import unittest

from app.domain.models import AutoReviewPolicy
from app.llm.auto_reviewer import AutoReviewManager, SubAgentSpec
from app.llm.gateway_client import GatewayClientError, StreamChunk


class FakeGatewayClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[list[dict[str, str]], str | None]] = []

    def complete_json(self, messages, model=None):
        self.calls.append((messages, model))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def complete_stream_sync(self, messages, model=None):
        """模拟流式调用：将 complete_json 的结果包装成单个 StreamChunk 返回。"""
        try:
            result = self.complete_json(messages, model)
            import json as _json

            yield StreamChunk(
                content=_json.dumps(result, ensure_ascii=False),
                finish_reason="stop",
                model=model or "",
            )
        except GatewayClientError:
            # 模拟真实 LLM 返回无法解析的内容，让上层 _strip_and_parse_json 抛异常
            yield StreamChunk(
                content="这不是有效的 JSON",
                finish_reason="stop",
                model=model or "",
            )

    def _strip_markdown_fences(self, raw: str) -> str:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            import re
            cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned, count=1)
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        return cleaned.strip()

    def _extract_first_json_value(self, text: str):
        return None


class AutoReviewerTests(unittest.TestCase):
    def test_run_sub_agent_retries_once_after_json_parse_failure(self) -> None:
        gateway = FakeGatewayClient(
            [
                GatewayClientError("模型返回的 JSON 无法解析"),
                {
                    "score": 88,
                    "issues": [],
                    "warnings": [],
                    "highlights": ["结构完整"],
                    "reasoning": "重试后解析成功",
                },
            ]
        )
        manager = AutoReviewManager(gateway_client=gateway)
        spec = SubAgentSpec(
            agent_id="agent-test",
            agent_name="结构分析师",
            role="structure",
            dimension="structure",
        )

        output = manager._run_sub_agent(
            spec=spec,
            prompt_text="请评估这个大纲。",
            model="MiniMax-M2.7-highspeed",
        )

        self.assertIsNone(output.error)
        self.assertEqual(output.score, 88)
        self.assertEqual(len(gateway.calls), 2)
        retry_messages, retry_model = gateway.calls[-1]
        self.assertEqual(retry_model, "MiniMax-M2.7-highspeed")
        self.assertEqual(retry_messages[-1]["role"], "user")
        self.assertIn("完整、可解析的 JSON", retry_messages[-1]["content"])

    def test_chapter_review_can_continue_when_score_passes_and_critical_escalation_disabled(self) -> None:
        manager = AutoReviewManager(gateway_client=FakeGatewayClient([]))
        policy = AutoReviewPolicy(
            chapter_pass_threshold=65,
            auto_escalate_on_critical=True,
            chapter_auto_escalate_on_critical=False,
        )

        decision = manager._build_decision(
            parsed={
                "overall_score": 82,
                "approved": False,
                "auto_escalated": False,
                "critical_issues": [
                    {
                        "severity": "critical",
                        "chapter": 3,
                        "dimension": "quality",
                        "description": "前情交代不足",
                        "suggestion": "补足背景",
                    }
                ],
                "warnings": [],
                "highlights": [],
                "comment": "",
                "reasoning": "",
            },
            outputs=[],
            review_type="chapter_pair_review",
            policy=policy,
            pass_threshold=policy.chapter_pass_threshold,
        )

        self.assertTrue(decision.approved)
        self.assertFalse(decision.auto_escalated)

    def test_outline_review_can_continue_when_score_passes_and_critical_escalation_disabled(self) -> None:
        manager = AutoReviewManager(gateway_client=FakeGatewayClient([]))
        policy = AutoReviewPolicy(
            outline_pass_threshold=60,
            auto_escalate_on_critical=True,
            outline_auto_escalate_on_critical=False,
        )

        decision = manager._build_decision(
            parsed={
                "overall_score": 78,
                "approved": False,
                "auto_escalated": False,
                "critical_issues": [
                    {
                        "severity": "critical",
                        "dimension": "consistency",
                        "description": "部分关系铺垫不足",
                        "suggestion": "补足铺垫",
                    }
                ],
                "warnings": [],
                "highlights": [],
                "comment": "",
                "reasoning": "",
            },
            outputs=[],
            review_type="outline_review",
            policy=policy,
            pass_threshold=policy.outline_pass_threshold,
        )

        self.assertTrue(decision.approved)
        self.assertFalse(decision.auto_escalated)


if __name__ == "__main__":
    unittest.main()
