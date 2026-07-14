import unittest
import json
from datetime import datetime, timezone

from app.agents.dynamic.factory import AgentFactory
from app.agents.dynamic.bridge import DynamicReviewBridge
from app.agents.dynamic.master import MasterAgent
from app.agents.dynamic.orchestrator import TaskOrchestrator
from app.agents.dynamic.models import AgentBlueprint, OrchestrationResult, TaskExecutionResult
from app.agents.dynamic.prompts import MASTER_BLUEPRINT_PROMPT
from app.domain.models import AutoReviewPolicy
from app.llm.gateway_client import StreamChunk


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


class AgentFactoryPromptRenderingTests(unittest.TestCase):
    def test_render_prompt_replaces_known_variables_without_formatting_json_examples(self) -> None:
        template = """
请审核正文：
{current_chapters_text}

请按如下 JSON 结构输出：
{"score": 80, "total_score": 80, "issues": [{"issue_location": "第1章", "description": "示例"}]}

综合其他 Agent：
{{sub_agents_json}}
"""

        rendered = AgentFactory.render_prompt(
            template,
            {
                "current_chapters_text": "第1章正文",
                "sub_agents_json": "[{\"agent_name\": \"结构分析师\"}]",
            },
        )

        self.assertIn("第1章正文", rendered)
        self.assertIn('[{"agent_name": "结构分析师"}]', rendered)
        self.assertIn('"score": 80', rendered)
        self.assertIn('"total_score": 80', rendered)
        self.assertIn('"issue_location": "第1章"', rendered)

    def test_execute_agent_handles_json_schema_in_prompt_template(self) -> None:
        class FakeGateway:
            def __init__(self) -> None:
                self.messages = None

            def _strip_markdown_fences(self, raw):
                return raw

            def _extract_first_json_value(self, raw):
                return json.loads(raw)

            def complete_stream_sync(self, messages, model, **kwargs):
                self.messages = messages
                yield StreamChunk(
                    content=(
                        '{"score": 88, "issues": [], "warnings": [], '
                        '"highlights": ["结构稳定"], "reasoning": "ok"}'
                    ),
                    model=model,
                    finish_reason="stop",
                )

        gateway = FakeGateway()
        factory = AgentFactory(gateway_client=gateway)
        agent = factory.create(
            AgentBlueprint(
                agent_name="章节质量审核员",
                role="chapter_review",
                dimension="章节质量",
                weight=1.0,
                system_prompt="你是章节质量审核员",
                user_prompt_template=(
                    "正文：{current_chapters_text}\n"
                    "输出示例："
                    '{"score": 80, "issues": [{"issue_location": "第1章"}]}\n'
                    "综合结果：{{sub_agents_json}}"
                ),
                output_format="json",
            )
        )

        result = factory.execute_agent(
            agent,
            {
                "current_chapters_text": "第1章正文",
                "sub_agents_json": "[{\"score\": 90}]",
            },
            model="test-model",
        )

        self.assertIsNone(result.error)
        self.assertEqual(result.score, 88)
        self.assertEqual(result.highlights, ["结构稳定"])
        self.assertIsNotNone(gateway.messages)
        user_prompt = gateway.messages[1]["content"]
        self.assertIn("第1章正文", user_prompt)
        self.assertIn('[{"score": 90}]', user_prompt)
        self.assertIn('"issue_location": "第1章"', user_prompt)

    def test_execute_agent_accepts_dimension_specific_score_field(self) -> None:
        class FakeGateway:
            def _strip_markdown_fences(self, raw):
                return raw

            def _extract_first_json_value(self, raw):
                return json.loads(raw)

            def complete_stream_sync(self, messages, model, **kwargs):
                yield StreamChunk(
                    content=(
                        '{"atmosphere_score": 91, "issues": [], "warnings": [], '
                        '"highlights": ["氛围稳定"], "reasoning": "悬疑氛围评分明确"}'
                    ),
                    model=model,
                    finish_reason="stop",
                )

        factory = AgentFactory(gateway_client=FakeGateway())
        agent = factory.create(
            AgentBlueprint(
                agent_name="悬疑氛围评估师",
                role="atmosphere",
                dimension="悬疑氛围",
                weight=1.0,
                system_prompt="你是悬疑氛围评估师",
                user_prompt_template="请审核：{current_chapters_text}",
                output_format="json",
            )
        )

        result = factory.execute_agent(agent, {"current_chapters_text": "第1章正文"}, model="test-model")

        self.assertIsNone(result.error)
        self.assertEqual(result.score, 91)
        self.assertEqual(result.highlights, ["氛围稳定"])

    def test_execute_agent_accepts_chinese_score_field(self) -> None:
        class FakeGateway:
            def _strip_markdown_fences(self, raw):
                return raw

            def _extract_first_json_value(self, raw):
                return json.loads(raw)

            def complete_stream_sync(self, messages, model, **kwargs):
                yield StreamChunk(
                    content=(
                        '{"评分": 86, "问题": [], "警告": [], '
                        '"亮点": ["章节计划完整"], "理由": "结构完整，逻辑清晰"}'
                    ),
                    model=model,
                    finish_reason="stop",
                )

        factory = AgentFactory(gateway_client=FakeGateway())
        agent = factory.create(
            AgentBlueprint(
                agent_name="结构完整性分析师",
                role="structure",
                dimension="结构完整性",
                weight=1.0,
                system_prompt="你是结构完整性分析师",
                user_prompt_template="请审核：{chapter_plan}",
                output_format="json",
            )
        )

        result = factory.execute_agent(agent, {"chapter_plan": "第1章到第8章"}, model="test-model")

        self.assertIsNone(result.error)
        self.assertEqual(result.score, 86)
        self.assertEqual(result.highlights, ["章节计划完整"])
        self.assertEqual(result.reasoning, "结构完整，逻辑清晰")


class MasterAgentBlueprintTests(unittest.TestCase):
    def test_master_blueprint_prompt_exposes_outline_review_content_variables(self) -> None:
        for variable in (
            "{{working_title}}",
            "{{logline}}",
            "{{world_notes}}",
            "{{character_notes}}",
            "{{chapter_plan}}",
        ):
            self.assertIn(variable, MASTER_BLUEPRINT_PROMPT)

        self.assertIn("outline_review", MASTER_BLUEPRINT_PROMPT)
        self.assertIn("大纲", MASTER_BLUEPRINT_PROMPT)

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


class TaskOrchestratorSynthesisScoreTests(unittest.TestCase):
    def test_backfill_synthesis_score_from_overall_score_when_missing(self) -> None:
        synthesis = TaskExecutionResult(
            agent_id="agent-synthesis",
            agent_name="综合决策专家",
            role="synthesis",
            dimension="综合决策",
            execution_kind="synthesis",
            score=0.0,
            raw_response={"final_recommendation": "通过"},
            started_at=_utc_now(),
            completed_at=_utc_now(),
        )

        TaskOrchestrator._backfill_synthesis_score(synthesis, 87.0)

        self.assertEqual(synthesis.score, 87.0)
        self.assertEqual(synthesis.raw_response["score"], 87.0)
        self.assertEqual(synthesis.raw_response["overall_score"], 87.0)

    def test_backfill_synthesis_score_keeps_existing_explicit_score(self) -> None:
        synthesis = TaskExecutionResult(
            agent_id="agent-synthesis",
            agent_name="综合决策专家",
            role="synthesis",
            dimension="综合决策",
            execution_kind="synthesis",
            score=92.0,
            raw_response={"score": 92.0},
            started_at=_utc_now(),
            completed_at=_utc_now(),
        )

        TaskOrchestrator._backfill_synthesis_score(synthesis, 87.0)

        self.assertEqual(synthesis.score, 92.0)
        self.assertEqual(synthesis.raw_response["score"], 92.0)


if __name__ == "__main__":
    unittest.main()
