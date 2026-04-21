import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.application.task_service import TaskService
from app.domain.models import DraftResult, ReviewPayload, StoryPlan, TaskStatus
from app.domain.models import TaskCreateRequest, TaskMode
from app.llm.model_catalog import ModelCatalogService
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore


class FakeGatewayClient:
    def list_models(self):
        return [{"id": "gpt-5.4", "object": "model", "owned_by": "openai"}]


class FakeEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gateway_client = FakeGatewayClient()
        self.progress_callback = None

    def set_runtime_default_model(self, model_id: str) -> None:
        self.settings.default_chat_model = model_id


class TaskServiceSupervisorSeedTests(unittest.TestCase):
    def test_create_task_seeds_supervisor_plan(self) -> None:
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
                    prompt="写一个被海雾吞没的码头疑案",
                    model_id="gpt-5.4",
                )
            )

            self.assertIsNotNone(task.supervisor_plan)
            assert task.supervisor_plan is not None
            self.assertEqual(task.supervisor_plan.planner_version, "v1")
            self.assertEqual(task.supervisor_plan.subtasks[0].status.value, "ready")
            self.assertEqual(task.supervisor_plan.subtasks[1].status.value, "blocked")

    def test_run_task_advances_supervisor_plan_into_outline_planning(self) -> None:
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
            service._start_background = lambda *args, **kwargs: None

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一个暴风雨海港里的疑案",
                    model_id="gpt-5.4",
                )
            )

            snapshot = service.run_task(task.id)

            assert snapshot.supervisor_plan is not None
            self.assertEqual(snapshot.supervisor_plan.subtasks[0].status.value, "completed")
            self.assertEqual(snapshot.supervisor_plan.subtasks[1].status.value, "running")

    def test_sync_result_completed_advances_result_assembly_to_completed(self) -> None:
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
                    prompt="写一个旧港追凶故事",
                    model_id="gpt-5.4",
                )
            )
            service.graph = SimpleNamespace(
                get_state=lambda config: SimpleNamespace(
                    values={
                        "normalized_spec": {
                            "mode": "short_story",
                            "prompt": "写一个旧港追凶故事",
                            "genre": "",
                            "style": "",
                            "requested_target_words": 1800,
                            "target_words": 1800,
                            "audience": "",
                            "banned": "",
                            "title_hint": "",
                            "model_id": "gpt-5.4",
                        },
                        "story_plan": StoryPlan(
                            working_title="旧港追凶",
                            logline="档案员追查旧港血案。",
                            world_notes=["海雾"],
                            character_notes=["档案员"],
                            chapter_plan=[{"number": 1, "title": "起始", "goal": "发现线索"}],
                        ).model_dump(mode="json"),
                        "draft_result": DraftResult(
                            title="旧港追凶",
                            summary="案件揭开。",
                            body="正文",
                            chapters=[{"number": 1, "title": "起始", "summary": "发现线索", "content": "正文"}],
                        ).model_dump(mode="json"),
                    }
                )
            )

            record = service._sync_result(task.id, {})

            assert record.supervisor_plan is not None
            self.assertTrue(all(item.status.value == "completed" for item in record.supervisor_plan.subtasks))

    def test_run_task_sync_keeps_waiting_review_when_followup_sync_fails(self) -> None:
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
                    prompt="写一个旧港追凶故事",
                    model_id="gpt-5.4",
                )
            )

            interrupt_payload = ReviewPayload(
                type="outline_review",
                version="v1",
                summary="请审核大纲。",
            )
            service.graph = SimpleNamespace(
                invoke=lambda *_args, **_kwargs: {
                    "__interrupt__": [SimpleNamespace(value=interrupt_payload.model_dump(mode="json"))]
                },
                get_state=lambda _config: SimpleNamespace(
                    values={
                        "normalized_spec": {
                            "mode": "short_story",
                            "prompt": "写一个旧港追凶故事",
                            "genre": "",
                            "style": "",
                            "requested_target_words": 1800,
                            "target_words": 1800,
                            "audience": "",
                            "banned": "",
                            "title_hint": "",
                            "model_id": "gpt-5.4",
                        },
                        "story_plan": StoryPlan(
                            working_title="旧港追凶",
                            logline="档案员追查旧港血案。",
                            world_notes=["海雾"],
                            character_notes=["档案员"],
                            chapter_plan=[{"number": 1, "title": "起始", "goal": "发现线索"}],
                        ).model_dump(mode="json"),
                    }
                ),
            )

            original_sync_supervisor_plan = service._sync_supervisor_plan

            def failing_sync_supervisor_plan(task_id: str):
                original_sync_supervisor_plan(task_id)
                raise RuntimeError("supervisor sync failed")

            service._sync_supervisor_plan = failing_sync_supervisor_plan

            record = service._run_task_sync(task.id)

            self.assertEqual(record.status, TaskStatus.WAITING_OUTLINE_REVIEW)
            persisted = store.get(task.id)
            self.assertEqual(persisted.status, TaskStatus.WAITING_OUTLINE_REVIEW)
            self.assertIsNotNone(persisted.pending_review)

    def test_run_task_sync_writes_normalized_spec_before_graph_returns(self) -> None:
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
                    prompt="写一个旧港追凶故事",
                    model_id="gpt-5.4",
                )
            )
            interrupt_payload = ReviewPayload(
                type="outline_review",
                version="v1",
                summary="请审核大纲。",
            )

            def invoke_with_runtime_probe(*_args, **_kwargs):
                task_json = Path(store.root_dir) / "runs" / task.id / "state" / "task.json"
                payload = __import__("json").loads(task_json.read_text(encoding="utf-8"))
                normalized_spec = payload.get("normalized_spec") or {}
                if normalized_spec.get("prompt") != "写一个旧港追凶故事":
                    raise AssertionError("graph.invoke 执行期间 normalized_spec 尚未写回 task.json")
                if "workflow_guidance" not in normalized_spec or "style_guidance" not in normalized_spec:
                    raise AssertionError("normalized_spec 缺少运行时风格字段")
                return {"__interrupt__": [SimpleNamespace(value=interrupt_payload.model_dump(mode="json"))]}

            service.graph = SimpleNamespace(
                invoke=invoke_with_runtime_probe,
                get_state=lambda _config: SimpleNamespace(
                    values={
                        "normalized_spec": {
                            "mode": "short_story",
                            "prompt": "写一个旧港追凶故事",
                            "genre": "",
                            "style": "",
                            "workflow_guidance": "",
                            "style_guidance": "",
                            "requested_target_words": 1800,
                            "target_words": 1800,
                            "audience": "",
                            "banned": "",
                            "title_hint": "",
                            "model_id": "gpt-5.4",
                        },
                        "story_plan": StoryPlan(
                            working_title="旧港追凶",
                            logline="档案员追查旧港血案。",
                            world_notes=["海雾"],
                            character_notes=["档案员"],
                            chapter_plan=[{"number": 1, "title": "起始", "goal": "发现线索"}],
                        ).model_dump(mode="json"),
                    }
                ),
            )

            record = service._run_task_sync(task.id)

            self.assertEqual(record.status, TaskStatus.WAITING_OUTLINE_REVIEW)

    def test_start_background_does_not_override_stable_waiting_state(self) -> None:
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
                    prompt="写一个旧港追凶故事",
                    model_id="gpt-5.4",
                )
            )
            story_plan = StoryPlan(
                working_title="旧港追凶",
                logline="档案员追查旧港血案。",
                world_notes=["海雾"],
                character_notes=["档案员"],
                chapter_plan=[{"number": 1, "title": "起始", "goal": "发现线索"}],
            )
            review = ReviewPayload(
                type="outline_review",
                version="v1",
                summary="请审核大纲。",
            )
            def target() -> None:
                store.set_waiting_review(task.id, review, story_plan)
                raise RuntimeError("post-write failure")

            service._start_background(task.id, target)
            deadline = time.time() + 3
            while time.time() < deadline:
                persisted = store.get(task.id)
                if persisted.status == TaskStatus.WAITING_OUTLINE_REVIEW:
                    break
                time.sleep(0.05)
            time.sleep(0.2)

            persisted = store.get(task.id)
            self.assertEqual(persisted.status, TaskStatus.WAITING_OUTLINE_REVIEW)
            self.assertNotEqual(persisted.status, TaskStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
