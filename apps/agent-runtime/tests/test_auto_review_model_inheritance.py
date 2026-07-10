import tempfile
import unittest
from unittest.mock import MagicMock

from app.application.task_service.core import TaskServiceCoreMixin
from app.domain.models import (
    AutoReviewModelMode,
    AutoReviewPolicy,
    TaskCreateRequest,
    TaskMode,
)
from app.llm.story_engine import StoryEngine
from app.storage.task_store import TaskLogStore
from tests.fakes import build_verified_gateway_model_catalog


class FakeSettings:
    openai_api_key = "test"
    openai_base_url = "http://test"
    default_chat_model = ""
    llm_provider = "openai"
    tasklog_root = "/tmp/test_tasklog"


class AutoReviewModelInheritanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_dir.cleanup)

    def _make_service(self, tasklog_root: str | None = None):
        tasklog_root = tasklog_root or self._temporary_dir.name
        settings = FakeSettings()
        settings.tasklog_root = tasklog_root
        store = TaskLogStore(root_dir=tasklog_root)
        engine = MagicMock(spec=StoryEngine)
        engine.settings = settings
        engine.gateway_client = MagicMock()
        engine.gateway_client.list_models.return_value = [
            {"id": "K2.6", "object": "model", "owned_by": "custom"},
            {"id": "glm-5.1", "object": "model", "owned_by": "zhipu"},
            {"id": "MiniMax-M2.7-highspeed", "object": "model", "owned_by": "minimax"},
            {"id": "claude-sonnet-4-6", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-opus-4-6", "object": "model", "owned_by": "anthropic"},
        ]
        model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
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

    def test_fixed_auto_review_policy_rejects_offline_legacy_models_before_execution(self):
        service = self._make_service()
        task = service.create_task(
            TaskCreateRequest(
                model_id="K2.6",
                prompt="测试",
                genre="悬疑",
                style="冷静",
                mode=TaskMode.SHORT_STORY,
            )
        )
        task.auto_review_policy = {
            "auto_review_model_mode": AutoReviewModelMode.FIXED.value,
            "auditor_model": "retired-auditor-model",
            "synthesis_model": "glm-5.1",
        }

        with self.assertRaisesRegex(ValueError, "retired-auditor-model.*不在当前供应商模型目录"):
            service._resolve_auto_review_policy(task)

    def test_initial_state_does_not_validate_fixed_policy_when_auto_review_is_disabled(self):
        service = self._make_service()
        task = service.create_task(
            TaskCreateRequest(
                model_id="K2.6",
                prompt="测试",
                genre="悬疑",
                style="冷静",
                mode=TaskMode.SHORT_STORY,
                auto_review=False,
            )
        )
        task.auto_review_policy = {
            "auto_review_model_mode": AutoReviewModelMode.FIXED.value,
            "auditor_model": "retired-auditor-model",
            "synthesis_model": "retired-synthesis-model",
        }

        initial_state = service._initial_state(task)

        self.assertFalse(initial_state["auto_review"])
        self.assertEqual(initial_state["auto_review_policy"]["auditor_model"], "retired-auditor-model")

    def test_create_task_rejects_empty_model_without_default_fallback(self):
        service = self._make_service()
        payload = TaskCreateRequest(
            model_id="",
            prompt="测试",
            genre="悬疑",
            style="冷静",
            mode=TaskMode.SHORT_STORY,
        )

        with self.assertRaisesRegex(ValueError, "请显式选择"):
            service.create_task(payload)

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
