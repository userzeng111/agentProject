import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.domain.models import ChapterDraft, ChapterPlan, ReviewDecision, StoryPlan
from app.graph.main_graph import build_graph
from tests.fakes import FakeVerifiedGatewayModelCatalog


class FakePacket:
    def __init__(self, stage: str) -> None:
        self.stage = stage

    def model_dump(self, mode: str = "json") -> dict:
        return {"stage": self.stage, "mode": mode}


class FakeSnapshot:
    def __init__(self, stage: str) -> None:
        self.packet = FakePacket(stage)
        self.stage = stage

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "stage": self.stage,
            "mode": mode,
            "packet": self.packet.model_dump(mode=mode),
        }


class FakeContextManager:
    def build_snapshot(self, task_id, stage, instruction, model_profile, references, memory_items):
        return FakeSnapshot(stage)


class FakeStreamingGatewayClient:
    def complete_stream_sync(self, messages, model=None):
        return iter(())


class FakeEngine:
    def __init__(self) -> None:
        self.gateway_client = object()
        self.revision_comments: list[str] = []
        self.seen_specs: list[dict] = []

    def build_story_plan(
        self,
        spec,
        reference_text,
        context_packet=None,
        model=None,
        revision_comment=None,
        original_plan=None,
    ):
        self.seen_specs.append(dict(spec))
        if revision_comment:
            self.revision_comments.append(revision_comment)
        return StoryPlan(
            working_title="测试标题",
            logline="测试梗概",
            world_notes=["世界观"],
            character_notes=["人物"],
            chapter_plan=[ChapterPlan(number=1, title="第一章", goal="建立冲突")],
        )

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
    ):
        return [
            ChapterDraft(
                number=1,
                title="第一章",
                summary="建立冲突",
                content="测试正文",
            )
        ]

    def build_chapter_plan_batch(self, spec, story_plan, batch_index, batch_size, confirmed_chapter_plans, model=None):
        chapter_plan = story_plan.get("chapter_plan") or []
        return [
            ChapterPlan(number=ch["number"], title=ch["title"], goal=ch["goal"])
            for ch in chapter_plan[batch_index : batch_index + batch_size]
        ]

    def revise_chapter_pair(
        self,
        current_pair,
        revision_comment,
        spec,
        story_plan,
        completed_chapters,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return [ChapterDraft.model_validate(item) for item in current_pair]

    def verify_full_story(
        self,
        completed_chapters,
        story_plan,
        spec,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return {"overall_score": 100, "issues": []}

    def verify_chapter_window(
        self,
        current_chapter_pair,
        completed_chapters,
        story_plan,
        spec,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return {"overall_score": 100, "issues": []}

    def fix_verified_issues(
        self,
        completed_chapters,
        verification_report,
        review_comment,
        story_plan,
        spec,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return completed_chapters


class FakeDynamicEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.gateway_client = FakeStreamingGatewayClient()
        self.chapter_gate_reports: list[dict] = []
        self.chapter_gate_calls = 0

    def verify_chapter_window(
        self,
        current_chapter_pair,
        completed_chapters,
        story_plan,
        spec,
        reference_text,
        context_packet=None,
        model=None,
    ):
        self.chapter_gate_calls += 1
        if self.chapter_gate_reports:
            return self.chapter_gate_reports.pop(0)
        return {"overall_score": 100, "issues": []}


class FakeAutoReviewManager:
    def __init__(self, decisions):
        self._decisions = list(decisions)

    def review(self, payload, policy):
        if payload.type == "outline_review":
            if self._decisions:
                return self._decisions.pop(0)
            return ReviewDecision(
                approved=True,
                comment="自动通过",
                reasoning="通过",
                overall_score=90,
            )
        return ReviewDecision(
            approved=True,
            comment="自动通过",
            reasoning="通过",
            overall_score=90,
        )


class FakeDynamicReviewBridge:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[str] = []
        self.payloads: list = []

    def review(self, payload, policy):
        self.calls.append(payload.type)
        self.payloads.append(payload)
        return ReviewDecision(
            approved=True,
            comment=f"动态审核通过：{payload.type}",
            reasoning="bridge",
            overall_score=91,
        )


class GraphAutoReviewEscalationTests(unittest.TestCase):
    def _initial_state(self) -> dict:
        return {
            "task_id": "task-auto-review",
            "input_payload": {
                "mode": "short_story",
                "prompt": "写一篇临海城市的悬疑故事",
                "genre": "悬疑",
                "style": "冷静克制",
                "target_words": 1800,
                "audience": "",
                "banned": "",
                "title_hint": "潮汐谜案",
                "model_id": "gpt-5.4",
            },
            "reference_text": "",
        }

    def test_auto_review_reject_without_self_revision_interrupts_for_manual_review(self) -> None:
        engine = FakeEngine()
        decisions = [
            ReviewDecision(
                approved=False,
                comment="评分不足，请人工审核。",
                reasoning="未通过",
                auto_escalated=True,
                overall_score=55,
                revision_needed=True,
            )
        ]
        manager = FakeAutoReviewManager(decisions)

        with patch("app.graph.main_graph.AutoReviewManager", return_value=manager):
            graph = build_graph(
                engine,
                context_manager=FakeContextManager(),
                model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
                auto_review=True,
                auto_review_policy={
                    "allow_self_revisions": False,
                    "max_auto_revisions": 0,
                },
            )

        result = graph.invoke(
            self._initial_state(),
            config={"configurable": {"thread_id": "task-auto-review-1"}},
        )

        self.assertIn("__interrupt__", result)
        self.assertEqual(result["__interrupt__"][0].value["type"], "outline_review")
        self.assertEqual(result["__interrupt__"][0].value["revision_count"], 0)
        self.assertEqual(engine.revision_comments, [])

    def test_auto_review_reject_after_one_self_revision_auto_passes(self) -> None:
        engine = FakeEngine()
        decisions = [
            ReviewDecision(
                approved=False,
                comment="先自动修订一次。",
                reasoning="首次未通过",
                auto_escalated=True,
                overall_score=60,
                revision_needed=True,
            ),
            ReviewDecision(
                approved=False,
                comment="二次仍未通过，请人工审核。",
                reasoning="再次未通过",
                auto_escalated=True,
                overall_score=62,
                revision_needed=True,
            ),
        ]
        manager = FakeAutoReviewManager(decisions)

        with patch("app.graph.main_graph.AutoReviewManager", return_value=manager):
            graph = build_graph(
                engine,
                context_manager=FakeContextManager(),
                model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
                auto_review=True,
                auto_review_policy={
                    "allow_self_revisions": True,
                    "max_auto_revisions": 1,
                },
            )

        result = graph.invoke(
            self._initial_state(),
            config={"configurable": {"thread_id": "task-auto-review-2"}},
        )

        # 达到 max_auto_revisions=1 后自动强制通过，不再中断到人工审核
        self.assertNotIn("__interrupt__", result)
        self.assertEqual(engine.revision_comments, ["先自动修订一次。"])

    def test_outline_stage_can_override_global_auto_revision_limit(self) -> None:
        engine = FakeEngine()
        decisions = [
            ReviewDecision(
                approved=False,
                comment="先自动修订一次。",
                reasoning="首次未通过",
                auto_escalated=True,
                overall_score=58,
                revision_needed=True,
            ),
            ReviewDecision(
                approved=False,
                comment="仍未通过，请人工审核。",
                reasoning="再次未通过",
                auto_escalated=True,
                overall_score=59,
                revision_needed=True,
            ),
        ]
        manager = FakeAutoReviewManager(decisions)

        with patch("app.graph.main_graph.AutoReviewManager", return_value=manager):
            graph = build_graph(
                engine,
                context_manager=FakeContextManager(),
                model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
                auto_review=True,
                auto_review_policy={
                    "allow_self_revisions": True,
                    "max_auto_revisions": 0,
                    "outline_max_auto_revisions": 1,
                },
            )

        result = graph.invoke(
            self._initial_state(),
            config={"configurable": {"thread_id": "task-auto-review-3"}},
        )

        # outline_max_auto_revisions=1 达到上限后自动强制通过，不再中断
        self.assertNotIn("__interrupt__", result)
        self.assertEqual(engine.revision_comments, ["先自动修订一次。"])

    def test_short_story_chapter_word_min_is_preserved(self) -> None:
        engine = FakeEngine()
        graph = build_graph(
            engine,
            context_manager=FakeContextManager(),
            model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
        )
        initial_state = self._initial_state()
        initial_state["input_payload"]["target_words"] = 1500

        graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": "task-auto-review-4"}},
        )

        self.assertTrue(engine.seen_specs)
        self.assertEqual(engine.seen_specs[0]["requested_target_words"], 1500)
        self.assertEqual(engine.seen_specs[0]["target_words"], 1500)
        self.assertEqual(engine.seen_specs[0]["chapter_word_min"], 1500)

    def test_dynamic_review_bridge_can_run_without_legacy_auto_review_manager(self) -> None:
        engine = FakeDynamicEngine()
        bridge = FakeDynamicReviewBridge()

        with patch("app.graph.main_graph.AutoReviewManager", return_value=None), patch(
            "app.settings.config.get_settings",
            return_value=SimpleNamespace(
                dynamic_agent_review=True,
                auto_review_auditor_model="gpt-5.4",
            ),
        ), patch(
            "app.agents.dynamic.bridge.DynamicReviewBridge",
            return_value=bridge,
        ):
            graph = build_graph(
                engine,
                context_manager=FakeContextManager(),
                model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
                auto_review=True,
                auto_review_policy={
                    "allow_self_revisions": True,
                    "max_auto_revisions": 0,
                },
            )

        result = graph.invoke(
            self._initial_state(),
            config={"configurable": {"thread_id": "task-auto-review-dynamic"}},
        )

        self.assertNotIn("__interrupt__", result)
        self.assertEqual(engine.chapter_gate_calls, 1)
        # 新行为：健康批次先过门禁，不再必进章节动态审核。
        self.assertEqual(
            bridge.calls,
            ["outline_review", "outline_review", "verification_review"],
        )

    def test_dynamic_review_bridge_skips_chapter_review_when_gate_has_no_critical_issue(self) -> None:
        engine = FakeDynamicEngine()
        engine.chapter_gate_reports = [
            {
                "overall_score": 86,
                "issues": [{"severity": "warning", "description": "节奏稍慢"}],
                "summary": "无严重问题",
            }
        ]
        bridge = FakeDynamicReviewBridge()

        with patch("app.graph.main_graph.AutoReviewManager", return_value=None), patch(
            "app.settings.config.get_settings",
            return_value=SimpleNamespace(
                dynamic_agent_review=True,
                auto_review_auditor_model="gpt-5.4",
                auto_review_max_workers=6,
            ),
        ), patch(
            "app.agents.dynamic.bridge.DynamicReviewBridge",
            return_value=bridge,
        ):
            graph = build_graph(
                engine,
                context_manager=FakeContextManager(),
                model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
                auto_review=True,
                auto_review_policy={
                    "allow_self_revisions": True,
                    "max_auto_revisions": 0,
                },
            )

        result = graph.invoke(
            self._initial_state(),
            config={"configurable": {"thread_id": "task-auto-review-gate-ok"}},
        )

        self.assertNotIn("__interrupt__", result)
        self.assertEqual(engine.chapter_gate_calls, 1)
        self.assertEqual(
            bridge.calls,
            ["outline_review", "outline_review", "verification_review"],
        )

    def test_dynamic_review_bridge_runs_targeted_chapter_review_when_gate_has_critical_issue(self) -> None:
        engine = FakeDynamicEngine()
        engine.chapter_gate_reports = [
            {
                "overall_score": 42,
                "issues": [{"severity": "critical", "description": "人物动机断裂，章节衔接失真"}],
                "summary": "存在严重问题",
            }
        ]
        bridge = FakeDynamicReviewBridge()

        with patch("app.graph.main_graph.AutoReviewManager", return_value=None), patch(
            "app.settings.config.get_settings",
            return_value=SimpleNamespace(
                dynamic_agent_review=True,
                auto_review_auditor_model="gpt-5.4",
                auto_review_max_workers=6,
            ),
        ), patch(
            "app.agents.dynamic.bridge.DynamicReviewBridge",
            return_value=bridge,
        ):
            graph = build_graph(
                engine,
                context_manager=FakeContextManager(),
                model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
                auto_review=True,
                auto_review_policy={
                    "allow_self_revisions": True,
                    "max_auto_revisions": 0,
                },
            )

        result = graph.invoke(
            self._initial_state(),
            config={"configurable": {"thread_id": "task-auto-review-gate-critical"}},
        )

        self.assertNotIn("__interrupt__", result)
        self.assertEqual(engine.chapter_gate_calls, 1)
        self.assertEqual(
            bridge.calls,
            ["outline_review", "outline_review", "chapter_pair_review", "verification_review"],
        )
        targeted_payload = next(item for item in bridge.payloads if item.type == "chapter_pair_review")
        self.assertEqual(targeted_payload.review_scope, "chapter_window")
        self.assertIsNotNone(targeted_payload.verification_report)
        self.assertTrue(targeted_payload.target_dimensions)


if __name__ == "__main__":
    unittest.main()
