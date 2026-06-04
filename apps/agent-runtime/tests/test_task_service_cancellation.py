import tempfile
import unittest
from pathlib import Path

from app.application.task_service import TaskService
from app.domain.models import TaskCreateRequest, TaskMode, TaskStatus
from app.llm.model_catalog import ModelCatalogService
from app.settings.config import Settings
from app.storage.database import get_session
from app.storage.db_models import (
    NovelChapterPlanBatchModel,
    NovelGenerationBatchModel,
    NovelOutlineChapterModel,
    NovelProjectModel,
)
from app.storage.task_store import TaskLogStore


class FakeGatewayClient:
    def list_models(self):
        return [{"id": "gpt-5.4", "object": "model", "owned_by": "openai"}]


class FakeEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gateway_client = FakeGatewayClient()

    def set_runtime_default_model(self, model_id: str) -> None:
        self.settings.default_chat_model = model_id


class AliveThread:
    def is_alive(self) -> bool:
        return True

    def join(self, timeout=None) -> None:
        return None


class BlockingThread:
    join_called = False

    def is_alive(self) -> bool:
        return True

    def join(self, timeout=None) -> None:
        self.join_called = True
        raise AssertionError("取消接口不应等待仍在运行的后台线程")


class TaskServiceCancellationTests(unittest.TestCase):
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

    def test_cancelled_task_ignores_late_progress_callback(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一个取消后不应继续写入的任务",
                model_id="gpt-5.4",
            )
        )
        store.mark_stage(
            task.id,
            status=TaskStatus.PLANNING,
            stage="planning",
            message="后台执行中",
            event_type="task.queued",
        )

        service.cancel_task(task.id)
        service._build_progress_callback(task.id)(
            {
                "stage": "drafting",
                "event_type": "chapter.started",
                "message": "迟到的章节进度",
                "payload": {"chapter_number": 1},
            }
        )

        self.assertEqual(store.get(task.id).status, TaskStatus.CANCELLED)

    def test_delete_rejects_task_while_cancelled_thread_is_still_alive(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一个取消中不能删除的任务",
                model_id="gpt-5.4",
            )
        )
        store.mark_stage(
            task.id,
            status=TaskStatus.PLANNING,
            stage="planning",
            message="后台执行中",
            event_type="task.queued",
        )
        with service._run_lock:
            service._active_runs.add(task.id)
            service._active_threads[task.id] = AliveThread()

        service.cancel_task(task.id)

        with self.assertRaisesRegex(ValueError, "正在取消|正在运行"):
            service.delete_task(task.id)

    def test_cancel_task_does_not_wait_for_alive_thread_to_finish(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一个取消时必须快速返回的任务",
                model_id="gpt-5.4",
            )
        )
        store.mark_stage(
            task.id,
            status=TaskStatus.PLANNING,
            stage="planning",
            message="后台执行中",
            event_type="task.queued",
        )
        thread = BlockingThread()
        with service._run_lock:
            service._active_runs.add(task.id)
            service._active_threads[task.id] = thread

        cancelled = service.cancel_task(task.id)

        self.assertEqual(cancelled.status, TaskStatus.CANCELLED)
        self.assertIn(task.id, service._stop_requested)
        self.assertFalse(thread.join_called)

    def test_workflow_callback_returns_cancelled_before_starting_expensive_node(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一个取消后不应继续调用模型的任务",
                model_id="gpt-5.4",
            )
        )

        with service._run_lock:
            service._stop_requested.add(task.id)

        result = service.workflow_engine.callbacks.plan_story(
            {
                "task_id": task.id,
                "normalized_spec": {"model_id": "gpt-5.4"},
                "reference_text": "",
            }
        )

        self.assertEqual(result, {"cancelled": True})

    def test_delete_task_removes_all_database_associations(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一个删除时需要清理数据库关联的任务",
                model_id="gpt-5.4",
            )
        )

        with get_session() as session:
            session.add(
                NovelProjectModel(
                    task_id=task.id,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
            )
            session.add(
                NovelGenerationBatchModel(
                    task_id=task.id,
                    batch_no=1,
                    continue_request_id="continue-1",
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
            )
            session.add(
                NovelChapterPlanBatchModel(
                    task_id=task.id,
                    batch_no=1,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
            )
            session.add(
                NovelOutlineChapterModel(
                    task_id=task.id,
                    chapter_number=1,
                    updated_at=task.updated_at,
                )
            )
            session.commit()

        service.delete_task(task.id)

        with get_session() as session:
            self.assertEqual(session.query(NovelProjectModel).filter_by(task_id=task.id).count(), 0)
            self.assertEqual(session.query(NovelGenerationBatchModel).filter_by(task_id=task.id).count(), 0)
            self.assertEqual(session.query(NovelChapterPlanBatchModel).filter_by(task_id=task.id).count(), 0)
            self.assertEqual(session.query(NovelOutlineChapterModel).filter_by(task_id=task.id).count(), 0)


if __name__ == "__main__":
    unittest.main()
