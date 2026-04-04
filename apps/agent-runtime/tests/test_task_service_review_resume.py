import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc

from app.application.task_service import TaskService
from app.domain.models import ReviewPayload, StoryPlan, TaskCreateRequest, TaskMode
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
            "target_words": 1600,
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


if __name__ == "__main__":
    unittest.main()
