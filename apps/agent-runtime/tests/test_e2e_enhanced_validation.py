"""增强端到端验证：测试修复后的可见性、日志、错误透传。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.application.task_service import TaskService
from app.domain.models import (
    AutoReviewPolicy,
    ReviewDecision,
    ReviewPayload,
    TaskCreateRequest,
    TaskMode,
    TaskStatus,
)
from app.llm.auto_reviewer import AutoReviewManager
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore

from tests.fakes import FakeGatewayClient, FakeStoryEngine


class E2EFakeEngine(FakeStoryEngine):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="gpt-5.4",
            tasklog_root="/tmp",
        )
        self.gateway_client = FakeGatewayClient()
        self.gateway_client.list_models = lambda: [
            {"id": "gpt-5.4", "object": "model", "owned_by": "openai"},
        ]

    def set_runtime_default_model(self, model_id: str) -> None:
        self.settings.default_chat_model = model_id


class TestE2EEnhancedValidation(unittest.TestCase):
    def _make_service(self, tmp_dir: str, engine: E2EFakeEngine, auto_review: bool = True) -> TaskService:
        store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
        return TaskService(
            store=store,
            engine=engine,
            auto_review=auto_review,
            auto_review_policy={
                "auditor_model": "auditor-x",
                "synthesis_model": "synthesis-y",
                "outline_pass_threshold": 60.0,
                "outline_auto_escalate_on_critical": False,
                "outline_max_auto_revisions": 3,
                "chapter_pass_threshold": 65.0,
                "chapter_auto_escalate_on_critical": False,
                "chapter_max_auto_revisions": 3,
            },
        )

    def test_auto_review_full_flow_reaches_completed(self) -> None:
        """开启自动审核的短篇故事应走到 COMPLETED，且工作台可见 auto_review=true。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            engine = E2EFakeEngine(settings=settings)
            service = self._make_service(tmp_dir, engine, auto_review=True)

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一个测试短篇故事",
                    model_id="gpt-5.4",
                )
            )

            def always_approve(self, payload: ReviewPayload, policy: AutoReviewPolicy) -> ReviewDecision:
                return ReviewDecision(
                    approved=True,
                    comment="自动审核通过",
                    reasoning="测试自动通过",
                    auto_escalated=False,
                    overall_score=95.0,
                )

            with patch.object(AutoReviewManager, "review", always_approve):
                result = service._run_task_sync(task.id)

            # 1. 状态验证
            self.assertEqual(result.status, TaskStatus.COMPLETED)

            # 2. 工作台 API 验证 auto_review 可见
            workspace = service.get_workspace(task.id)
            self.assertTrue(workspace.meta.auto_review, "工作台应展示 auto_review=true")

            # 3. 审核页面验证 auto_review_trace 非空
            review_response = service.get_review(task.id)
            self.assertTrue(len(review_response.auto_review_trace) > 0, "自动审核应留下 trace")

            # 4. 事件日志验证：自动审核全通过，没有 review.waiting（因为没有进入人工审核中断）
            event_types = [e.event_type for e in result.events]
            self.assertNotIn("review.waiting", event_types)

    def test_manual_review_flow_shows_auto_review_false(self) -> None:
        """关闭自动审核时，工作台应展示 auto_review=false。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            engine = E2EFakeEngine(settings=settings)
            service = self._make_service(tmp_dir, engine, auto_review=False)

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="关闭自动审核的测试",
                    model_id="gpt-5.4",
                )
            )

            # 只运行到 outline_review 中断点（不提交审核）
            result = service._run_task_sync(task.id)

            # 验证状态停在大纲审核等待
            self.assertEqual(result.status, TaskStatus.WAITING_OUTLINE_REVIEW)

            # 工作台验证 auto_review=false
            workspace = service.get_workspace(task.id)
            self.assertFalse(workspace.meta.auto_review, "工作台应展示 auto_review=false")

    def test_error_transparency_records_last_error_detail(self) -> None:
        """任务进入稳定状态后，后台异常应被记录为 task.error_recorded，且工作台可见。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            engine = E2EFakeEngine(settings=settings)
            service = self._make_service(tmp_dir, engine, auto_review=True)

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="测试错误透传",
                    model_id="gpt-5.4",
                )
            )
            # 人为将任务推入稳定状态
            service.store.set_waiting_manual_action(
                task.id,
                "模拟用户已看到恢复方案",
                payload={"summary": "测试", "display_level": "public"},
            )

            # 模拟后台再次异常
            record = service._mark_failed_unless_stable(
                task.id, "真实异常：上游 API 返回空响应，已重试3次"
            )

            # 状态应保持不变
            self.assertEqual(record.status, TaskStatus.WAITING_MANUAL_ACTION)

            # 验证事件已记录
            error_events = [e for e in record.events if e.event_type == "task.error_recorded"]
            self.assertEqual(len(error_events), 1)
            self.assertIn("上游 API 返回空响应", error_events[0].message)

            # 工作台 API 应返回 last_error_detail
            workspace = service.get_workspace(task.id)
            self.assertIn("上游 API 返回空响应", workspace.meta.last_error_detail or "")

    def test_auto_review_escalation_logs_and_leaves_trace(self) -> None:
        """auto_review 异常时应降级到人工审核，并留下 auto_escalated=true 的 trace。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            engine = E2EFakeEngine(settings=settings)
            service = self._make_service(tmp_dir, engine, auto_review=True)

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="测试 auto_review 异常降级",
                    model_id="gpt-5.4",
                )
            )

            def raise_exception(self, payload: ReviewPayload, policy: AutoReviewPolicy) -> ReviewDecision:
                raise RuntimeError("模拟评分服务崩溃")

            with patch.object(AutoReviewManager, "review", raise_exception):
                result = service._run_task_sync(task.id)

            # 任务应停在大纲审核等待（人工审核）
            self.assertEqual(result.status, TaskStatus.WAITING_OUTLINE_REVIEW)

            # 验证 review_comment 包含异常信息（异常信息通过 _sync_result 注入 review.summary）
            self.assertIsNotNone(result.pending_review)
            self.assertIn("自动审核异常", result.pending_review.summary or "")


if __name__ == "__main__":
    unittest.main()
