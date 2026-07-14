import tempfile
import time
import unittest
import json
from pathlib import Path
from types import SimpleNamespace

from app.application.task_service import TaskService
from app.domain.models import DraftResult, ReviewPayload, StoryPlan, TaskStatus
from app.domain.models import TaskCreateRequest, TaskMode
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore
from tests.fakes import build_verified_gateway_model_catalog


class FakeGatewayClient:
    def list_models(self):
        return [
            {"id": "gpt-5.4", "object": "model", "owned_by": "openai"},
            {"id": "glm-5.1", "object": "model", "owned_by": "zhipu"},
        ]


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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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

    def test_run_task_action_model_override_does_not_persist_task_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            background_calls: list[tuple] = []
            service._start_background = lambda *args, **kwargs: background_calls.append((args, kwargs))

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一个暴风雨海港里的疑案",
                    model_id="gpt-5.4",
                )
            )

            service.run_task(task.id, model_id="glm-5.1")

            self.assertEqual(store.get(task.id).model_id, "gpt-5.4")
            self.assertEqual(background_calls[0][0], (task.id, service._run_task_sync, task.id, "glm-5.1"))

    def test_sync_result_completed_advances_result_assembly_to_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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

    def test_sync_result_rebuilds_completed_result_from_chapter_files_when_checkpoint_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
            service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.LONG_STORY,
                    prompt="写一个九章校园重生故事",
                    model_id="gpt-5.4",
                )
            )
            story_plan = StoryPlan(
                working_title="九章旧校园",
                logline="主角重回校园补完遗憾。",
                world_notes=["旧校园"],
                character_notes=["重生主角"],
                planned_chapter_count=9,
                chapter_plan=[
                    {"number": number, "title": f"第{number}章", "goal": f"推进{number}"}
                    for number in range(1, 10)
                ],
            )
            for number in range(1, 10):
                service._write_chapter_file(
                    task.id,
                    chapter_number=number,
                    title=f"第{number}章",
                    summary=f"第{number}章摘要",
                    content=f"第{number}章正文",
                )

            stale_chapters = [
                {"number": number, "title": f"第{number}章", "summary": f"第{number}章摘要", "content": f"旧第{number}章正文"}
                for number in range(1, 5)
            ]
            service.graph = SimpleNamespace(
                get_state=lambda config: SimpleNamespace(
                    values={
                        "normalized_spec": {
                            "mode": "long_story",
                            "prompt": "写一个九章校园重生故事",
                            "genre": "",
                            "style": "",
                            "chapter_word_min": 1800,
                            "chapter_word_max": 2340,
                            "model_id": "gpt-5.4",
                        },
                        "story_plan": story_plan.model_dump(mode="json"),
                        "draft_result": DraftResult(
                            title="九章旧校园",
                            summary="旧结果只有四章。",
                            body="旧正文",
                            chapters=stale_chapters,
                        ).model_dump(mode="json"),
                    }
                )
            )

            record = service._sync_result(task.id, {})

            self.assertEqual(record.status, TaskStatus.COMPLETED)
            self.assertIsNotNone(record.draft_result)
            assert record.draft_result is not None
            self.assertEqual(len(record.draft_result.chapters), 9)
            self.assertEqual(record.draft_result.chapters[-1].number, 9)
            self.assertEqual(record.draft_result.chapters[-1].content, "第9章正文")
            self.assertEqual(record.storage_state, "runs")

            result_path = Path(tmp_dir) / "tasklog" / "runs" / task.id / "result.json"
            result_payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(len(result_payload["chapters"]), 9)
            artifacts_index = json.loads(
                (Path(tmp_dir) / "tasklog" / "runs" / task.id / "artifacts" / "index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                [item["id"] for item in artifacts_index if item["type"] == "chapter"],
                [f"chapter-{number:02d}" for number in range(1, 10)],
            )

    def test_run_task_sync_keeps_waiting_review_when_followup_sync_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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

    def test_run_task_sync_persists_task_default_model_in_normalized_spec_after_action_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
                invoke=lambda *_args, **_kwargs: {"__interrupt__": [SimpleNamespace(value=interrupt_payload.model_dump(mode="json"))]},
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
                            "model_id": "glm-5.1",
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

            service._run_task_sync(task.id, "glm-5.1")

            self.assertEqual(store.get(task.id).model_id, "gpt-5.4")
            self.assertEqual(store.get(task.id).normalized_spec.get("model_id"), "gpt-5.4")

    def test_start_background_does_not_override_stable_waiting_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
