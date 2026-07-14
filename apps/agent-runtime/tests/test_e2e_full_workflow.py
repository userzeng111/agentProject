"""端到端全流程测试：从小说创建到归档。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.application.task_service import TaskService
from app.domain.models import (
    AutoReviewPolicy,
    DraftResult,
    ReviewDecision,
    ReviewPayload,
    StoryPlan,
    TaskCreateRequest,
    TaskMode,
    TaskStatus,
)
from app.llm.auto_reviewer import AutoReviewManager
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore

from tests.fakes import (
    FakeGatewayClient,
    FakeStoryEngine,
    build_verified_gateway_model_catalog,
)


class E2EFakeEngine(FakeStoryEngine):
    """增强版 FakeStoryEngine，补充端到端测试所需的附加属性。"""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or Settings(
            OPENAI_API_KEY="test-key",
            tasklog_root="/tmp",
        )
        self.gateway_client = FakeGatewayClient()
        self.gateway_client.list_models = lambda: [
            {"id": "gpt-5.4", "object": "model", "owned_by": "openai"},
            {"id": "auditor-x", "object": "model", "owned_by": "test"},
            {"id": "synthesis-y", "object": "model", "owned_by": "test"},
        ]

class TestE2EFullWorkflow(unittest.TestCase):
    """验证从任务创建到工作流完成的完整链路。"""

    def _make_service(self, tmp_dir: str, engine: E2EFakeEngine) -> TaskService:
        store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
        return TaskService(
            store=store,
            engine=engine,
            model_catalog=build_verified_gateway_model_catalog(
                engine.settings,
                engine.gateway_client,
            ),
            auto_review=True,
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

    def test_short_story_auto_review_to_completion(self) -> None:
        """短篇故事在自动审核全开的情况下应一次性走到 COMPLETED。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            engine = E2EFakeEngine(settings=settings)
            service = self._make_service(tmp_dir, engine)

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一个测试短篇故事",
                    model_id="gpt-5.4",
                )
            )
            self.assertEqual(task.status, TaskStatus.CREATED)

            def always_approve(
                self: AutoReviewManager,
                payload: ReviewPayload,
                policy: AutoReviewPolicy,
            ) -> ReviewDecision:
                return ReviewDecision(
                    approved=True,
                    comment="自动审核通过",
                    reasoning="测试自动通过",
                    auto_escalated=False,
                    overall_score=95.0,
                )

            with patch.object(AutoReviewManager, "review", always_approve):
                result = service._run_task_sync(task.id)

            self.assertEqual(result.status, TaskStatus.COMPLETED)
            self.assertIsNotNone(result.story_plan)
            self.assertIsInstance(result.story_plan, StoryPlan)
            self.assertIsNotNone(result.draft_result)
            self.assertIsInstance(result.draft_result, DraftResult)
            self.assertEqual(len(result.draft_result.chapters), 5)

    def test_long_story_batches_to_completion(self) -> None:
        """长篇故事分批生成后应走到 COMPLETED。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                OPENAI_API_KEY="test-key",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            engine = E2EFakeEngine(settings=settings)
            # 将章节扩展到 6 章，验证多批次累积逻辑
            original_build_plan = engine.build_story_plan

            def build_plan_with_6_chapters(*args, **kwargs):
                plan = original_build_plan(*args, **kwargs)
                from app.domain.models import ChapterPlan

                plan.chapter_plan = [
                    ChapterPlan(number=i, title=f"第{i}章", goal=f"目标{i}")
                    for i in range(1, 7)
                ]
                return plan

            engine.build_story_plan = build_plan_with_6_chapters
            service = self._make_service(tmp_dir, engine)

            task = service.create_task(
                TaskCreateRequest(
                    mode=TaskMode.LONG_STORY,
                    prompt="写一个测试长篇小说",
                    model_id="gpt-5.4",
                )
            )

            def always_approve(
                self: AutoReviewManager,
                payload: ReviewPayload,
                policy: AutoReviewPolicy,
            ) -> ReviewDecision:
                return ReviewDecision(
                    approved=True,
                    comment="自动审核通过",
                    reasoning="测试自动通过",
                    auto_escalated=False,
                    overall_score=95.0,
                )

            with patch.object(AutoReviewManager, "review", always_approve):
                result = service._run_task_sync(task.id)

            self.assertEqual(result.status, TaskStatus.COMPLETED)
            self.assertIsNotNone(result.draft_result)
            self.assertEqual(len(result.draft_result.chapters), 6)


if __name__ == "__main__":
    unittest.main()
