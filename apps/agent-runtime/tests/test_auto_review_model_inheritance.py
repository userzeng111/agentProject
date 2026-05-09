import unittest
from unittest.mock import MagicMock

from app.application.task_service.core import TaskServiceCoreMixin
from app.domain.models import (
    AutoReviewModelMode,
    AutoReviewPolicy,
    TaskCreateRequest,
    TaskMode,
)
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine
from app.storage.task_store import TaskLogStore


class FakeSettings:
    openai_api_key = "test"
    openai_base_url = "http://test"
    default_chat_model = "gpt-5.4"
    llm_provider = "openai"
    tasklog_root = "/tmp/test_tasklog"


class AutoReviewModelInheritanceTests(unittest.TestCase):
    def _make_service(self, tasklog_root="/tmp/test_auto_review_model"):
        settings = FakeSettings()
        settings.tasklog_root = tasklog_root
        store = TaskLogStore(root_dir=tasklog_root)
        engine = MagicMock(spec=StoryEngine)
        engine.settings = settings
        engine.gateway_client = MagicMock()
        model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
        service = TaskServiceCoreMixin(
            store=store,
            engine=engine,
            model_catalog=model_catalog,
            auto_review=True,
        )
        # mock 缺失的 supervisor 方法
        service._derive_supervisor_subtask_status = MagicMock(return_value={})
        return service

    def test_initial_state_injects_task_model_into_auto_review_policy(self):
        service = self._make_service()
        payload = TaskCreateRequest(
            model_id="K2.6",
            prompt="测试",
            genre="悬疑",
            style="冷静",
            mode=TaskMode.SHORT_STORY,
        )
        task = service.create_task(payload)
        initial_state = service._initial_state(task)

        policy = AutoReviewPolicy.model_validate(initial_state["auto_review_policy"])
        self.assertEqual(policy.auditor_model, "K2.6")
        self.assertEqual(policy.synthesis_model, "K2.6")
        self.assertEqual(initial_state["input_payload"]["model_id"], "K2.6")

    def test_initial_state_follow_mode_ignores_configured_default_review_model(self):
        service = self._make_service()
        service.auto_review_policy = {
            "auto_review_model_mode": AutoReviewModelMode.FOLLOW_CREATIVE.value,
            "auditor_model": "MiniMax-M2.7-highspeed",
            "synthesis_model": "MiniMax-M2.7-highspeed",
        }
        payload = TaskCreateRequest(
            model_id="K2.6",
            prompt="测试",
            genre="悬疑",
            style="冷静",
            mode=TaskMode.SHORT_STORY,
            auto_review_model_mode=AutoReviewModelMode.FOLLOW_CREATIVE,
        )
        task = service.create_task(payload)
        initial_state = service._initial_state(task)

        policy = AutoReviewPolicy.model_validate(initial_state["auto_review_policy"])
        self.assertEqual(policy.auto_review_model_mode, AutoReviewModelMode.FOLLOW_CREATIVE)
        self.assertEqual(policy.auditor_model, "K2.6")
        self.assertEqual(policy.synthesis_model, "K2.6")

    def test_initial_state_fixed_mode_uses_task_review_model(self):
        service = self._make_service()
        payload = TaskCreateRequest(
            model_id="K2.6",
            prompt="测试",
            genre="悬疑",
            style="冷静",
            mode=TaskMode.SHORT_STORY,
            auto_review_model_mode=AutoReviewModelMode.FIXED,
            review_model_id="glm-5.1",
        )
        task = service.create_task(payload)
        initial_state = service._initial_state(task)

        policy = AutoReviewPolicy.model_validate(initial_state["auto_review_policy"])
        self.assertEqual(policy.auto_review_model_mode, AutoReviewModelMode.FIXED)
        self.assertEqual(policy.auditor_model, "glm-5.1")
        self.assertEqual(policy.synthesis_model, "glm-5.1")

    def test_initial_state_respects_explicit_policy_override(self):
        service = self._make_service()
        service.auto_review_policy = {
            "auditor_model": "claude-sonnet-4-6",
            "synthesis_model": "claude-opus-4-6",
        }
        payload = TaskCreateRequest(
            model_id="K2.6",
            prompt="测试",
            genre="悬疑",
            style="冷静",
            mode=TaskMode.SHORT_STORY,
        )
        task = service.create_task(payload)
        initial_state = service._initial_state(task)

        policy = AutoReviewPolicy.model_validate(initial_state["auto_review_policy"])
        self.assertEqual(policy.auditor_model, "claude-sonnet-4-6")
        self.assertEqual(policy.synthesis_model, "claude-opus-4-6")

    def test_initial_state_fallback_to_default_when_no_task_model(self):
        service = self._make_service()
        payload = TaskCreateRequest(
            model_id="",
            prompt="测试",
            genre="悬疑",
            style="冷静",
            mode=TaskMode.SHORT_STORY,
        )
        task = service.create_task(payload)
        # 任务 model_id 为空时会 fallback 到默认模型
        initial_state = service._initial_state(task)
        expected_model = service.model_catalog._effective_default_model()
        self.assertEqual(initial_state["input_payload"]["model_id"], expected_model)
        policy = AutoReviewPolicy.model_validate(initial_state["auto_review_policy"])
        self.assertEqual(policy.auditor_model, expected_model)
        self.assertEqual(policy.synthesis_model, expected_model)

    def test_resume_rehydrate_updates_model_in_state(self):
        service = self._make_service()
        payload = TaskCreateRequest(
            model_id="K2.6",
            prompt="测试",
            genre="悬疑",
            style="冷静",
            mode=TaskMode.SHORT_STORY,
        )
        task = service.create_task(payload)
        # 模拟 resume 时传入不同的 action_model_id
        initial_state = service._initial_state(task, action_model_id="glm-5.1")
        policy = AutoReviewPolicy.model_validate(initial_state["auto_review_policy"])
        self.assertEqual(policy.auditor_model, "glm-5.1")
        self.assertEqual(policy.synthesis_model, "glm-5.1")


if __name__ == "__main__":
    unittest.main()
