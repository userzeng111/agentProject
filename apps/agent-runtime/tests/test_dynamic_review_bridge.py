import unittest
from datetime import datetime, timezone

from app.agents.dynamic.bridge import DynamicReviewBridge
from app.agents.dynamic.master import MasterAgent
from app.agents.dynamic.models import OrchestrationResult, TaskExecutionResult
from app.domain.models import AutoReviewPolicy


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DynamicReviewBridgeTraceTests(unittest.TestCase):
    def test_convert_to_review_decision_includes_main_agent_subagent_and_synthesis_semantics(self) -> None:
        bridge = DynamicReviewBridge(gateway_client=object())
        started_at = _utc_now()
        completed_at = _utc_now()
        result = OrchestrationResult(
            task_description="审核测试任务",
            agent_results=[
                TaskExecutionResult(
                    agent_id="agent-structure",
                    agent_name="结构分析师",
                    role="structure",
                    dimension="结构",
                    weight=0.5,
                    score=81,
                    reasoning="结构完整",
                    started_at=started_at,
                    completed_at=completed_at,
                ),
                TaskExecutionResult(
                    agent_id="agent-style",
                    agent_name="风格分析师",
                    role="style",
                    dimension="风格",
                    weight=0.5,
                    score=77,
                    reasoning="风格稳定",
                    started_at=started_at,
                    completed_at=completed_at,
                ),
            ],
            synthesis_result=TaskExecutionResult(
                agent_id="agent-synthesis",
                agent_name="综合裁决专家",
                role="synthesis",
                dimension="综合裁决",
                weight=1.0,
                score=84,
                reasoning="综合通过",
                raw_response={
                    "final_recommendation": "可以通过",
                    "reasoning": "整体质量达标",
                },
                started_at=started_at,
                completed_at=completed_at,
            ),
            overall_score=84,
        )

        decision = bridge._convert_to_review_decision(
            result,
            AutoReviewPolicy(),
            "outline_review",
        )

        self.assertEqual(len(decision.agent_trace), 4)

        main_agent = decision.agent_trace[0]
        self.assertEqual(main_agent.execution_kind, "main_agent")
        self.assertEqual(main_agent.agent_id, "dynamic-review-main")
        self.assertEqual(main_agent.role, "orchestrator")
        self.assertEqual(main_agent.status, "completed")

        subagents = [item for item in decision.agent_trace if item.execution_kind == "subagent"]
        self.assertEqual(len(subagents), 2)
        self.assertTrue(all(item.parent_agent_id == "dynamic-review-main" for item in subagents))
        self.assertTrue(all(item.created_by == "main_agent" for item in subagents))

        synthesis = next(item for item in decision.agent_trace if item.execution_kind == "synthesis")
        self.assertEqual(synthesis.parent_agent_id, "dynamic-review-main")
        self.assertEqual(synthesis.created_by, "main_agent")
        self.assertEqual(synthesis.agent_name, "综合裁决专家")


class MasterAgentBlueprintTests(unittest.TestCase):
    def test_parse_blueprints_deduplicates_overlapping_agents_and_keeps_single_synthesis(self) -> None:
        master = MasterAgent(gateway_client=None)
        response = {
            "analysis_reasoning": "测试去重",
            "agents": [
                {
                    "agent_name": "结构分析师A",
                    "role": "structure",
                    "dimension": "结构",
                    "weight": 0.4,
                    "system_prompt": "分析结构",
                    "user_prompt_template": "请分析 {content}",
                    "dependencies": [],
                    "group": "analysis",
                    "is_synthesis": False,
                    "output_format": "json",
                },
                {
                    "agent_name": "结构分析师B",
                    "role": "structure",
                    "dimension": "结构",
                    "weight": 0.3,
                    "system_prompt": "重复结构分析",
                    "user_prompt_template": "请再次分析 {content}",
                    "dependencies": [],
                    "group": "analysis",
                    "is_synthesis": False,
                    "output_format": "json",
                },
                {
                    "agent_name": "人物分析师",
                    "role": "character",
                    "dimension": "人物",
                    "weight": 0.3,
                    "system_prompt": "分析人物",
                    "user_prompt_template": "请分析 {content}",
                    "dependencies": [],
                    "group": "analysis",
                    "is_synthesis": False,
                    "output_format": "json",
                },
                {
                    "agent_name": "综合裁决专家A",
                    "role": "synthesis",
                    "dimension": "综合裁决",
                    "weight": 1.0,
                    "system_prompt": "综合裁决",
                    "user_prompt_template": "请综合 {sub_agents_json}",
                    "dependencies": ["structure", "character"],
                    "group": "synthesis",
                    "is_synthesis": True,
                    "output_format": "json",
                },
                {
                    "agent_name": "综合裁决专家B",
                    "role": "synthesis",
                    "dimension": "最终裁决",
                    "weight": 1.0,
                    "system_prompt": "重复综合裁决",
                    "user_prompt_template": "请再次综合 {sub_agents_json}",
                    "dependencies": ["structure", "character"],
                    "group": "synthesis",
                    "is_synthesis": True,
                    "output_format": "json",
                },
            ],
        }

        blueprints = master._parse_blueprints(response)

        self.assertEqual(len(blueprints), 3)
        self.assertEqual(
            [(item.role, item.dimension, item.execution_kind) for item in blueprints],
            [
                ("structure", "结构", "subagent"),
                ("character", "人物", "subagent"),
                ("synthesis", "综合裁决", "synthesis"),
            ],
        )

        synthesis = next(item for item in blueprints if item.is_synthesis)
        self.assertEqual(synthesis.created_by, "main_agent")
        self.assertEqual(len(synthesis.dependencies), 2)
        self.assertEqual(len({dep for dep in synthesis.dependencies}), 2)


if __name__ == "__main__":
    unittest.main()
