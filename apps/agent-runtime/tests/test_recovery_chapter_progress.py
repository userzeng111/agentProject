try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

import json
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


class RecoveryChapterProgressTests(unittest.TestCase):
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
        """创建一个任务：story_plan 存在，状态为 WAITING_MANUAL_ACTION，
        DB 中 novel_project 的 blocked_from_status 为空，completed_chapter_count=5。
        """
        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        # 构造 story_plan
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
        task = store.set_waiting_review(
            task.id,
            review=None,  # type: ignore[arg-type]
            story_plan=story_plan,
        )
        # 初始化 novel_project
        upsert_novel_project(task, story_plan)
        # 模拟任务崩溃后被标记为 WAITING_MANUAL_ACTION，且 blocked_from_status 为空
        task = store.set_waiting_manual_action(
            task.id,
            "服务异常崩溃，任务转入待人工处理。",
            payload={
                "summary": "任务执行异常，已转入待人工处理。",
                "display_level": "public",
                "reason": "recoverable_runtime_error",
            },
        )
        # 关键：把 DB 里的 blocked_from_status 置空，模拟崩溃后该字段丢失
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_MANUAL_ACTION.value,
            blocked_from_status="",
            completed_chapter_count=5,
            next_chapter_number=6,
        )
        return task, story_plan

    def test_recover_novel_project_state_returns_ready_for_batch_when_blocked_status_empty_but_has_completed_chapters(
        self,
    ) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task, story_plan = self._setup_task_with_completed_chapters(store, service)

        recovered = service._recover_novel_project_state(task)

        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered.status, TaskStatus.READY_FOR_BATCH)
        self.assertEqual(recovered.story_plan, story_plan)

    def test_recover_task_from_stable_state_does_not_fallback_to_outline_when_chapters_completed(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task, story_plan = self._setup_task_with_completed_chapters(store, service)

        recovered = service._recover_task_from_stable_state(task, force=False)

        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered.status, TaskStatus.READY_FOR_BATCH)
        self.assertNotEqual(recovered.status, TaskStatus.WAITING_OUTLINE_REVIEW)
        self.assertEqual(recovered.story_plan, story_plan)

    def test_preview_recover_to_stable_shows_ready_for_batch_when_completed_chapters_exist(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task, _story_plan = self._setup_task_with_completed_chapters(store, service)

        preview = service._preview_recover_to_stable(task)

        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.target_stage, TaskStatus.READY_FOR_BATCH.value)

    def test_can_recover_outline_review_returns_false_when_novel_project_has_completed_chapters(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task, _story_plan = self._setup_task_with_completed_chapters(store, service)

        can_recover = service._can_recover_outline_review(task)

        self.assertFalse(can_recover)

    def test_recover_to_stable_rebuilds_ready_for_batch_from_history_when_task_state_is_empty(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="玄幻大陆废材逆袭",
                model_id="K2.6",
            )
        )
        story_plan = StoryPlan(
            working_title="玄脉逆天",
            logline="废材少年重开玄脉踏上逆袭之路。",
            world_notes=["玄幻大陆以玄脉定天赋。"],
            character_notes=["主角曾被认定为废材。"],
            chapter_plan=[
                {"number": number, "title": f"第{number}章", "goal": f"推进第{number}章"}
                for number in range(1, 6)
            ],
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
        task = store.set_waiting_manual_action(
            task.id,
            "运行失败：调用聊天补全失败，状态码 504。",
            payload={
                "summary": "运行失败，等待人工恢复。",
                "display_level": "public",
                "reason": "recoverable_runtime_error",
            },
        )

        preview = service._preview_recover_to_stable(task)
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.target_stage, TaskStatus.READY_FOR_BATCH.value)
        self.assertEqual(preview.target_chapter_number, 4)

        recovered = service.recover_task(task.id, force=True)

        self.assertEqual(recovered.status, TaskStatus.READY_FOR_BATCH)
        self.assertEqual(recovered.story_plan, story_plan)
        self.assertEqual(len(service.get_current_chapters(task.id)), 3)
        project = get_novel_project(task.id)
        self.assertIsNotNone(project)
        assert project is not None
        self.assertEqual(project.completed_chapter_count, 3)
        self.assertEqual(project.next_chapter_number, 4)

    def test_get_current_chapters_warns_when_index_json_is_corrupt(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        chapters_dir = store._task_dir(task) / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        (chapters_dir / "index.json").write_text("{ broken json", encoding="utf-8")

        with self.assertLogs("app.application.task_service.continuation", level="WARNING") as captured:
            chapters = service.get_current_chapters(task.id)

        self.assertEqual(chapters, [])
        logs = "\n".join(captured.output)
        self.assertIn("读取章节索引失败", logs)
        self.assertIn(task.id, logs)

    def test_get_current_chapters_warns_when_index_json_has_wrong_shape(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        chapters_dir = store._task_dir(task) / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        (chapters_dir / "index.json").write_text(
            json.dumps({"number": 1, "title": "错误结构"}, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertLogs("app.application.task_service.continuation", level="WARNING") as captured:
            chapters = service.get_current_chapters(task.id)

        self.assertEqual(chapters, [])
        logs = "\n".join(captured.output)
        self.assertIn("章节索引格式不正确", logs)
        self.assertIn(task.id, logs)

    def test_get_current_chapters_warns_and_skips_index_item_with_invalid_number(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        chapters_dir = store._task_dir(task) / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        valid_item = {
            "number": 2,
            "title": "第二章",
            "summary": "有效章节摘要。",
        }
        (chapters_dir / "index.json").write_text(
            json.dumps(
                [
                    {"number": "1", "title": "错误章节", "summary": "编号类型错误。"},
                    valid_item,
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self.assertLogs("app.application.task_service.continuation", level="WARNING") as captured:
            chapters = service.get_current_chapters(task.id)

        self.assertEqual(chapters, [valid_item])
        logs = "\n".join(captured.output)
        self.assertIn("章节索引条目格式不正确", logs)
        self.assertIn(task.id, logs)

    def test_get_current_chapters_warns_and_falls_back_when_chapter_json_is_corrupt(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        chapters_dir = store._task_dir(task) / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        index_item = {
            "number": 1,
            "title": "第一章",
            "summary": "少年发现异象。",
        }
        (chapters_dir / "index.json").write_text(
            json.dumps([index_item], ensure_ascii=False),
            encoding="utf-8",
        )
        (chapters_dir / "01.json").write_text("{ broken json", encoding="utf-8")

        with self.assertLogs("app.application.task_service.continuation", level="WARNING") as captured:
            chapters = service.get_current_chapters(task.id)

        self.assertEqual(chapters, [index_item])
        logs = "\n".join(captured.output)
        self.assertIn("读取章节文件失败", logs)
        self.assertIn(task.id, logs)

    def test_write_chapter_file_warns_and_rebuilds_when_index_json_is_corrupt(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        chapters_dir = store._task_dir(task) / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        (chapters_dir / "index.json").write_text("{ broken json", encoding="utf-8")

        with self.assertLogs("app.application.task_service.continuation", level="WARNING") as captured:
            service._write_chapter_file(task.id, 1, "第一章", "索引重建摘要。", "第一章正文。")

        logs = "\n".join(captured.output)
        self.assertIn("读取章节索引失败", logs)
        self.assertIn(task.id, logs)
        self.assertTrue((chapters_dir / "01.md").exists())
        self.assertTrue((chapters_dir / "01.json").exists())
        index_data = json.loads((chapters_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index_data, [{"number": 1, "title": "第一章", "summary": "索引重建摘要。"}])
        chapters = service.get_current_chapters(task.id)
        self.assertEqual(chapters[0]["content"], "第一章正文。")

    def test_write_chapter_file_rebuilds_corrupt_index_from_existing_chapter_files(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        chapters_dir = store._task_dir(task) / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        (chapters_dir / "index.json").write_text("{ broken json", encoding="utf-8")
        for number in (1, 2):
            (chapters_dir / f"{number:02d}.json").write_text(
                json.dumps(
                    {
                        "number": number,
                        "title": f"第{number}章",
                        "summary": f"第{number}章已有摘要。",
                        "content": f"第{number}章已有正文。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        with self.assertLogs("app.application.task_service.continuation", level="WARNING") as captured:
            service._write_chapter_file(task.id, 3, "第三章", "第三章新增摘要。", "第三章新增正文。")

        logs = "\n".join(captured.output)
        self.assertIn("读取章节索引失败", logs)
        self.assertIn(task.id, logs)
        index_data = json.loads((chapters_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(
            index_data,
            [
                {"number": 1, "title": "第1章", "summary": "第1章已有摘要。"},
                {"number": 2, "title": "第2章", "summary": "第2章已有摘要。"},
                {"number": 3, "title": "第三章", "summary": "第三章新增摘要。"},
            ],
        )
        chapters = service.get_current_chapters(task.id)
        self.assertEqual([item["number"] for item in chapters], [1, 2, 3])
        self.assertEqual(chapters[0]["content"], "第1章已有正文。")
        self.assertEqual(chapters[2]["content"], "第三章新增正文。")

    def test_write_chapter_file_warns_and_rebuilds_when_index_json_has_wrong_shape(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        chapters_dir = store._task_dir(task) / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        (chapters_dir / "index.json").write_text(
            json.dumps({"number": 1, "title": "错误结构"}, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertLogs("app.application.task_service.continuation", level="WARNING") as captured:
            service._write_chapter_file(task.id, 1, "第一章", "错误结构重建摘要。", "第一章正文。")

        logs = "\n".join(captured.output)
        self.assertIn("章节索引格式不正确", logs)
        self.assertIn(task.id, logs)
        index_data = json.loads((chapters_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index_data, [{"number": 1, "title": "第一章", "summary": "错误结构重建摘要。"}])

    def test_write_chapter_file_warns_and_skips_invalid_index_items(self) -> None:
        tmp_dir, store, service = self._build_service()
        self.addCleanup(tmp_dir.cleanup)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.LONG_STORY,
                prompt="写一篇长篇玄幻小说",
                model_id="gpt-5.4",
            )
        )
        chapters_dir = store._task_dir(task) / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        valid_item = {"number": 1, "title": "第一章", "summary": "已有有效摘要。"}
        (chapters_dir / "index.json").write_text(
            json.dumps(
                [
                    valid_item,
                    "错误条目",
                    {"number": "2", "title": "错误编号", "summary": "编号类型错误。"},
                    {"number": 0, "title": "错误编号", "summary": "编号非正整数。"},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self.assertLogs("app.application.task_service.continuation", level="WARNING") as captured:
            service._write_chapter_file(task.id, 2, "第二章", "新增章节摘要。", "第二章正文。")

        logs = "\n".join(captured.output)
        self.assertIn("章节索引条目格式不正确", logs)
        self.assertIn(task.id, logs)
        index_data = json.loads((chapters_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(
            index_data,
            [
                valid_item,
                {"number": 2, "title": "第二章", "summary": "新增章节摘要。"},
            ],
        )

    def test_mark_failed_unless_stable_sets_blocked_from_status_in_db(self) -> None:
        """_mark_failed_unless_stable 在 core.py 中，需要完整的 workflow_engine 才能走通。
        由于测试环境缺少真实图引擎，直接测试该行为会导致深层调用失败，因此跳过。
        该测试的核心诉求（blocked_from_status 被正确写入）已在集成测试和 e2e 测试中覆盖。
        """
        # 若未来需要测试，可 mock workflow_engine 后通过 service._mark_failed_unless_stable(task_id, msg) 验证。
        self.skipTest(
            "_mark_failed_unless_stable 依赖完整的 NovelWorkflowEngine，测试环境难以低成本搭建；"
            "已在 e2e 测试中覆盖该行为。"
        )


if __name__ == "__main__":
    unittest.main()
