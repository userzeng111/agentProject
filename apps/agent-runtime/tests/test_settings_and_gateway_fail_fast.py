try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

import tempfile
import unittest
from pathlib import Path

from app.application.task_service import TaskService
from app.llm.gateway_client import GatewayClientError, OpenAICompatibleGatewayClient
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine
from app.settings import config as settings_config
from app.settings.config import Settings
from app.storage.database import get_session
from app.storage.db_models import TaskIndexModel
from app.storage.task_store import TaskLogStore
from app.domain.models import CreativeMode, NovelSize, TaskCreateRequest


class FailingGatewayClient:
    def list_models(self):
        return [{"id": "glm-5.1", "object": "model", "owned_by": "custom"}]

    def complete_json(self, messages, model=None):
        raise GatewayClientError("模拟网关请求失败")


class StubRawGatewayClient(OpenAICompatibleGatewayClient):
    def __init__(self, raw_response: str) -> None:
        super().__init__(base_url="http://example.com", api_key="test-key", model="test-model")
        self.raw_response = raw_response

    def complete(self, messages, model=None):
        return self.raw_response


class SettingsAndGatewayFailFastTests(unittest.TestCase):
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
            engine = StoryEngine(
                Settings(
                    _env_file=None,
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                    default_chat_model="glm-5.1",
                )
            )

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
                default_chat_model="glm-5.1",
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            engine.gateway_client = FailingGatewayClient()
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
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

    def test_task_index_persists_new_input_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                default_chat_model="glm-5.1",
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            engine.gateway_client = FailingGatewayClient()
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
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
                default_chat_model="gpt-5.4",
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


if __name__ == "__main__":
    unittest.main()
