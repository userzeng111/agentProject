try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

import tempfile
import unittest
from pathlib import Path

from app.application.task_service import TaskService
from app.domain.models import ChapterDraft, StoryPlan, TaskCreateRequest, TaskMode, TaskStatus
from app.llm.model_catalog import ModelCatalogService
from app.settings.config import Settings
from app.storage.database import init_db
from app.storage.db_repository import get_novel_project, update_project_status, upsert_novel_project
from app.storage.task_store import TaskLogStore

from tests.fakes import FakeGatewayClient


class FakeEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gateway_client = FakeGatewayClient()
        self.progress_callback = None

    def set_runtime_default_model(self, model_id: str) -> None:
        self.settings.default_chat_model = model_id


class RecoveryCancelledTaskTests(unittest.TestCase):
    def _build_service(self):
        tmp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(tmp_dir.name) / "data.db")
        init_db(db_path)
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

    def _setup_task_with_completed_chapters(self, store, service):
        """创建任务并模拟完成3章后进入 READY_FOR_BATCH。"""
        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        story_plan = StoryPlan(
            working_title="苍穹变",
            logline="少年逆天改命",
            world_notes=["玄幻大陆"],
            character_notes=["主角林动"],
            chapter_plan=[
                {"number": i, "title": f"第{i}章", "goal": f"目标{i}"}
                for i in range(1, 11)
            ],
        )
        task = store.set_ready_for_batch(task.id, story_plan)
        upsert_novel_project(task, story_plan)
        # 模拟已完成3章
        update_project_status(
            task.id,
            status=TaskStatus.READY_FOR_BATCH.value,
            completed_chapter_count=3,
            next_chapter_number=4,
        )
        # 写入章节历史快照以便恢复
        for number in range(1, 4):
            chapter = ChapterDraft(
                number=number,
                title=f"第{number}章",
                summary=f"第{number}章摘要",
                content=f"第{number}章正文",
            )
            store.write_context_snapshot(
                task.id,
                stage="drafting",
                snapshot_name=f"chapter-{number:02d}-history",
                payload={
                    "messages": [
                        {"role": "assistant", "content": chapter.model_dump_json()},
                    ],
                },
            )
        return task, story_plan

    def test_cancel_task_saves_blocked_from_status(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task, _story_plan = self._setup_task_with_completed_chapters(store, service)
        # 先将任务转入 WAITING_MANUAL_ACTION（可取消状态），并清空 blocked_from_status
        task = store.set_waiting_manual_action(
            task.id,
            "模拟异常转入人工处理",
            payload={"summary": "测试", "display_level": "public", "reason": "recoverable_runtime_error"},
        )
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_MANUAL_ACTION.value,
            blocked_from_status="",
        )

        service.cancel_task(task.id, comment="用户取消测试")

        project = get_novel_project(task.id)
        self.assertIsNotNone(project)
        assert project is not None
        # cancel_task 应在 blocked_from_status 为空时保存当前 project.status
        # 当前 project.status 为 WAITING_MANUAL_ACTION，因此保存该值
        self.assertEqual(project.blocked_from_status, TaskStatus.WAITING_MANUAL_ACTION.value)
        # cancel_task 应清理 active_batch_no 和 active_continue_request_id
        self.assertIsNone(project.active_batch_no)
        self.assertEqual(project.active_continue_request_id, "")

    def test_cancel_task_clears_active_batch(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task, _story_plan = self._setup_task_with_completed_chapters(store, service)
        # 创建一个活动批次
        from app.storage.db_repository import create_batch, get_active_batch
        batch = create_batch(
            task.id,
            continue_request_id="test-req-1",
            requested_count=2,
            effective_count=2,
            actual_start_chapter=4,
        )
        update_project_status(
            task.id,
            status=TaskStatus.READY_FOR_BATCH.value,
            active_batch_no=batch.batch_no,
            active_continue_request_id="test-req-1",
        )
        # 将任务转入 WAITING_MANUAL_ACTION（可取消状态）
        task = store.set_waiting_manual_action(
            task.id,
            "模拟异常",
            payload={"summary": "测试", "display_level": "public", "reason": "recoverable_runtime_error"},
        )
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_MANUAL_ACTION.value,
            blocked_from_status=TaskStatus.READY_FOR_BATCH.value,
        )
        # 取消前应存在活动批次
        self.assertIsNotNone(get_active_batch(task.id))

        service.cancel_task(task.id)

        # 取消后活动批次应被标记为 failed
        self.assertIsNone(get_active_batch(task.id))
        project = get_novel_project(task.id)
        self.assertIsNotNone(project)
        assert project is not None
        self.assertIsNone(project.active_batch_no)
        self.assertEqual(project.active_continue_request_id, "")

    def test_cancelled_task_with_chapters_can_recover_to_ready_for_batch(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task, story_plan = self._setup_task_with_completed_chapters(store, service)
        # 直接构造已取消状态（绕过 cancel_task 的状态限制）
        task = store.set_waiting_manual_action(
            task.id,
            "模拟异常",
            payload={"summary": "测试", "display_level": "public", "reason": "recoverable_runtime_error"},
        )
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_MANUAL_ACTION.value,
            blocked_from_status=TaskStatus.READY_FOR_BATCH.value,
        )
        # 模拟取消：直接调用 store.cancel_task（此时状态是 WAITING_MANUAL_ACTION，可取消）
        store.cancel_task(task.id)

        cancelled_task = store.get(task.id)
        self.assertEqual(cancelled_task.status, TaskStatus.CANCELLED)

        preview = service._preview_recover_to_stable(cancelled_task)
        self.assertIsNotNone(preview)
        assert preview is not None
        # blocked_from_status 为 READY_FOR_BATCH 时，预览返回 waiting_chapter_generation
        # 但恢复执行后会通过 _recover_novel_project_state 回到 READY_FOR_BATCH
        self.assertEqual(preview.target_stage, "waiting_chapter_generation")

        recovered = service.recover_task(task.id, force=True)
        self.assertEqual(recovered.status, TaskStatus.READY_FOR_BATCH)
        self.assertEqual(recovered.story_plan, story_plan)

        project = get_novel_project(task.id)
        self.assertIsNotNone(project)
        assert project is not None
        self.assertEqual(project.completed_chapter_count, 3)
        self.assertEqual(project.next_chapter_number, 4)

    def test_cancelled_task_supports_restart_from_input(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="测试重新开始",
                model_id="gpt-5.4",
            )
        )
        # 先转入可取消状态再取消
        task = store.set_waiting_manual_action(
            task.id,
            "模拟异常",
            payload={"summary": "测试", "display_level": "public", "reason": "recoverable_runtime_error"},
        )
        store.cancel_task(task.id)

        cancelled_task = store.get(task.id)
        self.assertEqual(cancelled_task.status, TaskStatus.CANCELLED)

        preview = service._preview_restart_from_input(cancelled_task)
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.target_stage, TaskStatus.PLANNING.value)

    def test_cancelled_task_can_recover_outline_review_when_no_chapters(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="测试大纲恢复",
                model_id="gpt-5.4",
            )
        )
        # 构造大纲历史快照
        story_plan = StoryPlan(
            working_title="测试书",
            logline="测试大纲恢复",
            world_notes=["世界"],
            character_notes=["角色"],
            chapter_plan=[{"number": 1, "title": "第1章", "goal": "开局"}],
        )
        store.write_context_snapshot(
            task.id,
            stage="planning",
            snapshot_name="outline-revision-history",
            payload={
                "messages": [
                    {"role": "assistant", "content": story_plan.model_dump_json()},
                ],
            },
        )
        # 先转入可取消状态再取消
        task = store.set_waiting_manual_action(
            task.id,
            "模拟异常",
            payload={"summary": "测试", "display_level": "public", "reason": "recoverable_runtime_error"},
        )
        store.cancel_task(task.id)

        cancelled_task = store.get(task.id)
        self.assertEqual(cancelled_task.status, TaskStatus.CANCELLED)

        preview = service._preview_recover_to_stable(cancelled_task)
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.target_stage, TaskStatus.WAITING_OUTLINE_REVIEW.value)

        recovered = service.recover_task(task.id, force=True)
        self.assertEqual(recovered.status, TaskStatus.WAITING_OUTLINE_REVIEW)

    def test_recover_clears_stale_active_batch(self) -> None:
        """恢复已取消任务时，若数据库中残留旧版本未清理的活动批次，应自动清理。"""
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task, story_plan = self._setup_task_with_completed_chapters(store, service)
        # 创建一个活动批次（模拟旧版本 cancel_task 未清理的残留）
        from app.storage.db_repository import create_batch, get_active_batch
        batch = create_batch(
            task.id,
            continue_request_id="stale-req-1",
            requested_count=2,
            effective_count=2,
            actual_start_chapter=4,
        )
        update_project_status(
            task.id,
            status=TaskStatus.READY_FOR_BATCH.value,
            active_batch_no=batch.batch_no,
            active_continue_request_id="stale-req-1",
        )
        # 直接取消任务，但不清理批次（模拟旧版本行为）
        task = store.set_waiting_manual_action(
            task.id,
            "模拟异常",
            payload={"summary": "测试", "display_level": "public", "reason": "recoverable_runtime_error"},
        )
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_MANUAL_ACTION.value,
            blocked_from_status=TaskStatus.READY_FOR_BATCH.value,
        )
        store.cancel_task(task.id)

        # 确认取消后批次仍然存在（旧版本残留）
        self.assertIsNotNone(get_active_batch(task.id))

        # 恢复任务应自动清理残留批次
        recovered = service.recover_task(task.id, force=True)
        self.assertEqual(recovered.status, TaskStatus.READY_FOR_BATCH)

        # 清理后不应再有活动批次
        self.assertIsNone(get_active_batch(task.id))
        project = get_novel_project(task.id)
        self.assertIsNotNone(project)
        assert project is not None
        self.assertIsNone(project.active_batch_no)
        self.assertEqual(project.active_continue_request_id, "")


if __name__ == "__main__":
    unittest.main()
