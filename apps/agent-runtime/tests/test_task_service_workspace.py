import tempfile
import unittest
from pathlib import Path

from app.application.task_service import TaskService
from app.domain.models import ReviewPayload, StoryPlan, TaskCreateRequest, TaskMode, TaskStatus
from app.settings.config import Settings
from app.storage import db_repository
from app.storage.task_store import TaskLogStore
from tests.fakes import build_verified_gateway_model_catalog


class FakeGatewayClient:
    def __init__(self) -> None:
        self.calls = []

    def list_models(self):
        return [
            {
                "id": "gpt-5.4",
                "object": "model",
                "owned_by": "openai",
                "context_length": 272000,
                "max_output_tokens": 16000,
            },
            {"id": "glm-5.1", "object": "model", "owned_by": "zhipu"},
            {"id": "auditor-x", "object": "model", "owned_by": "test"},
            {"id": "synthesis-y", "object": "model", "owned_by": "test"},
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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)

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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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

    def test_workspace_chapter_catalog_keeps_full_planned_range(self) -> None:
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
                    prompt="写一部长篇悬疑小说",
                    model_id="gpt-5.4",
                    target_chapter_count=8,
                )
            )
            story_plan = StoryPlan(
                working_title="港口谜案",
                logline="档案员调查夜航失踪案。",
                world_notes=["潮湿港口"],
                character_notes=["女档案员"],
                planned_chapter_count=8,
                chapter_plan=[
                    {"number": 1, "title": "起始", "goal": "发现异常"},
                    {"number": 2, "title": "夜航", "goal": "追踪线索"},
                ],
            )
            review = ReviewPayload(
                type="outline_review",
                version="v1",
                summary="请审核首批章节计划。",
                story_plan=story_plan,
            )
            store.set_waiting_review(task.id, review, story_plan)

            workspace = service.get_workspace(task.id)

            self.assertEqual(len(workspace.chapter_catalog), 8)
            self.assertEqual([item.number for item in workspace.chapter_catalog], list(range(1, 9)))
            self.assertEqual(workspace.chapter_catalog[0].title, "起始")
            self.assertEqual(workspace.chapter_catalog[0].status, "ready_to_draft")
            self.assertEqual(workspace.chapter_catalog[2].status, "pending_outline")
            self.assertFalse(workspace.chapter_catalog[2].content_available)

    def test_workspace_exposes_pending_review_summary_without_review_body(self) -> None:
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
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            story_plan = StoryPlan(
                working_title="港口谜案",
                logline="档案员调查夜航失踪案。",
                world_notes=["潮湿港口"],
                character_notes=["女档案员"],
                chapter_plan=[{"number": 1, "title": "起始", "goal": "发现异常"}],
            )
            review = ReviewPayload(
                type="outline_review",
                version="v1",
                summary="请审核大纲。",
                story_plan=story_plan,
                revision_count=2,
            )
            store.set_waiting_review(task.id, review, story_plan)

            workspace = service.get_workspace(task.id)

            expected_keys = {
                "present",
                "review_type",
                "stage",
                "batch_index",
                "revision_count",
                "outline_phase",
                "summary",
            }
            self.assertTrue(workspace.pending_review_summary["present"])
            self.assertEqual(set(workspace.pending_review_summary.keys()), expected_keys)
            self.assertEqual(workspace.pending_review_summary["review_type"], "outline_review")
            self.assertEqual(workspace.pending_review_summary["stage"], "waiting_outline_review")
            self.assertIsNone(workspace.pending_review_summary["batch_index"])
            self.assertEqual(workspace.pending_review_summary["revision_count"], 2)
            self.assertIn("大纲", workspace.pending_review_summary["summary"])
            self.assertNotIn("story_plan", workspace.pending_review_summary)
            self.assertNotIn("chapter_pair", workspace.pending_review_summary)

    def test_workspace_exposes_pending_review_summary_stable_shape_without_review(self) -> None:
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
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )

            workspace = service.get_workspace(task.id)

            self.assertEqual(
                workspace.pending_review_summary,
                {
                    "present": False,
                    "review_type": "",
                    "stage": "created",
                    "batch_index": None,
                    "revision_count": 0,
                    "outline_phase": "",
                    "summary": "当前没有待审核内容。",
                },
            )

    def test_workspace_hides_stale_pending_review_summary_outside_waiting_review_status(self) -> None:
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
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            story_plan = StoryPlan(
                working_title="港口谜案",
                logline="档案员调查夜航失踪案。",
                world_notes=["潮湿港口"],
                character_notes=["女档案员"],
                chapter_plan=[{"number": 1, "title": "起始", "goal": "发现异常"}],
            )
            review = ReviewPayload(
                type="outline_review",
                version="v1",
                summary="旧的章节计划审核摘要不应继续展示。",
                story_plan=story_plan,
                revision_count=2,
            )
            store.set_waiting_review(task.id, review, story_plan)
            stale_task = store.get(task.id)
            stale_task.status = TaskStatus.DRAFTING
            stale_task.current_stage = "verification"
            stale_task.current_unit = "full-story-verification"
            stale_task.progress = 90
            store.save(stale_task)

            workspace = service.get_workspace(task.id)

            self.assertFalse(workspace.pending_review_summary["present"])
            self.assertEqual(workspace.pending_review_summary["review_type"], "")
            self.assertEqual(workspace.pending_review_summary["stage"], "verification")
            self.assertEqual(workspace.pending_review_summary["summary"], "当前没有待审核内容。")

    def test_workspace_pending_review_summary_omits_chapter_pair_body(self) -> None:
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
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            story_plan = StoryPlan(
                working_title="港口谜案",
                logline="档案员调查夜航失踪案。",
                world_notes=["潮湿港口"],
                character_notes=["女档案员"],
                chapter_plan=[{"number": 1, "title": "起始", "goal": "发现异常"}],
            )
            review = ReviewPayload(
                type="chapter_pair_review",
                version="v1",
                summary="等待章节审核。",
                batch_index=0,
                chapter_pair=[
                    {
                        "number": 1,
                        "title": "起始",
                        "summary": "发现异常",
                        "content": "章节正文泄露标记：这一段不能进入调试摘要。",
                    }
                ],
                completed_count=0,
                total_chapters=1,
                chapter_pair_revision_count=3,
            )
            store.set_waiting_chapter_review(task.id, review, story_plan=story_plan)

            workspace = service.get_workspace(task.id)

            self.assertEqual(
                set(workspace.pending_review_summary.keys()),
                {"present", "review_type", "stage", "batch_index", "revision_count", "outline_phase", "summary"},
            )
            self.assertTrue(workspace.pending_review_summary["present"])
            self.assertEqual(workspace.pending_review_summary["review_type"], "chapter_pair_review")
            self.assertEqual(workspace.pending_review_summary["stage"], "waiting_chapter_review")
            self.assertEqual(workspace.pending_review_summary["batch_index"], 0)
            self.assertEqual(workspace.pending_review_summary["revision_count"], 3)
            self.assertNotIn("chapter_pair", workspace.pending_review_summary)
            self.assertNotIn("章节正文泄露标记", workspace.pending_review_summary["summary"])

    def test_workspace_pending_review_summary_omits_verification_report(self) -> None:
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
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            story_plan = StoryPlan(
                working_title="港口谜案",
                logline="档案员调查夜航失踪案。",
                world_notes=["潮湿港口"],
                character_notes=["女档案员"],
                chapter_plan=[{"number": 1, "title": "起始", "goal": "发现异常"}],
            )
            review = ReviewPayload(
                type="verification_review",
                version="v1",
                summary="等待验证审核。",
                verification_report={
                    "summary": "验证报告泄露标记：这一段不能进入调试摘要。",
                    "raw_response": "raw response 不应进入 workspace 调试摘要。",
                    "prompt": "prompt 不应进入 workspace 调试摘要。",
                },
                verification_revision_count=4,
            )
            store.set_waiting_verification_review(task.id, review, story_plan=story_plan)

            workspace = service.get_workspace(task.id)

            self.assertEqual(
                set(workspace.pending_review_summary.keys()),
                {"present", "review_type", "stage", "batch_index", "revision_count", "outline_phase", "summary"},
            )
            self.assertTrue(workspace.pending_review_summary["present"])
            self.assertEqual(workspace.pending_review_summary["review_type"], "verification_review")
            self.assertEqual(workspace.pending_review_summary["stage"], "waiting_verification_review")
            self.assertIsNone(workspace.pending_review_summary["batch_index"])
            self.assertEqual(workspace.pending_review_summary["revision_count"], 4)
            self.assertNotIn("verification_report", workspace.pending_review_summary)
            self.assertNotIn("验证报告泄露标记", workspace.pending_review_summary["summary"])
            self.assertNotIn("raw_response", workspace.pending_review_summary)
            self.assertNotIn("prompt", workspace.pending_review_summary)

    def test_workspace_exposes_rag_status_summary_from_context_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)

            class ReadyRagService:
                config = type("Config", (), {"enabled": True})()

                def is_ready(self) -> bool:
                    return True

                def readiness_error(self) -> str:
                    return ""

            service = TaskService(
                store=store,
                engine=engine,
                model_catalog=model_catalog,
                rag_service=ReadyRagService(),
            )
            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            store.write_context_snapshot(
                task.id,
                stage="drafting",
                snapshot_name="draft-context",
                payload={
                    "task_id": task.id,
                    "stage": "drafting",
                    "cache_hit": False,
                    "budget": {"max_input_tokens": 256000},
                    "packet": {
                        "estimated_input_tokens": 4096,
                        "references_text": "RAG 参考内容只作为长度证据，不应原样返回。",
                    },
                    "compressed_references": [
                        {
                            "source_id": "rag-test-1",
                            "was_compressed": False,
                            "original_chars": 32,
                            "compressed_chars": 32,
                        }
                    ],
                },
            )

            workspace = service.get_workspace(task.id)

            self.assertTrue(workspace.rag_status["enabled"])
            self.assertTrue(workspace.rag_status["ready"])
            self.assertTrue(workspace.rag_status["injected"])
            self.assertEqual(workspace.rag_status["last_query_stage"], "drafting")
            self.assertEqual(workspace.rag_status["injection_evidence"], "context_snapshot")
            self.assertNotIn("hits", workspace.rag_status)
            self.assertNotIn("contexts", workspace.rag_status)
            self.assertNotIn("selected_contexts", workspace.rag_status)
            self.assertNotIn("references_text", workspace.rag_status)
            self.assertNotIn("RAG 参考内容", workspace.rag_status.get("summary", ""))

    def test_workspace_rag_status_does_not_treat_plain_reference_snapshot_as_injected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)

            class ReadyRagService:
                config = type("Config", (), {"enabled": True})()

                def is_ready(self) -> bool:
                    return True

                def readiness_error(self) -> str:
                    return ""

            service = TaskService(
                store=store,
                engine=engine,
                model_catalog=model_catalog,
                rag_service=ReadyRagService(),
            )
            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            store.write_context_snapshot(
                task.id,
                stage="drafting",
                snapshot_name="draft-context",
                payload={
                    "task_id": task.id,
                    "stage": "drafting",
                    "cache_hit": False,
                    "budget": {"max_input_tokens": 256000},
                    "packet": {
                        "estimated_input_tokens": 4096,
                        "references_text": "普通用户素材内容，不是 RAG 命中。",
                    },
                    "compressed_references": [
                        {
                            "source_id": "source-user-note-1",
                            "was_compressed": False,
                            "original_chars": 18,
                            "compressed_chars": 18,
                        }
                    ],
                },
            )

            workspace = service.get_workspace(task.id)

            self.assertFalse(workspace.rag_status["injected"])
            self.assertEqual(workspace.rag_status["injection_evidence"], "")
            self.assertEqual(workspace.rag_status["last_query_stage"], "")

    def test_workspace_rag_status_does_not_treat_failed_skipped_status_or_rebuild_events_as_injected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)

            class ReadyRagService:
                config = type("Config", (), {"enabled": True})()

                def is_ready(self) -> bool:
                    return True

                def readiness_error(self) -> str:
                    return ""

            service = TaskService(
                store=store,
                engine=engine,
                model_catalog=model_catalog,
                rag_service=ReadyRagService(),
            )
            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            store.append_event(
                task.id,
                stage="planning",
                message="RAG 检索失败，继续使用普通上下文。",
                event_type="rag.search_failed",
                payload={
                    "summary": "RAG 检索失败。",
                    "display_level": "public",
                    "error": "临时检索错误",
                    "rag_injected": True,
                    "rag_hit_count": 2,
                    "selected_hits": [{"doc_id": "rag-failed-1"}],
                },
            )
            store.append_event(
                task.id,
                stage="planning",
                message="RAG 检索已跳过。",
                event_type="rag.search_skipped",
                payload={
                    "summary": "RAG 检索已跳过。",
                    "display_level": "public",
                    "reason": "query_empty",
                    "rag_injected": True,
                    "selected_contexts": ["跳过事件不应视为已注入。"],
                    "hits": [{"doc_id": "rag-skipped-1"}],
                },
            )
            store.append_event(
                task.id,
                stage="verification",
                message="RAG 状态已刷新。",
                event_type="rag.status",
                payload={
                    "summary": "RAG 状态已刷新。",
                    "display_level": "public",
                    "rag_injected": True,
                    "rag_context_count": 3,
                },
            )
            store.append_event(
                task.id,
                stage="verification",
                message="RAG 索引重建状态已刷新。",
                event_type="rag.rebuild.status",
                payload={
                    "summary": "RAG 索引重建状态已刷新。",
                    "display_level": "public",
                    "rag_injected": True,
                    "selected_context_count": 4,
                },
            )

            workspace = service.get_workspace(task.id)

            self.assertFalse(workspace.rag_status["injected"])
            self.assertEqual(workspace.rag_status["injection_evidence"], "")
            self.assertEqual(workspace.rag_status["last_query_stage"], "planning")

    def test_workspace_rag_status_prefers_event_stage_over_context_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)

            class ReadyRagService:
                config = type("Config", (), {"enabled": True})()

                def is_ready(self) -> bool:
                    return True

                def readiness_error(self) -> str:
                    return ""

            service = TaskService(
                store=store,
                engine=engine,
                model_catalog=model_catalog,
                rag_service=ReadyRagService(),
            )
            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            store.write_context_snapshot(
                task.id,
                stage="drafting",
                snapshot_name="draft-context",
                payload={
                    "task_id": task.id,
                    "stage": "drafting",
                    "cache_hit": False,
                    "budget": {"max_input_tokens": 256000},
                    "packet": {
                        "estimated_input_tokens": 4096,
                        "references_text": "RAG 参考内容只作为长度证据，不应原样返回。",
                    },
                    "compressed_references": [],
                },
            )
            store.append_event(
                task.id,
                stage="verification",
                message="verification 阶段已注入 RAG 参考材料。",
                event_type="rag.injected",
                payload={"summary": "RAG 参考材料已注入。", "display_level": "public", "rag_injected": True},
            )

            workspace = service.get_workspace(task.id)

            self.assertTrue(workspace.rag_status["injected"])
            self.assertEqual(workspace.rag_status["injection_evidence"], "event")
            self.assertEqual(workspace.rag_status["last_query_stage"], "verification")

    def test_workspace_exposes_rag_status_when_rag_is_not_ready_or_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)

            class MissingRagService:
                config = type("Config", (), {"enabled": True})()

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

            workspace = service.get_workspace(task.id)

            self.assertTrue(workspace.rag_status["enabled"])
            self.assertFalse(workspace.rag_status["ready"])
            self.assertIn("尚未构建", workspace.rag_status["last_error"])

            service_without_rag = TaskService(store=store, engine=engine, model_catalog=model_catalog)
            workspace_without_rag = service_without_rag.get_workspace(task.id)

            self.assertFalse(workspace_without_rag.rag_status["enabled"])
            self.assertFalse(workspace_without_rag.rag_status["ready"])

    def test_workspace_rag_status_warns_when_readiness_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)

            class BrokenReadyRagService:
                config = type("Config", (), {"enabled": True})()

                def is_ready(self) -> bool:
                    raise RuntimeError("rag backend down")

                def readiness_error(self) -> str:
                    return ""

            service = TaskService(
                store=store,
                engine=engine,
                model_catalog=model_catalog,
                rag_service=BrokenReadyRagService(),
            )
            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )

            with self.assertLogs("app.application.task_service.queries", level="WARNING") as logs:
                workspace = service.get_workspace(task.id)

            self.assertTrue(workspace.rag_status["enabled"])
            self.assertFalse(workspace.rag_status["ready"])
            self.assertIn("rag backend down", workspace.rag_status["last_error"])
            self.assertIn("读取 RAG 工作区就绪状态失败", "\n".join(logs.output))

    def test_workspace_rag_status_warns_when_readiness_error_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = FakeEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)

            class BrokenReadinessErrorRagService:
                config = type("Config", (), {"enabled": True})()

                def is_ready(self) -> bool:
                    return False

                def readiness_error(self) -> str:
                    raise RuntimeError("rag status missing")

            service = TaskService(
                store=store,
                engine=engine,
                model_catalog=model_catalog,
                rag_service=BrokenReadinessErrorRagService(),
            )
            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )

            with self.assertLogs("app.application.task_service.queries", level="WARNING") as logs:
                workspace = service.get_workspace(task.id)

            self.assertTrue(workspace.rag_status["enabled"])
            self.assertFalse(workspace.rag_status["ready"])
            self.assertIn("rag status missing", workspace.rag_status["last_error"])
            self.assertIn("读取 RAG 工作区未就绪原因失败", "\n".join(logs.output))

    def test_workspace_exposes_creative_and_last_action_model_fields(self) -> None:
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
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            service.run_task(task.id, model_id="glm-5.1")

            workspace = service.get_workspace(task.id)

            self.assertEqual(workspace.meta.model_id, "gpt-5.4")
            self.assertEqual(workspace.meta.creative_model_id, "gpt-5.4")
            self.assertNotIn("default_model_id", workspace.meta.model_dump())
            self.assertEqual(workspace.meta.last_action_model_id, "glm-5.1")
            self.assertEqual(workspace.meta.last_action_kind, "run")
            self.assertEqual(workspace.request_preview["creative_model_id"], "gpt-5.4")
            self.assertNotIn("default_model_id", workspace.request_preview)
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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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

    def test_workspace_rebuilds_outline_batch_state_from_database_when_pending_review_is_missing(self) -> None:
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
                    prompt="写一部克制风格的都市悬疑小说",
                    model_id="gpt-5.4",
                )
            )
            stale_task = store.get(task.id)
            stale_task.status = TaskStatus.PLANNING
            stale_task.current_stage = "planning"
            stale_task.current_unit = "outline-revision"
            stale_task.progress = 20
            stale_task.pending_review = None
            store.save(stale_task)

            db_repository.create_chapter_plan_batch(
                task_id=task.id,
                batch_no=1,
                start_chapter=1,
                end_chapter=8,
                requested_count=20,
                effective_count=8,
                status="waiting_review",
            )
            for chapter_number in range(1, 9):
                db_repository.upsert_outline_chapter_plan(
                    task_id=task.id,
                    chapter_number=chapter_number,
                    title=f"第{chapter_number}章",
                    goal="推进主线",
                    outline_batch_no=1,
                    status="outline_planned",
                )

            workspace = service.get_workspace(task.id)

            self.assertEqual(workspace.outline_phase, "chapter_batches")
            self.assertEqual(workspace.outline_completed_count, 0)
            self.assertEqual(workspace.outline_total_count, 8)

    def test_workspace_keeps_waiting_manual_action_on_read_and_recommends_restart(self) -> None:
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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
            self.assertEqual(restart_option.preview.creative_model_id, task.model_id)
            self.assertNotIn("default_model_id", restart_option.preview.model_dump())
            self.assertTrue(restart_option.preview.will_resume_generation)
            self.assertEqual(store.get(task.id).status, TaskStatus.WAITING_MANUAL_ACTION)

    def test_historical_missing_or_offline_model_does_not_block_workspace_read_but_still_blocks_execution(self) -> None:
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

            for saved_model_id in ("retired-text-model", ""):
                with self.subTest(saved_model_id=saved_model_id):
                    task = service.create_task(
                        TaskCreateRequest(
                            mode=TaskMode.SHORT_STORY,
                            prompt="历史模型不可用时仍应可查看工作台",
                            model_id="gpt-5.4",
                        )
                    )
                    historical_task = store.get(task.id)
                    historical_task.model_id = saved_model_id
                    historical_task.status = TaskStatus.WAITING_MANUAL_ACTION
                    historical_task.current_stage = TaskStatus.WAITING_MANUAL_ACTION.value
                    store.save(historical_task)

                    workspace = service.get_workspace(task.id)

                    self.assertEqual(workspace.meta.model_id, saved_model_id)
                    self.assertEqual(workspace.meta.creative_model_id, saved_model_id)
                    self.assertEqual(workspace.request_preview["creative_model_id"], saved_model_id)
                    restart_option = next(item for item in workspace.recovery_options if item.action == "restart_from_input")
                    self.assertTrue(restart_option.available)
                    assert restart_option.preview is not None
                    self.assertEqual(restart_option.preview.creative_model_id, saved_model_id)
                    self.assertIn("gpt-5.4", restart_option.preview.allowed_model_ids)

            with self.assertRaisesRegex(ValueError, "不在当前供应商模型目录|没有已选模型"):
                service.recover_task(task.id, force=True)

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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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
