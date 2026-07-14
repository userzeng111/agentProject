try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.application.task_service import TaskService
from app.llm.gateway_client import GatewayClientError, OpenAICompatibleGatewayClient
from app.llm.protocols import AnthropicAdapter, OpenAIAdapter
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine
from app.settings import config as settings_config
from app.settings.config import Settings
from app.storage.database import get_session
from app.storage.db_models import TaskIndexModel
from app.storage.task_store import TaskLogStore
from app.domain.models import CreativeMode, NovelSize, TaskCreateRequest
from tests.fakes import build_verified_gateway_model_catalog


class FailingGatewayClient:
    def list_models(self):
        return [{"id": "glm-5.1", "object": "model", "owned_by": "custom"}]

    def complete_json(self, messages, model=None, **kwargs):
        raise GatewayClientError("模拟网关请求失败")


class StubRawGatewayClient(OpenAICompatibleGatewayClient):
    def __init__(self, raw_response: str) -> None:
        super().__init__(base_url="http://example.com", api_key="test-key", model="test-model")
        self.raw_response = raw_response

    def complete(self, messages, model=None, **kwargs):
        return self.raw_response


class TimeoutCaptureGatewayClient(OpenAICompatibleGatewayClient):
    """用于捕获实际传入 httpx 的超时对象的 GatewayClient 子类。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.captured_timeout = None

    def _request(self, method, path, json=None):
        # 通过直接创建 Client 来捕获 timeout 对象
        import httpx
        client = httpx.Client(timeout=self._timeout, trust_env=False)
        self.captured_timeout = client.timeout
        client.close()
        # 返回一个伪造的 Response 避免后续逻辑报错
        class FakeResponse:
            status_code = 200
            content = b'{"choices":[{"message":{"content":"{}"}}]}'
            text = content.decode()
            def json(self):
                import json
                return json.loads(self.content)
        return FakeResponse()


class SettingsAndGatewayFailFastTests(unittest.TestCase):
    def test_settings_do_not_define_runtime_model_defaults(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual(settings.default_chat_model, "")
        self.assertEqual(settings.auto_review_auditor_model, "")
        self.assertEqual(settings.auto_review_synthesis_model, "")

    def test_removed_task_model_requires_explicit_replacement(self) -> None:
        class CurrentGateway:
            def list_models(self):
                return [{"id": "current-provider-model", "object": "model", "owned_by": "provider"}]

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                _env_file=None,
                LLM_API_KEY="",
                DEFAULT_CHAT_MODEL="",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            engine.gateway_client = CurrentGateway()
            catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=catalog)
            task = store.create_task(
                TaskCreateRequest(
                    prompt="恢复一个模型已下线的任务",
                    creative_mode=CreativeMode.ORIGINAL,
                    novel_size=NovelSize.SHORT,
                    chapter_word_min=1800,
                    model_id="removed-provider-model",
                )
            )

            with self.assertRaisesRegex(ValueError, "不在当前供应商模型目录"):
                service._resolve_task_model_id(task)

    def test_gateway_normalizes_root_base_url_for_openai_protocol(self) -> None:
        client = OpenAICompatibleGatewayClient(
            base_url="https://gateway.example.com",
            api_key="test-key",
            model="mimo-v2.5-pro",
            default_protocol="openai",
        )

        # 不再自动追加 /v1，用户配置完整路径
        self.assertEqual(
            client._build_url("/chat/completions", "openai"),
            "https://gateway.example.com/chat/completions",
        )
        self.assertEqual(
            client._build_url("/models", "openai"),
            "https://gateway.example.com/models",
        )

    def test_gateway_does_not_duplicate_v1_base_url(self) -> None:
        client = OpenAICompatibleGatewayClient(
            base_url="https://gateway.example.com/v1",
            api_key="test-key",
            model="mimo-v2.5-pro",
            default_protocol="openai",
        )

        self.assertEqual(
            client._build_url("/chat/completions", "openai"),
            "https://gateway.example.com/v1/chat/completions",
        )

    def test_gateway_preserves_custom_base_path(self) -> None:
        client = OpenAICompatibleGatewayClient(
            base_url="https://gateway.example.com/custom",
            api_key="test-key",
            model="mimo-v2.5-pro",
            default_protocol="openai",
        )

        self.assertEqual(
            client._build_url("/chat/completions", "openai"),
            "https://gateway.example.com/custom/chat/completions",
        )

    def test_gateway_normalizes_root_base_url_for_anthropic_protocol(self) -> None:
        client = OpenAICompatibleGatewayClient(
            base_url="https://gateway.example.com",
            api_key="test-key",
            model="claude-sonnet-4-6",
            default_protocol="anthropic",
            anthropic_version="2023-06-01",
        )

        # 不再自动追加 /v1，用户配置完整路径
        self.assertEqual(
            client._build_url("/messages", "anthropic"),
            "https://gateway.example.com/messages",
        )
        headers = client._headers_for_protocol("anthropic")
        self.assertEqual(headers["x-api-key"], "test-key")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["Authorization"], "Bearer test-key")

    def test_gateway_uses_injected_default_protocol_without_global_settings(self) -> None:
        client = OpenAICompatibleGatewayClient(
            base_url="https://gateway.example.com",
            api_key="test-key",
            model="unknown-model",
            default_protocol="anthropic",
        )

        self.assertIsInstance(client._get_adapter("unknown-model"), AnthropicAdapter)

    def test_gateway_model_protocol_overrides_take_precedence(self) -> None:
        client = OpenAICompatibleGatewayClient(
            base_url="https://gateway.example.com",
            api_key="test-key",
            model="mimo-v2.5-pro",
            default_protocol="openai",
            protocol_overrides={"K2.6": "anthropic"},
        )

        self.assertIsInstance(client._get_adapter("K2.6"), AnthropicAdapter)
        self.assertIsInstance(client._get_adapter("mimo-v2.5-pro"), OpenAIAdapter)

    def test_gateway_protocol_override_resolver_failure_logs_warning_and_uses_default_protocol(self) -> None:
        def raise_resolver():
            raise RuntimeError("runtime overrides broken")

        client = OpenAICompatibleGatewayClient(
            base_url="https://gateway.example.com",
            api_key="test-key",
            model="mimo-v2.5-pro",
            default_protocol="openai",
            protocol_overrides_resolver=raise_resolver,
        )

        with self.assertLogs("backend.gateway", level="WARNING") as logs:
            protocol = client._resolve_protocol("K2.7")

        self.assertEqual(protocol, "openai")
        self.assertTrue(any("读取动态模型协议覆盖失败" in message for message in logs.output))

    def test_prompt_cache_settings_failure_logs_warning_and_disables_prompt_cache(self) -> None:
        client = OpenAICompatibleGatewayClient(
            base_url="https://gateway.example.com",
            api_key="test-key",
            model="claude-sonnet-4-6",
            default_protocol="anthropic",
        )

        with patch("app.settings.config.get_settings", side_effect=RuntimeError("settings unavailable")):
            with self.assertLogs("backend.gateway", level="WARNING") as logs:
                kwargs = client._provider_prompt_cache_kwargs(AnthropicAdapter())

        self.assertEqual(kwargs, {})
        self.assertTrue(any("读取 provider prompt cache 设置失败" in message for message in logs.output))

    def test_settings_accept_anthropic_key_alias_without_forcing_protocol(self) -> None:
        settings = Settings(
            _env_file=None,
            ANTHROPIC_AUTH_TOKEN="alias-key",
            LLM_BASE_URL="https://gateway.example.com",
            DEFAULT_PROTOCOL="openai",
        )

        self.assertEqual(settings.openai_api_key, "alias-key")
        self.assertEqual(settings.default_protocol, "openai")

    def test_story_engine_passes_injected_protocol_to_gateway(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                _env_file=None,
                LLM_API_KEY="test-key",
                LLM_BASE_URL="https://gateway.example.com",
                DEFAULT_PROTOCOL="anthropic",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )

            engine = StoryEngine(settings)

            self.assertIsInstance(engine.gateway_client._get_adapter("unknown-model"), AnthropicAdapter)

    def test_complete_json_extracts_json_from_fenced_response_with_extra_text(self) -> None:
        client = StubRawGatewayClient(
            "下面是结果：\n```json\n{\"working_title\":\"雨夜监控室\",\"chapter_plan\":[]}\n```\n请查收。"
        )

        payload = client.complete_json([{"role": "user", "content": "test"}], model="test-model")

        self.assertEqual(payload["working_title"], "雨夜监控室")

    def test_complete_json_extracts_first_json_value_from_plain_text_wrapper(self) -> None:
        client = StubRawGatewayClient(
            "结果如下：{\"working_title\":\"雨站回声\",\"chapter_plan\":[]} 以上是最终答案。"
        )

        payload = client.complete_json([{"role": "user", "content": "test"}], model="test-model")

        self.assertEqual(payload["working_title"], "雨站回声")

    def test_complete_json_does_not_fall_through_to_nested_array_when_outer_object_is_invalid(self) -> None:
        client = StubRawGatewayClient(
            "```json\n{\"working_title\":\"雨夜监控室\",\"world_notes\":[\"高速服务区位于山区\"],\n```"
        )

        with self.assertRaisesRegex(GatewayClientError, "模型返回的 JSON 无法解析"):
            client.complete_json([{"role": "user", "content": "test"}], model="test-model")

    def test_settings_use_fixed_runtime_env_file_path(self) -> None:
        env_file = settings_config.Settings.model_config.get("env_file")

        self.assertIsNotNone(env_file)
        self.assertEqual(Path(env_file).resolve(), (Path(settings_config.__file__).resolve().parents[2] / ".env").resolve())

    def test_build_story_plan_raises_when_gateway_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                _env_file=None,
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                default_chat_model="",
                LLM_API_KEY="",
                LLM_BASE_URL="",
            )
            engine = StoryEngine(settings)

            with self.assertRaisesRegex(GatewayClientError, "模型网关"):
                engine.build_story_plan(
                    spec={
                        "mode": "short_story",
                        "prompt": "写一篇恐怖短篇",
                        "genre": "恐怖",
                        "style": "冷静克制",
                        "target_words": 1800,
                        "model_id": "glm-5.1",
                    },
                    reference_text="",
                    context_packet=None,
                    model="glm-5.1",
                )

    def test_task_service_marks_task_waiting_manual_action_when_gateway_request_fails_but_input_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                default_chat_model="",
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            engine.gateway_client = FailingGatewayClient()
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            task = service.create_task(
                TaskCreateRequest(
                    prompt="写一篇恐怖短篇",
                    creative_mode=CreativeMode.ORIGINAL,
                    novel_size=NovelSize.SHORT,
                    chapter_word_min=1800,
                    model_id="glm-5.1",
                )
            )

            with self.assertRaisesRegex(GatewayClientError, "模拟网关请求失败"):
                service._run_task_sync(task.id)

            failed = store.get(task.id)
            self.assertEqual(failed.status.value, "waiting_manual_action")
            self.assertEqual(failed.current_stage, "waiting_manual_action")
            self.assertIn("模拟网关请求失败", failed.error_message or "")
            self.assertEqual(failed.creative_mode.value, "original")
            self.assertEqual(failed.novel_size.value, "short")
            self.assertEqual(failed.chapter_word_min, 1800)
            self.assertEqual(failed.mode.value, "short_story")
            persisted = store.read_json(task.id, "task.json")
            self.assertEqual(persisted["creative_mode"], "original")
            self.assertEqual(persisted["novel_size"], "short")
            self.assertEqual(persisted["chapter_word_min"], 1800)

    def test_exchange_callback_redacts_raw_parse_failure_diagnostic_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                default_chat_model="",
                LLM_DIAGNOSTIC_RAW_RESPONSE_MAX_CHARS=12,
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)

            class GatewayWithMimo:
                def list_models(self):
                    return [{"id": "mimo-v2.5-pro", "object": "model", "owned_by": "mimo"}]

            engine.gateway_client = GatewayWithMimo()
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=model_catalog)
            task = store.create_task(
                TaskCreateRequest(
                    prompt="继续写同人小说",
                    creative_mode=CreativeMode.FANFIC,
                    novel_size=NovelSize.MEDIUM,
                    chapter_word_min=1800,
                    model_id="mimo-v2.5-pro",
                )
            )
            callback = service._build_exchange_callback(task.id)
            raw_response = '```json\n{"number":5,"content":"未完成'

            callback(
                {
                    "stage": "drafting",
                    "exchange_label": "chapter-05",
                    "model": "mimo-v2.5-pro",
                    "response_parse_failed": True,
                    "raw_response": raw_response,
                    "finish_reason": "length",
                    "parse_error": "模型返回的 JSON 无法解析",
                    "request_messages": [{"role": "user", "content": "生成第 5 章"}],
                    "prompt_diagnostics": {"message_count": 1},
                }
            )

            diagnostic = store.read_json(task.id, "context/drafting/chapter-05-raw-response.json")
            self.assertNotIn("raw_response", diagnostic)
            self.assertNotIn("request_messages", diagnostic)
            self.assertEqual(diagnostic["raw_response_preview"], raw_response[:12])
            self.assertTrue(diagnostic["raw_response_truncated"])
            self.assertEqual(diagnostic["request_message_count"], 1)
            self.assertEqual(diagnostic["finish_reason"], "length")
            self.assertEqual(diagnostic["parse_error"], "模型返回的 JSON 无法解析")
            latest_event = store.get(task.id).events[-1]
            self.assertEqual(latest_event.event_type, "model.response.parse_failed")
            self.assertEqual(
                latest_event.json_ref,
                f"tasklog/runs/{task.id}/context/drafting/chapter-05-raw-response.json",
            )

    def test_task_index_persists_new_input_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                default_chat_model="",
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            engine.gateway_client = FailingGatewayClient()
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            task = service.create_task(
                TaskCreateRequest(
                    prompt="写一篇短篇悬疑小说",
                    creative_mode=CreativeMode.ORIGINAL,
                    novel_size=NovelSize.SHORT,
                    chapter_word_min=1800,
                    model_id="glm-5.1",
                )
            )

            with get_session() as session:
                row = session.query(TaskIndexModel).filter_by(id=task.id).first()

            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row.mode, "short_story")
            self.assertEqual(row.creative_mode, "original")
            self.assertEqual(row.novel_size, "short")
            self.assertEqual(row.chapter_word_min, 1800)

    def test_create_task_rejects_unverified_gateway_only_model_for_novel_workflow(self) -> None:
        class GatewayWithUnknownModel:
            def list_models(self):
                return [{"id": "unknown-model-xyz", "object": "model", "owned_by": "custom"}]

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                default_chat_model="",
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            engine.gateway_client = GatewayWithUnknownModel()
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            with self.assertRaisesRegex(ValueError, "未完成兼容性验证"):
                service.create_task(
                    TaskCreateRequest(
                        prompt="写一个修罗场都市医生故事",
                        creative_mode=CreativeMode.STYLE_REMIX,
                        novel_size=NovelSize.LONG,
                        chapter_word_min=2200,
                        model_id="unknown-model-xyz",
                        style_profile_id="wozhenmeixiangchongshengya",
                    )
                )


    def test_gateway_client_default_timeout(self):
        client = TimeoutCaptureGatewayClient(
            base_url="http://example.com", api_key="test-key", model="test-model"
        )
        client._request("GET", "/models")
        self.assertEqual(client.captured_timeout.connect, 30.0)
        self.assertEqual(client.captured_timeout.read, 240.0)
        self.assertEqual(client.captured_timeout.write, 60.0)
        self.assertEqual(client.captured_timeout.pool, 60.0)

    def test_gateway_client_custom_dict_timeout(self):
        client = TimeoutCaptureGatewayClient(
            base_url="http://example.com",
            api_key="test-key",
            model="test-model",
            timeout={"connect": 5.0, "read": 600.0, "write": 10.0, "pool": 15.0},
        )
        client._request("GET", "/models")
        self.assertEqual(client.captured_timeout.connect, 5.0)
        self.assertEqual(client.captured_timeout.read, 600.0)
        self.assertEqual(client.captured_timeout.write, 10.0)
        self.assertEqual(client.captured_timeout.pool, 15.0)

    def test_gateway_client_custom_httpx_timeout(self):
        import httpx
        custom = httpx.Timeout(connect=1.0, read=2.0, write=3.0, pool=4.0)
        client = TimeoutCaptureGatewayClient(
            base_url="http://example.com",
            api_key="test-key",
            model="test-model",
            timeout=custom,
        )
        client._request("GET", "/models")
        self.assertEqual(client.captured_timeout.connect, 1.0)
        self.assertEqual(client.captured_timeout.read, 2.0)
        self.assertEqual(client.captured_timeout.write, 3.0)
        self.assertEqual(client.captured_timeout.pool, 4.0)

    def test_story_engine_passes_timeout_from_settings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                _env_file=None,
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                default_chat_model="",
                LLM_API_KEY="test-key",
                LLM_TIMEOUT_CONNECT="10.0",
                LLM_TIMEOUT_READ="500.0",
                LLM_TIMEOUT_WRITE="20.0",
                LLM_TIMEOUT_POOL="25.0",
            )
            engine = StoryEngine(settings)
            self.assertIsNotNone(engine.gateway_client)
            # 直接检查 StoryEngine 创建的 gateway_client 的超时属性
            self.assertEqual(engine.gateway_client._timeout.connect, 10.0)
            self.assertEqual(engine.gateway_client._timeout.read, 500.0)
            self.assertEqual(engine.gateway_client._timeout.write, 20.0)
            self.assertEqual(engine.gateway_client._timeout.pool, 25.0)


def test_settings_warns_and_returns_empty_overrides_when_protocol_override_json_is_invalid(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        settings = Settings(
            _env_file=None,
            MODEL_PROTOCOL_OVERRIDES="{ broken json",
        )

    assert settings.model_protocol_overrides == {}
    assert any("MODEL_PROTOCOL_OVERRIDES" in record.message for record in caplog.records)


if __name__ == "__main__":
    unittest.main()
