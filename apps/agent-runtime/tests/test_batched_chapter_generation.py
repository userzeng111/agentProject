import tempfile
import unittest
from pathlib import Path

from app.application.task_service import TaskService
from app.domain.models import StoryPlan, TaskCreateRequest, TaskStatus
from app.settings.config import Settings
from app.storage.database import get_session
from app.storage.db_models import NovelGenerationBatchModel, NovelOutlineChapterModel
from app.storage.db_repository import get_novel_project, read_file_content_hash
from app.storage.task_store import TaskLogStore
from tests.fakes import build_verified_gateway_model_catalog


class FakeGatewayClient:
    def list_models(self):
        return [
            {"id": "gpt-5.4", "object": "model", "owned_by": "openai"},
            {"id": "glm-5.1", "object": "model", "owned_by": "zhipu"},
        ]


class FakeBatchEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gateway_client = FakeGatewayClient()
        self.generated_batches: list[dict] = []
        self.emit_progress_events = False

    def set_runtime_default_model(self, model_id: str) -> None:
        self.settings.default_chat_model = model_id

    def generate_chapter_pair(
        self,
        spec,
        story_plan,
        batch_index,
        completed_chapters,
        reference_text,
        context_packet=None,
        model=None,
        progress_callback=None,
        requested_batch_size=None,
        **_kwargs,
    ):
        remaining = len(story_plan["chapter_plan"]) - batch_index
        batch_size = min(int(requested_batch_size or 1), remaining)
        result = []
        for item in story_plan["chapter_plan"][batch_index : batch_index + batch_size]:
            if self.emit_progress_events and progress_callback is not None:
                progress_callback(
                    {
                        "event_type": "chapter.started",
                        "stage": "drafting",
                        "unit_id": f"chapter-{item['number']:02d}",
                        "message": f"正在生成第 {item['number']} 章：{item['title']}",
                        "payload": {
                            "chapter_number": item["number"],
                            "chapter_title": item["title"],
                        },
                    }
                )
                progress_callback(
                    {
                        "event_type": "model.thinking",
                        "stage": "drafting",
                        "unit_id": f"chapter-{item['number']:02d}",
                        "message": "模型思考中...",
                        "payload": {
                            "reasoning_chunk": f"思考第 {item['number']} 章",
                            "model": model or "",
                            "finish_reason": None,
                        },
                    }
                )
            result.append(
                {
                    "number": item["number"],
                    "title": item["title"],
                    "summary": f"{item['title']} 摘要",
                    "content": f"{item['title']} 正文",
                }
            )
            if self.emit_progress_events and progress_callback is not None:
                progress_callback(
                    {
                        "event_type": "chapter.saved",
                        "stage": "drafting",
                        "unit_id": f"chapter-{item['number']:02d}",
                        "message": f"第 {item['number']} 章已生成：{item['title']}",
                        "payload": {
                            "chapter_number": item["number"],
                            "chapter_title": item["title"],
                            "chapter_summary": f"{item['title']} 摘要",
                        },
                    }
                )
        self.generated_batches.append(
            {
                "batch_index": batch_index,
                "requested_batch_size": requested_batch_size,
                "model": model,
                "generated_numbers": [item["number"] for item in result],
            }
        )
        return result


class BatchedChapterGenerationTests(unittest.TestCase):
    def _build_service(self):
        tmp_dir = tempfile.TemporaryDirectory()
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="",
            tasklog_root=str(Path(tmp_dir.name) / "tasklog"),
        )
        store = TaskLogStore(root_dir=str(Path(tmp_dir.name) / "tasklog"))
        engine = FakeBatchEngine(settings)
        model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
        service = TaskService(store=store, engine=engine, model_catalog=model_catalog)
        return tmp_dir, store, service, engine

    def _seed_ready_task(self, store: TaskLogStore, service: TaskService, *, planned_chapter_count: int = 3):
        task = service.create_task(
            TaskCreateRequest(
                prompt="写一个长篇都市医生修罗场故事",
                creative_mode="original",
                novel_size="long",
                target_chapter_count=planned_chapter_count,
                model_id="gpt-5.4",
            )
        )
        task = store.get(task.id)
        task.normalized_spec = {
            "mode": "long_story",
            "creative_mode": "original",
            "novel_size": "long",
            "prompt": "写一个长篇都市医生修罗场故事",
            "genre": "都市",
            "style": "",
            "chapter_word_min": 2200,
            "chapter_word_max": 2860,
            "model_id": "gpt-5.4",
        }
        story_plan = StoryPlan(
            working_title="白衣修罗场",
            logline="年轻医生在都市权贵与情感纠葛中崛起。",
            world_notes=["现代都市医院体系"],
            character_notes=["男主是年轻医生"],
            planned_chapter_count=planned_chapter_count,
            chapter_plan=[
                {"number": number, "title": f"第{number}章", "goal": f"剧情推进{number}"}
                for number in range(1, planned_chapter_count + 1)
            ],
        )
        store.save(task)
        ready = store.set_ready_for_batch(task.id, story_plan)
        return ready

    def test_continue_task_generates_requested_batch_and_waits_for_review(self) -> None:
        tmp_dir, store, service, engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        self.assertTrue(hasattr(service, "continue_task"))
        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        snapshot = continue_task(
            task.id,
            {"requested_chapter_count": 2, "continue_request_id": "req-1"},
        )

        self.assertEqual(snapshot.status, TaskStatus.WAITING_CHAPTER_REVIEW)
        self.assertEqual(len(snapshot.pending_review.chapter_pair or []), 2)
        self.assertEqual(engine.generated_batches[-1]["generated_numbers"], [1, 2])
        chapter_md = Path(tmp_dir.name) / "tasklog" / "runs" / task.id / "chapters" / "01.md"
        self.assertTrue(chapter_md.exists())

    def test_queue_continue_task_returns_before_chapter_generation_runs(self) -> None:
        tmp_dir, store, service, engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)
        background_calls = []
        service._start_background = lambda *args, **kwargs: background_calls.append((args, kwargs))

        snapshot = service.queue_continue_task(
            task.id,
            {"requested_chapter_count": 2, "continue_request_id": "req-queued"},
        )

        self.assertEqual(snapshot.status, TaskStatus.READY_FOR_BATCH)
        self.assertEqual(len(background_calls), 1)
        self.assertEqual(engine.generated_batches, [])
        self.assertIn(task.id, service._active_runs)

    def test_continue_task_reuses_same_continue_request_id(self) -> None:
        tmp_dir, store, service, engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        first = continue_task(task.id, {"requested_chapter_count": 2, "continue_request_id": "req-1"})
        second = continue_task(task.id, {"requested_chapter_count": 2, "continue_request_id": "req-1"})

        self.assertEqual(first.status, TaskStatus.WAITING_CHAPTER_REVIEW)
        self.assertEqual(second.status, TaskStatus.WAITING_CHAPTER_REVIEW)
        self.assertEqual(len(engine.generated_batches), 1)

    def test_continue_task_uses_remaining_chapter_count_for_last_batch(self) -> None:
        tmp_dir, store, service, engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        continue_task(task.id, {"requested_chapter_count": 2, "continue_request_id": "req-1"})
        service.resume_task(task.id, approved=True, comment="通过")
        last = continue_task(task.id, {"requested_chapter_count": 3, "continue_request_id": "req-2"})

        self.assertEqual(last.status, TaskStatus.WAITING_CHAPTER_REVIEW)
        self.assertEqual(engine.generated_batches[-1]["generated_numbers"], [3])

    def test_chapter_review_approve_returns_ready_for_batch(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        continue_task(task.id, {"requested_chapter_count": 2, "continue_request_id": "req-1"})
        approved = service.resume_task(task.id, approved=True, comment="通过")

        self.assertEqual(approved.status.value, "ready_for_batch")
        self.assertEqual(approved.current_stage, "ready_for_batch")

    def test_chapter_review_approve_advances_past_restored_drafted_chapters(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=8)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        continue_task(task.id, {"requested_chapter_count": 3, "continue_request_id": "req-1"})
        service.resume_task(task.id, approved=True, comment="通过")

        with get_session() as session:
            for chapter_number in (1, 2, 3):
                chapter = session.query(NovelOutlineChapterModel).filter_by(
                    task_id=task.id,
                    chapter_number=chapter_number,
                ).first()
                self.assertIsNotNone(chapter)
                chapter.status = "drafted"
                chapter.artifact_state = "present"
            session.commit()

        continue_task(task.id, {"requested_chapter_count": 3, "continue_request_id": "req-2"})
        approved = service.resume_task(task.id, approved=True, comment="通过")

        self.assertEqual(approved.status, TaskStatus.READY_FOR_BATCH)
        project = get_novel_project(task.id)
        self.assertIsNotNone(project)
        assert project is not None
        self.assertEqual(project.completed_chapter_count, 6)
        self.assertEqual(project.next_chapter_number, 7)

    def test_continue_task_emits_progress_and_thinking_events_for_later_batch(self) -> None:
        tmp_dir, store, service, engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        engine.emit_progress_events = True
        task = self._seed_ready_task(store, service, planned_chapter_count=8)
        event_queue = store.subscribe(task.id)
        self.addCleanup(store.unsubscribe, task.id, event_queue)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        continue_task(task.id, {"requested_chapter_count": 3, "continue_request_id": "req-1"})
        service.resume_task(task.id, approved=True, comment="通过")
        while not event_queue.empty():
            event_queue.get_nowait()
        before_event_count = len(store.get(task.id).events)
        continue_task(task.id, {"requested_chapter_count": 3, "continue_request_id": "req-2"})

        events = store.get(task.id).events[before_event_count:]
        chapter_started = {
            event.payload.get("chapter_number")
            for event in events
            if event.event_type == "chapter.started"
        }
        persisted_thinking_units = [
            event.unit_id
            for event in events
            if event.event_type == "model.thinking"
        ]
        broadcast_thinking_units = []
        while not event_queue.empty():
            event = event_queue.get_nowait()
            if event.get("event_type") == "model.thinking":
                broadcast_thinking_units.append(event.get("unit_id"))

        self.assertEqual(chapter_started, {4, 5, 6})
        self.assertEqual(persisted_thinking_units, [])
        self.assertEqual(set(broadcast_thinking_units), {"chapter-04", "chapter-05", "chapter-06"})

    def test_model_thinking_progress_callback_only_broadcasts_without_persistence(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)
        event_queue = store.subscribe(task.id)
        self.addCleanup(store.unsubscribe, task.id, event_queue)

        original_mark_stage = store.mark_stage
        original_save = store.save
        original_sync_supervisor_plan = service._sync_supervisor_plan
        calls = {"mark_stage": 0, "save": 0, "sync": 0}

        def counted_mark_stage(*args, **kwargs):
            calls["mark_stage"] += 1
            return original_mark_stage(*args, **kwargs)

        def counted_save(*args, **kwargs):
            calls["save"] += 1
            return original_save(*args, **kwargs)

        def counted_sync_supervisor_plan(*args, **kwargs):
            calls["sync"] += 1
            return original_sync_supervisor_plan(*args, **kwargs)

        store.mark_stage = counted_mark_stage
        store.save = counted_save
        service._sync_supervisor_plan = counted_sync_supervisor_plan
        before_event_count = len(store.get(task.id).events)

        service._build_progress_callback(task.id)(
            {
                "event_type": "model.thinking",
                "stage": "drafting",
                "unit_id": "chapter-01",
                "message": "模型思考中...",
                "payload": {
                    "reasoning_chunk": "这段思考不能写入 task.json",
                    "model": "gpt-5.4",
                    "finish_reason": None,
                },
            }
        )

        self.assertEqual(calls, {"mark_stage": 0, "save": 0, "sync": 0})
        self.assertEqual(len(store.get(task.id).events), before_event_count)
        broadcast_event = event_queue.get_nowait()
        self.assertEqual(broadcast_event["event_type"], "model.thinking")
        self.assertEqual(broadcast_event["unit_id"], "chapter-01")
        self.assertEqual(broadcast_event["payload"]["reasoning_chunk"], "这段思考不能写入 task.json")

    def test_chapter_started_progress_callback_keeps_persistent_stage_path(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        original_mark_stage = store.mark_stage
        original_sync_supervisor_plan = service._sync_supervisor_plan
        calls = {"mark_stage": 0, "sync": 0}

        def counted_mark_stage(*args, **kwargs):
            calls["mark_stage"] += 1
            return original_mark_stage(*args, **kwargs)

        def counted_sync_supervisor_plan(*args, **kwargs):
            calls["sync"] += 1
            return original_sync_supervisor_plan(*args, **kwargs)

        store.mark_stage = counted_mark_stage
        service._sync_supervisor_plan = counted_sync_supervisor_plan
        before_event_count = len(store.get(task.id).events)

        service._build_progress_callback(task.id)(
            {
                "event_type": "chapter.started",
                "stage": "drafting",
                "unit_id": "chapter-01",
                "message": "正在生成第 1 章",
                "payload": {"chapter_number": 1, "chapter_title": "第1章"},
            }
        )

        events = store.get(task.id).events[before_event_count:]
        self.assertEqual(calls, {"mark_stage": 1, "sync": 1})
        self.assertIn("chapter.started", [event.event_type for event in events])

    def test_recover_task_marks_waiting_manual_action_on_checksum_mismatch(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        continue_task(task.id, {"requested_chapter_count": 2, "continue_request_id": "req-1"})
        with get_session() as session:
            chapter = session.query(NovelOutlineChapterModel).filter_by(task_id=task.id, chapter_number=1).first()
            self.assertIsNotNone(chapter)
            chapter.content_hash = "broken-hash"
            session.commit()

        recovered = service.recover_task(task.id, force=True)

        self.assertEqual(recovered.status, TaskStatus.WAITING_MANUAL_ACTION)

    def test_recover_task_marks_waiting_manual_action_on_batch_consistency_mismatch(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        continue_task(task.id, {"requested_chapter_count": 2, "continue_request_id": "req-1"})
        with get_session() as session:
            batch = session.query(NovelGenerationBatchModel).filter_by(task_id=task.id, batch_no=1).first()
            self.assertIsNotNone(batch)
            batch.expected_end_chapter = 99
            session.commit()

        recovered = service.recover_task(task.id, force=True)

        self.assertEqual(recovered.status, TaskStatus.WAITING_MANUAL_ACTION)

    def test_recover_task_backfills_outline_metadata_from_existing_file(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        continue_task(task.id, {"requested_chapter_count": 2, "continue_request_id": "req-1"})
        with get_session() as session:
            chapter = session.query(NovelOutlineChapterModel).filter_by(task_id=task.id, chapter_number=1).first()
            self.assertIsNotNone(chapter)
            chapter.md_ref = ""
            chapter.json_ref = ""
            chapter.content_hash = ""
            chapter.file_size = 0
            chapter.artifact_state = "pending"
            session.commit()

        recovered = service.recover_task(task.id, force=True)
        with get_session() as session:
            chapter = session.query(NovelOutlineChapterModel).filter_by(task_id=task.id, chapter_number=1).first()
            self.assertIsNotNone(chapter)
            self.assertTrue(chapter.md_ref)
            self.assertTrue(str(chapter.md_ref).endswith(".md"))
            self.assertTrue(str(chapter.json_ref).endswith(".json"))
            self.assertEqual(chapter.artifact_state, "present")
        self.assertEqual(recovered.status, TaskStatus.WAITING_CHAPTER_REVIEW)

    def test_recover_task_restores_waiting_chapter_review_after_manual_fix(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        continue_task(task.id, {"requested_chapter_count": 2, "continue_request_id": "req-1"})
        with get_session() as session:
            chapter = session.query(NovelOutlineChapterModel).filter_by(task_id=task.id, chapter_number=1).first()
            self.assertIsNotNone(chapter)
            chapter.content_hash = "broken-hash"
            session.commit()

        blocked = service.recover_task(task.id, force=True)
        self.assertEqual(blocked.status, TaskStatus.WAITING_MANUAL_ACTION)

        chapter_path = Path(tmp_dir.name) / "tasklog" / "runs" / task.id / "chapters" / "01.json"
        correct_hash, correct_size = read_file_content_hash(chapter_path)
        with get_session() as session:
            chapter = session.query(NovelOutlineChapterModel).filter_by(task_id=task.id, chapter_number=1).first()
            self.assertIsNotNone(chapter)
            chapter.content_hash = correct_hash
            chapter.file_size = correct_size
            chapter.artifact_state = "present"
            session.commit()

        recovered = service.recover_task(task.id, force=True)
        self.assertEqual(recovered.status, TaskStatus.WAITING_CHAPTER_REVIEW)

    def test_continue_task_persists_md_ref_for_outline_chapter(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        continue_task = getattr(service, "continue_task", None)
        self.assertIsNotNone(continue_task)
        continue_task(task.id, {"requested_chapter_count": 2, "continue_request_id": "req-1"})

        with get_session() as session:
            chapter = session.query(NovelOutlineChapterModel).filter_by(task_id=task.id, chapter_number=1).first()
            self.assertIsNotNone(chapter)
            self.assertTrue(str(chapter.md_ref).endswith(".md"))
            self.assertTrue(str(chapter.json_ref).endswith(".json"))

    def test_continue_task_failure_moves_task_to_waiting_manual_action_and_can_recover(self) -> None:
        tmp_dir, store, service, _engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        def raise_gateway_error(**_kwargs):
            raise RuntimeError("模型网关暂时不可用")

        service.engine.generate_chapter_pair = raise_gateway_error

        snapshot = service.continue_task(
            task.id,
            {"requested_chapter_count": 2, "continue_request_id": "req-1", "model_id": "glm-5.1"},
        )

        self.assertEqual(snapshot.status, TaskStatus.WAITING_MANUAL_ACTION)
        self.assertEqual(snapshot.current_stage, "waiting_manual_action")
        self.assertEqual(snapshot.model_id, "gpt-5.4")
        self.assertIn("继续创作失败", snapshot.error_message or "")

        recovered = service.recover_task(task.id, force=True)

        self.assertEqual(recovered.status, TaskStatus.READY_FOR_BATCH)
        self.assertEqual(recovered.current_stage, "ready_for_batch")

    def test_continue_task_action_model_override_does_not_persist_task_default_model(self) -> None:
        tmp_dir, store, service, engine = self._build_service()
        self.addCleanup(tmp_dir.cleanup)
        task = self._seed_ready_task(store, service, planned_chapter_count=3)

        snapshot = service.continue_task(
            task.id,
            {"requested_chapter_count": 2, "continue_request_id": "req-model", "model_id": "glm-5.1"},
        )

        self.assertEqual(snapshot.status, TaskStatus.WAITING_CHAPTER_REVIEW)
        self.assertEqual(engine.generated_batches[-1]["model"], "glm-5.1")
        self.assertEqual(store.get(task.id).model_id, "gpt-5.4")


if __name__ == "__main__":
    unittest.main()
