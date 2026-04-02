import datetime
import tempfile
import unittest
from pathlib import Path

if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc

from app.application.task_service import TaskService
from app.llm.gateway_client import GatewayClientError
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine
from app.settings import config as settings_config
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore
from app.domain.models import TaskCreateRequest, TaskMode


class FailingGatewayClient:
    def list_models(self):
        return [{"id": "glm-5.1", "object": "model", "owned_by": "custom"}]

    def complete_json(self, messages, model=None):
        raise GatewayClientError("模拟网关请求失败")


class SettingsAndGatewayFailFastTests(unittest.TestCase):
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

    def test_task_service_marks_task_failed_when_gateway_request_fails(self) -> None:
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
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一篇恐怖短篇",
                    model_id="glm-5.1",
                )
            )

            with self.assertRaisesRegex(GatewayClientError, "模拟网关请求失败"):
                service._run_task_sync(task.id)

            failed = store.get(task.id)
            self.assertEqual(failed.status.value, "failed")
            self.assertIn("模拟网关请求失败", failed.error_message or "")


if __name__ == "__main__":
    unittest.main()
