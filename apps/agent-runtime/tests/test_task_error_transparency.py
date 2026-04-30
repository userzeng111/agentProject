import tempfile
import unittest
from pathlib import Path

from app.application.task_service import TaskService
from app.domain.models import (
    CreativeMode,
    NovelSize,
    TaskCreateRequest,
    TaskStatus,
)
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore


class FakeGatewayClient:
    def list_models(self):
        return [{"id": "test-model", "object": "model", "owned_by": "test"}]

    def complete_json(self, messages, model=None, **kwargs):
        return {"result": "fake"}


class FakeEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gateway_client = FakeGatewayClient()
        self.progress_callback = None

    def set_runtime_default_model(self, model_id: str) -> None:
        self.settings.default_chat_model = model_id


class TaskErrorTransparencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tasklog_root = Path(self.tmp_dir.name) / "tasklog"

        settings = Settings(
            _env_file=None,
            tasklog_root=str(self.tasklog_root),
            default_chat_model="test-model",
        )
        store = TaskLogStore(str(self.tasklog_root))
        engine = FakeEngine(settings)
        self.service = TaskService(store=store, engine=engine, auto_review=False)

    def test_mark_failed_unless_stable_records_event_when_stable(self):
        """任务处于稳定状态时，_mark_failed_unless_stable 应写入 task.error_recorded 事件。"""
        request = TaskCreateRequest(
            prompt="测试错误透传",
            genre="科幻",
            style="细腻",
            creative_mode=CreativeMode.ORIGINAL,
            novel_size=NovelSize.SHORT,
            target_chapter_count=3,
            target_words=3000,
        )
        task = self.service.create_task(request)
        # 模拟任务进入稳定状态
        self.service.store.set_waiting_manual_action(
            task.id,
            "模拟已有稳定状态",
            payload={"summary": "测试", "display_level": "public"},
        )

        # 再次调用 _mark_failed_unless_stable，应写入事件但不覆盖状态
        record = self.service._mark_failed_unless_stable(
            task.id, "真实异常：上游 API 返回空响应"
        )

        self.assertEqual(record.status, TaskStatus.WAITING_MANUAL_ACTION)
        # 查找 task.error_recorded 事件
        error_events = [e for e in record.events if e.event_type == "task.error_recorded"]
        self.assertEqual(len(error_events), 1)
        self.assertIn("上游 API 返回空响应", error_events[0].message)
        self.assertEqual(error_events[0].payload.get("detail"), "真实异常：上游 API 返回空响应")

    def test_to_summary_includes_last_error_detail(self):
        """_to_summary 应提取 task.error_recorded 事件中的 detail 作为 last_error_detail。"""
        request = TaskCreateRequest(
            prompt="测试 last_error_detail",
            genre="科幻",
            style="细腻",
            creative_mode=CreativeMode.ORIGINAL,
            novel_size=NovelSize.SHORT,
            target_chapter_count=3,
            target_words=3000,
        )
        task = self.service.create_task(request)
        self.service.store.append_event(
            task.id,
            stage="drafting",
            message="后台异常（未覆盖状态）：JSON解析失败",
            event_type="task.error_recorded",
            payload={"detail": "JSON解析失败：Expecting value", "status_at_error": "waiting_manual_action"},
        )

        summary = self.service._to_summary(task)
        self.assertEqual(summary.last_error_detail, "JSON解析失败：Expecting value")

    def test_to_summary_falls_back_to_error_message(self):
        """没有 task.error_recorded 时，last_error_detail 应回退到 task.error_message。"""
        request = TaskCreateRequest(
            prompt="测试回退",
            genre="科幻",
            style="细腻",
            creative_mode=CreativeMode.ORIGINAL,
            novel_size=NovelSize.SHORT,
            target_chapter_count=3,
            target_words=3000,
        )
        task = self.service.create_task(request)
        self.service.store.set_failed(task.id, "旧错误消息")

        summary = self.service._to_summary(task)
        self.assertEqual(summary.last_error_detail, "旧错误消息")
