import tempfile
import unittest
from pathlib import Path

from app.application.task_service import TaskService
from app.domain.models import TaskCreateRequest, TaskMode, TaskStatus
from app.llm.model_catalog import ModelCatalogService
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore


class FakeGatewayClient:
    def __init__(self) -> None:
        self.calls = []

    def list_models(self):
        return [
            {"id": "gpt-5.4", "object": "model", "owned_by": "openai"},
            {"id": "glm-5.1", "object": "model", "owned_by": "zhipu"},
        ]

    def complete_json(self, messages, model=None, **kwargs):
        self.calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
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
    def test_task_level_auto_review_false_must_override_global_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
            service = TaskService(
                store=store,
                engine=engine,
                model_catalog=model_catalog,
                auto_review=True,
                auto_review_policy={
                    "auditor_model": "auditor-x",
                    "synthesis_model": "synthesis-y",
                },
            )

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                    auto_review=False,
                )
            )
            stored = service.get_task(task.id)
            initial_state = service._initial_state(stored)

            self.assertFalse(stored.auto_review)
            self.assertFalse(initial_state["auto_review"])
            self.assertEqual(
                initial_state["auto_review_policy"],
                {
                    "auditor_model": "auditor-x",
                    "synthesis_model": "synthesis-y",
                },
            )

    def test_create_task_persists_task_level_auto_review_and_initial_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
            service = TaskService(
                store=store,
                engine=engine,
                model_catalog=model_catalog,
                auto_review=False,
                auto_review_policy={
                    "auditor_model": "auditor-x",
                    "synthesis_model": "synthesis-y",
                },
            )

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                    auto_review=True,
                )
            )
            stored = service.get_task(task.id)
            initial_state = service._initial_state(stored)

            self.assertTrue(stored.auto_review)
            self.assertEqual(
                stored.auto_review_policy,
                {
                    "auditor_model": "auditor-x",
                    "synthesis_model": "synthesis-y",
                },
            )
            self.assertTrue(initial_state["auto_review"])
            self.assertEqual(
                initial_state["auto_review_policy"],
                {
                    "auditor_model": "auditor-x",
                    "synthesis_model": "synthesis-y",
                },
            )

    def test_run_task_fails_fast_when_novel_rag_library_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)

            class MissingRagService:
                def is_ready(self) -> bool:
                    return False

                def readiness_error(self) -> str:
                    return "小说RAG知识库尚未构建，请先前往设置页完成索引构建。"

            service = TaskService(
                store=store,
                engine=engine,
                model_catalog=model_catalog,
                rag_service=MissingRagService(),
            )

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )

            with self.assertRaisesRegex(ValueError, "小说RAG知识库尚未构建"):
                service.run_task(task.id)

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
            self.assertIsNotNone(workspace.supervisor_plan)
            assert workspace.supervisor_plan is not None
            self.assertEqual(workspace.supervisor_plan.subtasks[0].kind, "reference_analysis")
            self.assertEqual(workspace.supervisor_plan.subtasks[0].status.value, "ready")

    def test_workspace_exposes_default_and_last_action_model_fields(self) -> None:
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
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            service.run_task(task.id, model_id="glm-5.1")

            workspace = service.get_workspace(task.id)

            self.assertEqual(workspace.meta.model_id, "gpt-5.4")
            self.assertEqual(workspace.meta.default_model_id, "gpt-5.4")
            self.assertEqual(workspace.meta.last_action_model_id, "glm-5.1")
            self.assertEqual(workspace.meta.last_action_kind, "run")
            self.assertEqual(workspace.request_preview["default_model_id"], "gpt-5.4")
            self.assertEqual(workspace.request_preview["last_action_model_id"], "glm-5.1")
            self.assertEqual(workspace.request_preview["last_action_kind"], "run")

    def test_workspace_exposes_explicit_recovery_contract_fields(self) -> None:
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

            workspace = service.get_workspace(task.id)

            self.assertEqual(workspace.allowed_actions, [])
            self.assertEqual(workspace.recommended_action, "")
            self.assertEqual(workspace.blocked_reason, "")
            self.assertFalse(workspace.state_reconciled)
            self.assertEqual(workspace.reconciliation_kind, "")
            self.assertEqual(workspace.reconciliation_summary, "")
            self.assertEqual(len(workspace.recovery_options), 2)
            self.assertEqual(workspace.recovery_options[0].action, "recover_to_stable")
            self.assertFalse(workspace.recovery_options[0].available)
            self.assertEqual(workspace.recovery_options[1].action, "restart_from_input")
            self.assertFalse(workspace.recovery_options[1].available)

    def test_workspace_keeps_waiting_manual_action_on_read_and_recommends_restart(self) -> None:
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
            broken = store.get(task.id)
            broken.status = TaskStatus.WAITING_MANUAL_ACTION
            broken.current_stage = "waiting_manual_action"
            broken.current_unit = None
            broken.story_plan = None
            broken.pending_review = None
            broken.error_message = "运行失败：模型网关暂时不可用。"
            broken.normalized_spec = {
                "mode": "short_story",
                "creative_mode": "original",
                "novel_size": "short",
                "prompt": "写一部克制风格的都市悬疑小说",
                "model_id": "gpt-5.4",
            }
            store.save(broken)

            workspace = service.get_workspace(task.id)

            self.assertEqual(workspace.meta.status, TaskStatus.WAITING_MANUAL_ACTION)
            self.assertEqual(store.get(task.id).status, TaskStatus.WAITING_MANUAL_ACTION)
            self.assertEqual(workspace.allowed_actions, ["restart_from_input"])
            self.assertEqual(workspace.recommended_action, "restart_from_input")
            self.assertEqual(workspace.recovery_options[0].action, "recover_to_stable")
            self.assertFalse(workspace.recovery_options[0].available)
            self.assertEqual(workspace.recovery_options[1].action, "restart_from_input")
            self.assertTrue(workspace.recovery_options[1].available)

    def test_dashboard_treats_dead_statuses_as_failed_attention_items(self) -> None:
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

            waiting_manual = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="任务一",
                    model_id="gpt-5.4",
                )
            )
            assembling = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="任务二",
                    model_id="gpt-5.4",
                )
            )
            cancelled = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="任务三",
                    model_id="gpt-5.4",
                )
            )

            waiting_manual_task = store.get(waiting_manual.id)
            waiting_manual_task.status = TaskStatus.WAITING_MANUAL_ACTION
            waiting_manual_task.current_stage = "waiting_manual_action"
            store.save(waiting_manual_task)

            assembling_task = store.get(assembling.id)
            assembling_task.status = TaskStatus.ASSEMBLING
            assembling_task.current_stage = "assembling"
            store.save(assembling_task)

            cancelled_task = store.get(cancelled.id)
            cancelled_task.status = TaskStatus.CANCELLED
            cancelled_task.current_stage = "cancelled"
            store.save(cancelled_task)

            dashboard = service.get_dashboard()
            failed_ids = {item.task_id for item in dashboard.failed_tasks}
            continue_ids = {item.task_id for item in dashboard.continue_tasks}
            running_ids = {item.task_id for item in dashboard.running_tasks}

            self.assertIn(waiting_manual.id, failed_ids)
            self.assertIn(assembling.id, failed_ids)
            self.assertIn(cancelled.id, failed_ids)
            self.assertNotIn(waiting_manual.id, continue_ids)
            self.assertNotIn(assembling.id, running_ids)
            self.assertNotIn(cancelled.id, continue_ids)

    def test_workspace_meta_exposes_error_message_for_waiting_manual_action(self) -> None:
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
                    prompt="任务一",
                    model_id="gpt-5.4",
                )
            )
            store.set_waiting_manual_action(
                task.id,
                "任务当前无法恢复，缺少可恢复的稳定产物，已转入待人工处理。",
                payload={
                    "summary": "任务当前无法恢复，缺少可恢复的稳定产物，已转入待人工处理。",
                    "display_level": "public",
                    "reason": "missing_stable_state",
                },
            )

            workspace = service.get_workspace(task.id)

            self.assertEqual(workspace.meta.status, TaskStatus.WAITING_MANUAL_ACTION)
            self.assertEqual(
                workspace.meta.error_message,
                "任务当前无法恢复，缺少可恢复的稳定产物，已转入待人工处理。",
            )
            self.assertEqual(workspace.allowed_actions, ["restart_from_input"])
            self.assertEqual(workspace.recommended_action, "restart_from_input")
            self.assertEqual(workspace.blocked_reason, "missing_stable_state")
            self.assertFalse(workspace.state_reconciled)
            self.assertEqual(workspace.reconciliation_kind, "")
            self.assertEqual(workspace.reconciliation_summary, "")
            self.assertEqual(len(workspace.recovery_options), 2)
            stable_option, restart_option = workspace.recovery_options
            self.assertEqual(stable_option.action, "recover_to_stable")
            self.assertFalse(stable_option.available)
            self.assertIsNone(stable_option.preview)
            self.assertEqual(restart_option.action, "restart_from_input")
            self.assertTrue(restart_option.available)
            self.assertIsNotNone(restart_option.preview)
            assert restart_option.preview is not None
            self.assertEqual(restart_option.preview.target_stage, "planning")
            self.assertTrue(restart_option.preview.will_resume_generation)
            self.assertEqual(store.get(task.id).status, TaskStatus.WAITING_MANUAL_ACTION)

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
