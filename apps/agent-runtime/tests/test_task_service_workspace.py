import tempfile
import unittest
from pathlib import Path

from app.application.task_service import TaskService
from app.domain.models import TaskCreateRequest, TaskMode
from app.llm.model_catalog import ModelCatalogService
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore


class FakeGatewayClient:
    def __init__(self) -> None:
        self.calls = []

    def list_models(self):
        return [{"id": "gpt-5.4", "object": "model", "owned_by": "openai"}]

    def complete_json(self, messages, model=None):
        self.calls.append({"messages": [dict(item) for item in messages], "model": model})
        return {
            "working_title": "缓存命中测试标题",
            "logline": "缓存命中测试梗概",
            "world_notes": ["港口潮湿。"],
            "character_notes": ["主角是档案员。"],
            "chapter_plan": [
                {"number": 1, "title": "引子", "goal": "发现问题"},
                {"number": 2, "title": "推进", "goal": "继续追查"},
            ],
        }


class FakeEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gateway_client = FakeGatewayClient()
        self.progress_callback = None

    def set_runtime_default_model(self, model_id: str) -> None:
        self.settings.default_chat_model = model_id

    def build_story_plan(self, spec, reference_text, context_packet=None, model=None):
        from app.domain.models import StoryPlan

        payload = self.gateway_client.complete_json(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": spec["prompt"]},
            ],
            model=model,
        )
        return StoryPlan.model_validate(payload)


class TaskServiceWorkspaceTests(unittest.TestCase):
    def test_workspace_contains_model_capabilities_and_context_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            store.write_context_snapshot(
                task.id,
                stage="planning",
                snapshot_name="outline-context",
                payload={
                    "task_id": task.id,
                    "stage": "planning",
                    "cache_hit": False,
                    "cache_key": "context:test",
                    "budget": {"max_input_tokens": 256000},
                    "packet": {"estimated_input_tokens": 3200},
                    "compressed_references": [
                        {"was_compressed": True, "original_chars": 2000, "compressed_chars": 600}
                    ],
                },
            )

            workspace = service.get_workspace(task.id)

            self.assertEqual(workspace.meta.model_capabilities["context_window"]["max_input_tokens"], 256000)
            self.assertEqual(workspace.context_status["stage"], "planning")
            self.assertTrue(workspace.context_status["compression_applied"])
            self.assertEqual(workspace.context_status["cache_scope"], "runtime_context")
            self.assertEqual(workspace.response_cache_status, {})
            self.assertEqual(workspace.request_preview["model_capabilities"]["cache"]["runtime_context_cache"], True)

    def test_second_equivalent_task_hits_context_and_response_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            from app.llm.story_engine import StoryEngine

            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            engine.gateway_client = FakeGatewayClient()
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            payload = TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一部克制风格的都市悬疑小说",
                model_id="gpt-5.4",
            )
            first_task = service.create_task(payload)
            second_task = service.create_task(payload)

            service._run_task_sync(first_task.id)
            service._run_task_sync(second_task.id)
            workspace = service.get_workspace(second_task.id)

            self.assertEqual(len(engine.gateway_client.calls), 1)
            self.assertIn("cache_hit", workspace.context_status)
            self.assertEqual(workspace.context_status["cache_scope"], "runtime_context")
            self.assertTrue(workspace.response_cache_status["cache_hit"])
            self.assertTrue(any(event.event_type == "cache.hit" for event in service.get_task(second_task.id).events))
            self.assertEqual(workspace.response_cache_status["cache_scope"], "response_cache")

    def test_workspace_still_exposes_response_cache_status_when_cache_event_is_outside_recent_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            from app.llm.story_engine import StoryEngine

            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            engine.gateway_client = FakeGatewayClient()
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            payload = TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一部克制风格的都市悬疑小说",
                model_id="gpt-5.4",
            )
            first_task = service.create_task(payload)
            second_task = service.create_task(payload)

            service._run_task_sync(first_task.id)
            service._run_task_sync(second_task.id)

            for index in range(25):
                store.append_event(
                    second_task.id,
                    stage="waiting_outline_review",
                    message=f"后续事件 {index}",
                    event_type="trace.summary",
                    payload={"summary": f"后续事件 {index}"},
                )

            workspace = service.get_workspace(second_task.id)

            self.assertTrue(workspace.response_cache_status["cache_hit"])
            self.assertEqual(workspace.response_cache_status["cache_scope"], "response_cache")


if __name__ == "__main__":
    unittest.main()
