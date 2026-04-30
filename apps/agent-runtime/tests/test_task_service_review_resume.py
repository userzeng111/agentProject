try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.application.task_service import TaskService
from app.domain.models import ReviewPayload, StoryPlan, TaskCreateRequest, TaskMode, TaskStatus
from app.llm.model_catalog import ModelCatalogService
from app.settings.config import Settings
from app.storage.database import init_db
from app.storage.task_store import TaskLogStore
from app.storage.db_repository import create_batch, update_project_status


from tests.fakes import FakeGatewayClient


class FakeEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gateway_client = FakeGatewayClient()
        self.progress_callback = None

    def set_runtime_default_model(self, model_id: str) -> None:
        self.settings.default_chat_model = model_id


class RecordingRagService:
    def __init__(self) -> None:
        self.chapter_calls = []

    def search_for_story_chapter(
        self,
        *,
        spec,
        story_plan,
        batch_index,
        batch_size=2,
        completed_chapters,
    ):
        self.chapter_calls.append(
            {
                "spec": spec,
                "story_plan": story_plan,
                "batch_index": batch_index,
                "batch_size": batch_size,
                "completed_chapters": completed_chapters,
            }
        )
        return object()

    def build_reference_materials(self, result, *, prefix, start_priority=40):
        return []


class TaskServiceReviewResumeTests(unittest.TestCase):
    def _build_service(self):
        tmp_dir = tempfile.TemporaryDirectory()
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="gpt-5.4",
            tasklog_root=str(Path(tmp_dir.name) / "tasklog"),
        )
        store = TaskLogStore(root_dir=str(Path(tmp_dir.name) / "tasklog"))
        engine = FakeEngine(settings)
        model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
        service = TaskService(store=store, engine=engine, model_catalog=model_catalog)
        return tmp_dir, store, service

    def _write_outline_history(
        self,
        store,
        task_id: str,
        *,
        filename: str,
        title: str = "恐怖短篇",
        chapter_count: int = 2,
    ) -> None:
        chapter_plan = [
            {"number": number, "title": f"第{number}章", "goal": f"目标{number}"}
            for number in range(1, chapter_count + 1)
        ]
        payload = {
            "working_title": title,
            "logline": f"{title} 梗概",
            "world_notes": ["旧公寓"],
            "character_notes": ["独居主角"],
            "chapter_plan": chapter_plan,
        }
        store.write_message_history(
            task_id,
            stage="planning",
            history=[
                {"role": "system", "content": "s"},
                {"role": "user", "content": "u"},
                {"role": "assistant", "content": __import__('json').dumps(payload, ensure_ascii=False)},
            ],
            filename=filename,
        )

    def test_recover_task_restores_outline_review_from_latest_outline_history(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        broken = store.get(task.id)
        broken.status = TaskStatus.PLANNING
        broken.current_stage = "planning"
        broken.current_unit = "outline-revision"
        broken.story_plan = None
        broken.pending_review = None
        store.save(broken)

        self._write_outline_history(store, task.id, filename="outline-history", title="旧标题", chapter_count=2)
        self._write_outline_history(store, task.id, filename="outline-revision-history", title="新标题", chapter_count=3)

        recovered = service.recover_task(task.id, force=True)

        self.assertEqual(recovered.status, TaskStatus.WAITING_OUTLINE_REVIEW)
        self.assertEqual(recovered.current_stage, "waiting_outline_review")
        self.assertIsNotNone(recovered.story_plan)
        assert recovered.story_plan is not None
        self.assertEqual(recovered.story_plan.working_title, "新标题")
        self.assertIsNotNone(recovered.pending_review)
        assert recovered.pending_review is not None
        self.assertEqual(recovered.pending_review.type, "outline_review")
        self.assertEqual(recovered.pending_review.revision_count, 1)

    def test_recover_task_restores_missing_story_plan_for_waiting_chapter_review(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        broken = store.get(task.id)
        broken.story_plan = None
        broken.pending_review = ReviewPayload(
            type="chapter_pair_review",
            version="v1",
            summary="请审核章节对。",
            batch_index=2,
            chapter_pair=[
                {
                    "number": 3,
                    "title": "第三章",
                    "summary": "章节摘要",
                    "content": "第三章正文",
                }
            ],
            completed_count=2,
            total_chapters=4,
        )
        broken.status = TaskStatus.WAITING_CHAPTER_REVIEW
        broken.current_stage = "waiting_chapter_review"
        broken.current_unit = "chapter-pair-2"
        store.save(broken)

        self._write_outline_history(store, task.id, filename="outline-history", title="章节恢复标题", chapter_count=4)

        recovered = service.recover_task(task.id, force=True)

        self.assertEqual(recovered.status, TaskStatus.WAITING_CHAPTER_REVIEW)
        self.assertIsNotNone(recovered.story_plan)
        assert recovered.story_plan is not None
        self.assertEqual(recovered.story_plan.working_title, "章节恢复标题")
        response = service.get_review(task.id)
        self.assertEqual(response.review_type, "chapter_pair_review")
        self.assertIsNotNone(response.outline_markdown)

    def test_resume_seed_passes_actual_chapter_pair_size_to_rag_search(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        rag_service = RecordingRagService()
        service.rag_service = rag_service

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇悬疑",
                model_id="gpt-5.4",
                target_words=6000,
            )
        )
        task = store.get(task.id)
        task.normalized_spec = {
            "mode": "long_story",
            "prompt": "写一篇长篇悬疑",
            "genre": "",
            "style": "",
            "requested_target_words": 6000,
            "target_words": 6000,
            "audience": "",
            "banned": "",
            "title_hint": "",
            "model_id": "gpt-5.4",
        }
        task.story_plan = StoryPlan(
            working_title="雾中楼",
            logline="主角调查旧楼失踪案。",
            world_notes=[],
            character_notes=[],
            planned_chapter_count=4,
            chapter_plan=[
                {"number": number, "title": f"第{number}章", "goal": f"线索{number}"}
                for number in range(1, 5)
            ],
        )
        task.pending_review = ReviewPayload(
            type="chapter_pair_review",
            version="v1",
            summary="请审核章节对。",
            batch_index=1,
            chapter_pair=[
                {
                    "number": 2,
                    "title": "第二章",
                    "summary": "调查展开",
                    "content": "第二章正文",
                },
                {
                    "number": 3,
                    "title": "第三章",
                    "summary": "发现矛盾",
                    "content": "第三章正文",
                },
            ],
            completed_count=1,
            total_chapters=4,
        )
        store.save(task)

        seed = service._resume_seed_state(store.get(task.id))

        self.assertIsNotNone(seed)
        self.assertEqual(rag_service.chapter_calls[0]["batch_size"], 2)

    def test_recover_task_marks_unrecoverable_task_waiting_manual_action(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        broken = store.get(task.id)
        broken.status = TaskStatus.PLANNING
        broken.current_stage = "planning"
        broken.current_unit = "outline-revision"
        broken.story_plan = None
        broken.pending_review = None
        store.save(broken)

        with self.assertRaisesRegex(ValueError, "当前没有可回填的稳定阶段"):
            service.recover_task(task.id, force=True)

        current = store.get(task.id)
        self.assertEqual(current.status, TaskStatus.PLANNING)
        self.assertEqual(current.current_stage, "planning")

    def test_recover_task_restores_outline_review_from_waiting_manual_action_when_history_exists(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.FANFIC,
                prompt="主角拥有神级武魂，在斗罗开后宫。",
                model_id="gpt-5.4",
                target_words=3000,
            )
        )
        broken = store.get(task.id)
        broken.status = TaskStatus.WAITING_MANUAL_ACTION
        broken.current_stage = "waiting_manual_action"
        broken.current_unit = None
        broken.story_plan = None
        broken.pending_review = None
        broken.error_message = "任务当前无法恢复，缺少可恢复的稳定产物，已转入待人工处理。"
        store.save(broken)

        self._write_outline_history(store, task.id, filename="outline-history", title="斗罗后宫录", chapter_count=12)

        recovered = service.recover_task(task.id)

        self.assertEqual(recovered.status, TaskStatus.WAITING_OUTLINE_REVIEW)
        self.assertEqual(recovered.current_stage, "waiting_outline_review")
        self.assertIsNotNone(recovered.story_plan)
        assert recovered.story_plan is not None
        self.assertEqual(recovered.story_plan.working_title, "斗罗后宫录")
        self.assertIsNotNone(recovered.pending_review)
        assert recovered.pending_review is not None
        self.assertEqual(recovered.pending_review.type, "outline_review")

    def test_recover_task_requeues_planning_with_model_override_when_no_stable_state(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇港口悬疑小说",
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
            "prompt": "写一篇港口悬疑小说",
            "model_id": "gpt-5.4",
        }
        store.save(broken)

        background_calls: list[tuple[str, str, tuple[object, ...]]] = []

        def fake_start_background(task_id: str, target, *args: object) -> None:
            background_calls.append((task_id, target.__name__, args))

        service._start_background = fake_start_background

        with self.assertRaisesRegex(ValueError, "当前没有可回填的稳定阶段"):
            service.recover_task(task.id, force=True, model_id="glm-5.1")

        self.assertEqual(store.get(task.id).status, TaskStatus.WAITING_MANUAL_ACTION)
        self.assertEqual(background_calls, [])

    def test_recover_task_restart_from_input_requeues_planning_with_model_override(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇港口悬疑小说",
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
            "prompt": "写一篇港口悬疑小说",
            "model_id": "gpt-5.4",
        }
        store.save(broken)

        background_calls: list[tuple[str, str, tuple[object, ...]]] = []

        def fake_start_background(task_id: str, target, *args: object) -> None:
            background_calls.append((task_id, target.__name__, args))

        service._start_background = fake_start_background

        recovered = service.recover_task(
            task.id,
            force=True,
            model_id="glm-5.1",
            recovery_mode="restart_from_input",
        )

        self.assertEqual(recovered.status, TaskStatus.PLANNING)
        self.assertEqual(recovered.current_stage, "planning")
        self.assertEqual(store.get(task.id).model_id, "gpt-5.4")
        self.assertEqual(background_calls, [(task.id, "_run_task_sync", (task.id, "glm-5.1"))])

    def test_resume_task_action_model_override_does_not_persist_task_default_model(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        review = ReviewPayload(
            type="verification_review",
            version="v1",
            summary="请审核全文一致性验证报告。",
            verification_report={"overall_score": 20, "issues": [{"severity": "critical"}]},
        )
        store.set_waiting_verification_review(task.id, review)

        background_calls: list[tuple[str, str, tuple[object, ...]]] = []

        def fake_start_background(task_id: str, target, *args: object) -> None:
            background_calls.append((task_id, target.__name__, args))

        service._start_background = fake_start_background

        snapshot = service.resume_task(task.id, approved=False, comment="继续修", model_id="glm-5.1")

        self.assertEqual(snapshot.status.value, "drafting")
        self.assertEqual(store.get(task.id).model_id, "gpt-5.4")
        self.assertEqual(background_calls, [(task.id, "_resume_task_sync", (task.id, False, "继续修", "glm-5.1"))])

    def test_get_review_does_not_auto_recover_outline_review_from_history(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        broken = store.get(task.id)
        broken.status = TaskStatus.PLANNING
        broken.current_stage = "planning"
        broken.current_unit = "outline-revision"
        broken.story_plan = None
        broken.pending_review = None
        store.save(broken)
        self._write_outline_history(store, task.id, filename="outline-revision-history", title="自动恢复标题", chapter_count=2)

        response = service.get_review(task.id)

        self.assertEqual(response.review_type, "outline_review")
        self.assertEqual(response.summary, "当前审核上下文不可用，请先执行恢复动作。")
        self.assertEqual(response.allowed_actions, ["recover_to_stable", "restart_from_input"])
        self.assertEqual(response.recommended_action, "recover_to_stable")
        self.assertFalse(response.state_reconciled)
        self.assertEqual(len(response.recovery_options), 2)
        stable_option, restart_option = response.recovery_options
        self.assertEqual(stable_option.action, "recover_to_stable")
        self.assertTrue(stable_option.available)
        self.assertIsNotNone(stable_option.preview)
        assert stable_option.preview is not None
        self.assertEqual(stable_option.preview.target_stage, "waiting_outline_review")
        self.assertFalse(stable_option.preview.will_resume_generation)
        self.assertEqual(restart_option.action, "restart_from_input")
        self.assertTrue(restart_option.available)
        restored = store.get(task.id)
        self.assertEqual(restored.status, TaskStatus.PLANNING)

    def test_get_review_reconciles_stale_review_state_without_restart(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
                target_words=1500,
            )
        )
        task = store.get(task.id)
        task.story_plan = StoryPlan(
            working_title="恐怖短篇",
            logline="主角在夜里听见诡异敲门声。",
            world_notes=["旧公寓"],
            character_notes=["独居主角"],
            planned_chapter_count=4,
            chapter_plan=[
                {"number": 1, "title": "第一章", "goal": "听见异响"},
                {"number": 2, "title": "第二章", "goal": "查明真相"},
                {"number": 3, "title": "第三章", "goal": "发现线索"},
                {"number": 4, "title": "第四章", "goal": "逼近真相"},
            ],
        )
        task.pending_review = ReviewPayload(
            type="chapter_pair_review",
            version="v1",
            summary="请审核当前章节批次。",
            batch_index=2,
            chapter_pair=[
                {
                    "number": 3,
                    "title": "第三章",
                    "summary": "章节摘要",
                    "content": "第三章正文",
                },
                {
                    "number": 4,
                    "title": "第四章",
                    "summary": "章节摘要",
                    "content": "第四章正文",
                },
            ],
            completed_count=2,
            total_chapters=4,
        )
        task.status = TaskStatus.WAITING_CHAPTER_REVIEW
        task.current_stage = "waiting_chapter_review"
        task.current_unit = "chapter-pair-2"
        store.save(task)

        service._ensure_novel_project_seeded(task)
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_VERIFICATION_REVIEW.value,
            completed_chapter_count=4,
            next_chapter_number=5,
            active_batch_no=None,
            active_continue_request_id="",
        )

        response = service.get_review(task.id)

        self.assertEqual(response.review_type, "verification_review")
        self.assertTrue(response.state_reconciled)
        self.assertEqual(response.reconciliation_kind, "stale_review_state")
        self.assertEqual(response.reconciliation_summary, "已自动校正到最新稳定审核状态。")
        self.assertEqual(response.allowed_actions, [])
        repaired = store.get(task.id)
        self.assertEqual(repaired.status, TaskStatus.WAITING_VERIFICATION_REVIEW)

    def test_workspace_recovery_preview_points_to_specific_chapter_generation_target(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇校园悬疑短篇",
                model_id="gpt-5.4",
                target_words=1600,
            )
        )
        task = store.get(task.id)
        task.story_plan = StoryPlan(
            working_title="旧校钟声",
            logline="学生在深夜追查教学楼异响来源。",
            world_notes=["旧教学楼夜间封闭。"],
            character_notes=["主角是学生会干事。"],
            planned_chapter_count=4,
            chapter_plan=[
                {"number": 1, "title": "第一章", "goal": "听见钟声"},
                {"number": 2, "title": "第二章", "goal": "排查旧楼"},
                {"number": 3, "title": "第三章", "goal": "锁定线索"},
                {"number": 4, "title": "第四章", "goal": "揭开真相"},
            ],
        )
        task.status = TaskStatus.WAITING_MANUAL_ACTION
        task.current_stage = "waiting_manual_action"
        task.error_message = "继续创作失败：第 4 章生成过程中断。"
        store.save(task)

        service._ensure_novel_project_seeded(task)
        create_batch(
            task.id,
            continue_request_id="req-4",
            requested_count=1,
            effective_count=1,
            actual_start_chapter=4,
        )
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_MANUAL_ACTION.value,
            completed_chapter_count=3,
            next_chapter_number=4,
            active_batch_no=1,
            active_continue_request_id="req-4",
            blocked_from_status=TaskStatus.READY_FOR_BATCH.value,
            current_generating_chapter_number=4,
        )

        workspace = service.get_workspace(task.id)

        stable_option = next(item for item in (workspace.recovery_options or []) if item.action == "recover_to_stable")
        self.assertTrue(stable_option.available)
        self.assertIsNotNone(stable_option.preview)
        assert stable_option.preview is not None
        self.assertEqual(stable_option.preview.target_stage, "waiting_chapter_generation")
        self.assertEqual(stable_option.preview.target_chapter_number, 4)
        self.assertEqual(stable_option.preview.target_chapter_numbers, [4])
        self.assertFalse(stable_option.preview.reuse_existing_draft)

    def test_workspace_recovery_preview_keeps_chapter_target_when_failed_batch_is_not_active(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇校园悬疑短篇",
                model_id="gpt-5.4",
                target_words=1600,
            )
        )
        task = store.get(task.id)
        task.story_plan = StoryPlan(
            working_title="旧校钟声",
            logline="学生在深夜追查教学楼异响来源。",
            world_notes=["旧教学楼夜间封闭。"],
            character_notes=["主角是学生会干事。"],
            planned_chapter_count=4,
            chapter_plan=[
                {"number": 1, "title": "第一章", "goal": "听见钟声"},
                {"number": 2, "title": "第二章", "goal": "排查旧楼"},
                {"number": 3, "title": "第三章", "goal": "锁定线索"},
                {"number": 4, "title": "第四章", "goal": "揭开真相"},
            ],
        )
        task.status = TaskStatus.WAITING_MANUAL_ACTION
        task.current_stage = "waiting_manual_action"
        task.error_message = "继续创作失败：模型不可用。"
        store.save(task)

        service._ensure_novel_project_seeded(task)
        batch = create_batch(
            task.id,
            continue_request_id="req-4",
            requested_count=1,
            effective_count=1,
            actual_start_chapter=4,
        )
        from app.storage.db_repository import mark_batch_failed

        mark_batch_failed(task.id, batch.batch_no)
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_MANUAL_ACTION.value,
            completed_chapter_count=3,
            next_chapter_number=4,
            active_batch_no=None,
            active_continue_request_id="",
            blocked_from_status=TaskStatus.READY_FOR_BATCH.value,
            current_generating_chapter_number=4,
        )

        workspace = service.get_workspace(task.id)

        stable_option = next(item for item in (workspace.recovery_options or []) if item.action == "recover_to_stable")
        assert stable_option.preview is not None
        self.assertEqual(stable_option.preview.target_stage, "waiting_chapter_generation")
        self.assertEqual(stable_option.preview.target_stage_label, "恢复到第 4 章待生成")
        self.assertEqual(stable_option.preview.target_chapter_number, 4)

    def test_current_generating_chapter_number_falls_back_to_requested_start_when_no_new_chapter_event(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇校园悬疑长篇",
                model_id="gpt-5.4",
                target_words=2000,
            )
        )
        task = store.get(task.id)
        task.story_plan = StoryPlan(
            working_title="旧校钟声",
            logline="学生在深夜追查教学楼异响来源。",
            world_notes=["旧教学楼夜间封闭。"],
            character_notes=["主角是学生会干事。"],
            planned_chapter_count=6,
            chapter_plan=[
                {"number": i, "title": f"第{i}章", "goal": f"推进{i}"} for i in range(1, 7)
            ],
        )
        store.save(task)
        service._ensure_novel_project_seeded(task)
        store.append_event(
            task.id,
            stage="drafting",
            message="上一批次开始生成第 3 章",
            event_type="chapter.started",
            payload={"chapter_number": 3},
        )

        self.assertEqual(service._current_generating_chapter_number_from_error(task.id, 4), 4)

    def test_init_db_migrates_missing_current_generating_chapter_number_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legacy.sqlite3"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE novel_project (
                        task_id VARCHAR(64) PRIMARY KEY,
                        novel_title VARCHAR(512) DEFAULT '',
                        creative_mode VARCHAR(32) DEFAULT '',
                        novel_size VARCHAR(16) DEFAULT '',
                        target_chapter_count INTEGER DEFAULT 0,
                        chapter_count_min INTEGER DEFAULT 0,
                        chapter_count_max INTEGER DEFAULT 0,
                        planned_chapter_count INTEGER DEFAULT 0,
                        chapter_word_min INTEGER DEFAULT 1800,
                        chapter_word_max INTEGER DEFAULT 1800,
                        default_batch_size INTEGER DEFAULT 3,
                        completed_chapter_count INTEGER DEFAULT 0,
                        next_chapter_number INTEGER DEFAULT 1,
                        status VARCHAR(64) DEFAULT 'created',
                        active_batch_no INTEGER,
                        active_continue_request_id VARCHAR(128) DEFAULT '',
                        blocked_from_status VARCHAR(64) DEFAULT '',
                        last_checkpoint_stage VARCHAR(64) DEFAULT '',
                        last_consistency_state VARCHAR(64) DEFAULT '',
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            init_db(db_path)

            verify_connection = sqlite3.connect(db_path)
            try:
                columns = {
                    row[1]
                    for row in verify_connection.execute("PRAGMA table_info('novel_project')")
                }
            finally:
                verify_connection.close()

            self.assertIn("current_generating_chapter_number", columns)

    def test_recover_task_rebuilds_corrupted_chapter_pair_from_history(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.STYLE_REMIX,
                prompt="写一篇学院玄幻长篇",
                model_id="gpt-5.4",
                target_words=8000,
            )
        )
        broken = store.get(task.id)
        broken.normalized_spec = {
            "mode": "style_remix",
            "prompt": "写一篇学院玄幻长篇",
            "genre": "玄幻",
            "style": "热血成长",
            "requested_target_words": 8000,
            "target_words": 8000,
            "audience": "",
            "banned": "",
            "title_hint": "",
            "model_id": "gpt-5.4",
        }
        broken.story_plan = None
        broken.pending_review = ReviewPayload(
            type="chapter_pair_review",
            version="v1",
            summary="请审核章节对。",
            batch_index=0,
            chapter_pair=[
                {
                    "number": number,
                    "title": f"脏章节{number}",
                    "summary": "脏摘要",
                    "content": "脏正文",
                }
                for number in range(1, 9)
            ],
            completed_count=0,
            total_chapters=8,
        )
        broken.status = TaskStatus.WAITING_CHAPTER_REVIEW
        broken.current_stage = "waiting_chapter_review"
        broken.current_unit = "chapter-pair-0"
        store.save(broken)
        self._write_outline_history(store, task.id, filename="outline-history", title="恢复标题", chapter_count=8)
        store.write_message_history(
            task.id,
            stage="drafting",
            history=[
                {"role": "system", "content": "s"},
                {"role": "user", "content": "u"},
                {"role": "assistant", "content": "{\"number\": 1, \"title\": \"第一章\", \"summary\": \"摘要\", \"content\": \"第一章正文\"}"},
            ],
            filename="chapter-01-history",
        )
        store.write_message_history(
            task.id,
            stage="drafting",
            history=[
                {"role": "system", "content": "s"},
                {"role": "user", "content": "u"},
                {"role": "assistant", "content": "{\"number\": 2, \"title\": \"第二章\", \"summary\": \"摘要\", \"content\": \"第二章正文\"}"},
            ],
            filename="chapter-02-history",
        )

        recovered = service.recover_task(task.id, force=True)

        assert recovered.pending_review is not None
        self.assertEqual(len(recovered.pending_review.chapter_pair or []), 2)
        self.assertEqual(
            [item.title for item in (recovered.pending_review.chapter_pair or [])],
            ["第一章", "第二章"],
        )

    def test_verification_reject_moves_task_into_background_processing_and_blocks_duplicate_submit(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        review = ReviewPayload(
            type="verification_review",
            version="v1",
            summary="请审核全文一致性验证报告。",
            verification_report={"overall_score": 20, "issues": [{"severity": "critical"}]},
        )
        store.set_waiting_verification_review(task.id, review)
        service._start_background = lambda *args, **kwargs: None

        snapshot = service.resume_task(task.id, approved=False, comment="")

        self.assertEqual(snapshot.status.value, "drafting")
        self.assertEqual(snapshot.current_stage, "verification")
        self.assertEqual(snapshot.current_unit, "verification")
        self.assertEqual(snapshot.events[-1].message, "人工审核已驳回，正在根据验证意见修复。")

        with self.assertRaisesRegex(ValueError, "当前任务没有待恢复的审核节点"):
            service.resume_task(task.id, approved=False, comment="")

    def test_review_history_exposes_rejected_and_repairing_events(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        review = ReviewPayload(
            type="verification_review",
            version="v1",
            summary="请审核全文一致性验证报告。",
            verification_report={"overall_score": 20, "issues": [{"severity": "critical"}]},
        )
        store.set_waiting_verification_review(task.id, review)
        store.append_event(
            task.id,
            stage="review_decision",
            message="收到人工审核结果（驳回），准备修订。",
            event_type="task.review.rejected",
        )
        store.append_event(
            task.id,
            stage="verification",
            message="verification 阶段已记录模型上下文链：fix-issues",
            event_type="context.history.updated",
            payload={"exchange_label": "fix-issues"},
        )

        history = service._review_history(store.get(task.id))

        self.assertEqual([item["action"] for item in history[-3:]], ["waiting", "rejected", "repairing"])
        self.assertEqual(history[-1]["comment"], "已进入验证问题修复阶段。")

    def test_outline_reject_can_resume_from_planning_status(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        review = ReviewPayload(
            type="outline_review",
            version="v1",
            summary="请审核大纲。",
        )
        task = store.get(task.id)
        task.pending_review = review
        task.status = task.status.WAITING_OUTLINE_REVIEW
        task.current_stage = "waiting_outline_review"
        store.save(task)

        service._start_background = lambda *args, **kwargs: None
        service.resume_task(task.id, approved=False, comment="")

        resumed = store.get(task.id)
        self.assertEqual(resumed.status.value, "planning")

        service._sync_result = lambda task_id, result, review_comment="": store.get(task_id)
        service.graph = type(
            "FakeGraph",
            (),
            {"invoke": lambda self, command, config=None: {}},
        )()

        try:
            service._resume_task_sync(task.id, approved=False, comment="打回")
        except ValueError as exc:  # pragma: no cover - 红灯断言
            self.fail(f"_resume_task_sync 不应拒绝 planning 状态: {exc}")

    def test_outline_approve_moves_task_to_ready_for_batch_without_background_resume(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                prompt="写一个长篇都市医生修罗场故事",
                creative_mode="original",
                novel_size="long",
                target_chapter_count=100,
                model_id="gpt-5.4",
            )
        )
        story_plan = StoryPlan(
            working_title="白衣修罗场",
            logline="年轻医生在都市权贵与情感纠葛中崛起。",
            world_notes=["现代都市医院体系"],
            character_notes=["男主是年轻医生"],
            planned_chapter_count=100,
            chapter_plan=[
                {"number": 1, "title": "入院风波", "goal": "主角初登场"},
                {"number": 2, "title": "夜班急诊", "goal": "建立职业能力"},
            ],
        )
        review = ReviewPayload(
            type="outline_review",
            version="v1",
            summary="请审核大纲。",
            story_plan=story_plan,
        )
        store.set_waiting_review(task.id, review, story_plan)

        background_calls: list[tuple] = []
        service._start_background = lambda *args, **kwargs: background_calls.append((args, kwargs))

        snapshot = service.resume_task(task.id, approved=True, comment="通过")

        self.assertEqual(snapshot.status.value, "ready_for_batch")
        self.assertEqual(snapshot.current_stage, "ready_for_batch")
        self.assertIsNone(snapshot.pending_review)
        self.assertEqual(background_calls, [])

    def test_get_review_preserves_outline_revision_count(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        review = ReviewPayload(
            type="outline_review",
            version="v1",
            summary="请审核大纲。",
            revision_count=3,
        )
        task = store.get(task.id)
        task.pending_review = review
        task.status = task.status.WAITING_OUTLINE_REVIEW
        task.current_stage = "waiting_outline_review"
        store.save(task)

        response = service.get_review(task.id)

        self.assertEqual(response.review_type, "outline_review")
        self.assertEqual(response.revision_count, 3)

    def test_get_review_without_pending_review_uses_last_waiting_review_type(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
            )
        )
        review = ReviewPayload(
            type="chapter_pair_review",
            version="v1",
            summary="请审核章节对。",
            batch_index=0,
            chapter_pair=[
                {
                    "number": 1,
                    "title": "第一章",
                    "summary": "章节摘要",
                    "content": "章节正文",
                }
            ],
            completed_count=0,
            total_chapters=2,
        )
        store.set_waiting_chapter_review(task.id, review)
        task = store.get(task.id)
        task.story_plan = StoryPlan(
            working_title="恐怖短篇",
            logline="主角在夜里听见诡异敲门声。",
            world_notes=["旧公寓"],
            character_notes=["独居主角"],
            chapter_plan=[
                {"number": 1, "title": "第一章", "goal": "听见异响"},
                {"number": 2, "title": "第二章", "goal": "查明真相"},
            ],
        )
        task.pending_review = None
        task.status = task.status.COMPLETED
        task.current_stage = "completed"
        store.save(task)

        response = service.get_review(task.id)

        self.assertEqual(response.review_type, "chapter_pair_review")

    def test_resume_chapter_review_rehydrates_missing_checkpoint_state(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
                target_words=1500,
            )
        )
        task = store.get(task.id)
        task.normalized_spec = {
            "mode": "short_story",
            "prompt": "写一篇恐怖短篇",
            "genre": "恐怖",
            "style": "冷静克制",
            "requested_target_words": 1500,
            "target_words": 1500,
            "chapter_word_min": 1500,
            "chapter_word_max": 1950,
            "audience": "",
            "banned": "",
            "title_hint": "",
            "model_id": "gpt-5.4",
        }
        task.story_plan = StoryPlan(
            working_title="恐怖短篇",
            logline="主角在夜里听见诡异敲门声。",
            world_notes=["旧公寓"],
            character_notes=["独居主角"],
            chapter_plan=[
                {"number": 1, "title": "第一章", "goal": "听见异响"},
                {"number": 2, "title": "第二章", "goal": "查明真相"},
                {"number": 3, "title": "第三章", "goal": "发现线索"},
                {"number": 4, "title": "第四章", "goal": "逼近真相"},
            ],
        )
        review = ReviewPayload(
            type="chapter_pair_review",
            version="v1",
            summary="请审核章节对。",
            batch_index=2,
            chapter_pair=[
                {
                    "number": 3,
                    "title": "第三章",
                    "summary": "章节摘要",
                    "content": "第三章正文",
                },
                {
                    "number": 4,
                    "title": "第四章",
                    "summary": "章节摘要",
                    "content": "第四章正文",
                },
            ],
            completed_count=2,
            total_chapters=4,
            chapter_pair_revision_count=1,
        )
        task.pending_review = review
        task.status = task.status.WAITING_CHAPTER_REVIEW
        task.current_stage = "waiting_chapter_review"
        store.save(task)

        store.write_message_history(
            task.id,
            stage="drafting",
            history=[
                {"role": "system", "content": "s"},
                {"role": "user", "content": "u"},
                {"role": "assistant", "content": "{\"number\": 1, \"title\": \"第一章\", \"summary\": \"摘要\", \"content\": \"第一章正文\"}"},
            ],
            filename="chapter-01-history",
        )
        store.write_message_history(
            task.id,
            stage="drafting",
            history=[
                {"role": "system", "content": "s"},
                {"role": "user", "content": "u"},
                {"role": "assistant", "content": "{\"number\": 2, \"title\": \"第二章\", \"summary\": \"摘要\", \"content\": \"第二章正文\"}"},
            ],
            filename="chapter-02-history",
        )

        class FakeGraph:
            def __init__(self):
                self.updated = None

            def get_state(self, config):
                return SimpleNamespace(values={})

            def update_state(self, config, values, as_node=None, task_id=None):
                self.updated = {"config": config, "values": values, "as_node": as_node, "task_id": task_id}
                return config

            def invoke(self, command, config=None):
                return {}

        fake_graph = FakeGraph()
        service.graph = fake_graph
        service._sync_result = lambda task_id, result, review_comment="": store.get(task_id)

        try:
            service._resume_task_sync(task.id, approved=True, comment="继续")
        except Exception as exc:  # pragma: no cover
            self.fail(f"_resume_task_sync 不应因缺少检查点状态失败: {exc}")

        self.assertIsNotNone(fake_graph.updated)
        self.assertEqual(fake_graph.updated["as_node"], "draft_chapter_pair")
        self.assertIn("input_payload", fake_graph.updated["values"])
        self.assertEqual(len(fake_graph.updated["values"]["completed_chapters"]), 2)
        self.assertEqual(len(fake_graph.updated["values"]["current_chapter_pair"]), 2)

    def test_get_review_syncs_stale_chapter_review_to_verification_review_when_project_already_advanced(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
                target_words=1500,
            )
        )
        task = store.get(task.id)
        task.story_plan = StoryPlan(
            working_title="恐怖短篇",
            logline="主角在夜里听见诡异敲门声。",
            world_notes=["旧公寓"],
            character_notes=["独居主角"],
            planned_chapter_count=4,
            chapter_plan=[
                {"number": 1, "title": "第一章", "goal": "听见异响"},
                {"number": 2, "title": "第二章", "goal": "查明真相"},
                {"number": 3, "title": "第三章", "goal": "发现线索"},
                {"number": 4, "title": "第四章", "goal": "逼近真相"},
            ],
        )
        task.pending_review = ReviewPayload(
            type="chapter_pair_review",
            version="v1",
            summary="请审核章节对。",
            batch_index=2,
            chapter_pair=[
                {
                    "number": 3,
                    "title": "第三章",
                    "summary": "章节摘要",
                    "content": "第三章正文",
                },
                {
                    "number": 4,
                    "title": "第四章",
                    "summary": "章节摘要",
                    "content": "第四章正文",
                },
            ],
            completed_count=2,
            total_chapters=4,
        )
        task.status = TaskStatus.WAITING_CHAPTER_REVIEW
        task.current_stage = "waiting_chapter_review"
        task.current_unit = "chapter-pair-2"
        store.save(task)

        service._ensure_novel_project_seeded(task)
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_VERIFICATION_REVIEW.value,
            completed_chapter_count=4,
            next_chapter_number=5,
            active_batch_no=None,
            active_continue_request_id="",
        )

        response = service.get_review(task.id)

        self.assertEqual(response.review_type, "verification_review")
        self.assertTrue(response.state_reconciled)
        self.assertEqual(response.reconciliation_kind, "stale_review_state")
        self.assertEqual(response.recommended_action, "")
        repaired = store.get(task.id)
        self.assertEqual(repaired.status, TaskStatus.WAITING_VERIFICATION_REVIEW)
        self.assertIsNotNone(repaired.pending_review)
        assert repaired.pending_review is not None
        self.assertEqual(repaired.pending_review.type, "verification_review")

    def test_resume_task_syncs_stale_chapter_review_before_submitting(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇恐怖短篇",
                model_id="gpt-5.4",
                target_words=1500,
            )
        )
        task = store.get(task.id)
        task.story_plan = StoryPlan(
            working_title="恐怖短篇",
            logline="主角在夜里听见诡异敲门声。",
            world_notes=["旧公寓"],
            character_notes=["独居主角"],
            planned_chapter_count=4,
            chapter_plan=[
                {"number": 1, "title": "第一章", "goal": "听见异响"},
                {"number": 2, "title": "第二章", "goal": "查明真相"},
                {"number": 3, "title": "第三章", "goal": "发现线索"},
                {"number": 4, "title": "第四章", "goal": "逼近真相"},
            ],
        )
        task.pending_review = ReviewPayload(
            type="chapter_pair_review",
            version="v1",
            summary="请审核章节对。",
            batch_index=2,
            chapter_pair=[
                {
                    "number": 3,
                    "title": "第三章",
                    "summary": "章节摘要",
                    "content": "第三章正文",
                },
                {
                    "number": 4,
                    "title": "第四章",
                    "summary": "章节摘要",
                    "content": "第四章正文",
                },
            ],
            completed_count=2,
            total_chapters=4,
        )
        task.status = TaskStatus.WAITING_CHAPTER_REVIEW
        task.current_stage = "waiting_chapter_review"
        task.current_unit = "chapter-pair-2"
        store.save(task)

        service._ensure_novel_project_seeded(task)
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_VERIFICATION_REVIEW.value,
            completed_chapter_count=4,
            next_chapter_number=5,
            active_batch_no=None,
            active_continue_request_id="",
        )

        background_calls: list[tuple] = []
        service._start_background = lambda *args, **kwargs: background_calls.append((args, kwargs))

        snapshot = service.resume_task(task.id, approved=True, comment="通过")

        self.assertEqual(snapshot.status, TaskStatus.DRAFTING)
        self.assertEqual(snapshot.current_stage, "verification")
        self.assertEqual(snapshot.current_unit, "verification")
        self.assertEqual(len(background_calls), 1)


if __name__ == "__main__":
    unittest.main()
