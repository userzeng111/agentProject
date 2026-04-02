import datetime
import tempfile
import unittest
from pathlib import Path

if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc

from app.application.task_service import TaskService
from app.domain.models import ReviewPayload, TaskCreateRequest, TaskMode
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


if __name__ == "__main__":
    unittest.main()
