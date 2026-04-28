"""
Agent 工厂

根据 AgentBlueprint 动态实例化可执行的 DynamicAgent。
负责 prompt 模板渲染、gateway_client 注入、变量校验。
"""

from __future__ import annotations

import re
from app.observability import get_logger
from typing import Any

from app.agents.base import BaseAgent
from app.agents.dynamic.models import (
    AgentBlueprint,
    DynamicAgent,
    DynamicAgentStatus,
    TaskExecutionResult,
)
from app.llm.gateway_client import OpenAICompatibleGatewayClient

logger = get_logger(__name__)


class AgentFactory:
    """根据 Blueprint 创建 DynamicAgent 实例。"""

    def __init__(
        self,
        gateway_client: OpenAICompatibleGatewayClient,
        default_model: str = "MiniMax-M2.7-highspeed",
    ) -> None:
        self._gateway_client = gateway_client
        self._default_model = default_model

    def create(self, blueprint: AgentBlueprint) -> DynamicAgent:
        """根据蓝图创建单个 DynamicAgent 实例。"""
        if blueprint.created_by != "main_agent":
            raise ValueError(f"仅允许主 Agent 派发子执行单元，当前来源: {blueprint.created_by}")
        agent = DynamicAgent(
            blueprint=blueprint,
            status=DynamicAgentStatus.IDLE,
        )
        logger.info(
            "Agent 工厂创建 Agent: %s（角色: %s，维度: %s，权重: %.2f）",
            agent.blueprint.agent_name,
            agent.blueprint.role,
            agent.blueprint.dimension,
            agent.blueprint.weight,
        )
        return agent

    def create_batch(self, blueprints: list[AgentBlueprint]) -> list[DynamicAgent]:
        """批量创建 DynamicAgent 实例。"""
        return [self.create(bp) for bp in blueprints]

    @staticmethod
    def render_prompt(
        template: str,
        variables: dict[str, Any],
    ) -> str:
        """渲染 prompt 模板，安全替换变量。"""
        try:
            # 只替换模板中存在的变量，忽略多余变量
            return template.format(**{
                k: v for k, v in variables.items()
                if f"{{{k}}}" in template
            })
        except KeyError:
            # 缺少变量时用空字符串替代
            used_vars = set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", template))
            safe_vars = {k: variables.get(k, "") for k in used_vars}
            return template.format(**safe_vars)

    def execute_agent(
        self,
        agent: DynamicAgent,
        variables: dict[str, Any],
        model: str | None = None,
    ) -> TaskExecutionResult:
        """执行单个 DynamicAgent，返回执行结果。"""
        from datetime import datetime, timezone

        bp = agent.blueprint
        started_at = datetime.now(timezone.utc)
        agent.status = DynamicAgentStatus.RUNNING
        agent.started_at = started_at

        logger.info("开始执行 Agent: %s（角色: %s）", bp.agent_name, bp.role)

        try:
            # 渲染 prompt
            user_prompt = self.render_prompt(bp.user_prompt_template, variables)

            # 当要求 JSON 输出时，强制追加 JSON 格式和评分要求
            if bp.output_format == "json":
                user_prompt += (
                    "\n\n【强制输出要求】"
                    "你必须且只能返回一个合法的 JSON 对象，不要输出 Markdown 代码围栏，不要输出任何额外解释。"
                    "JSON 必须包含以下字段："
                    ' "score": 0-100 之间的数值评分（必填，不得省略）；'
                    ' "issues": 问题列表（数组，可选）；'
                    ' "warnings": 警告列表（数组，可选）；'
                    ' "highlights": 亮点列表（数组，可选）；'
                    ' "reasoning": 评分理由（字符串，可选）。'
                )

            # 构建消息
            messages = [
                {"role": "system", "content": bp.system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            # 调用 LLM
            use_model = model or self._default_model

            # 使用 BaseAgent 的 JSON 调用能力
            base = BaseAgent(gateway_client=self._gateway_client)
            if bp.output_format == "json":
                response = base._call_llm_json(
                    messages, use_model, max_retries=1,
                    stage=bp.role, unit_id=agent.id,
                )
            else:
                raw_text = base._call_llm_stream(
                    messages, use_model,
                    stage=bp.role, unit_id=agent.id,
                )
                response = {"text": raw_text}

            completed_at = datetime.now(timezone.utc)
            agent.status = DynamicAgentStatus.COMPLETED
            agent.completed_at = completed_at

            # 兼容多种评分字段名：score / total_score / overall_score / weighted_score / final_score / synthesis_score
            score = 0.0
            for score_key in ("score", "total_score", "overall_score", "weighted_score", "final_score", "synthesis_score"):
                if score_key in response and response[score_key] is not None:
                    try:
                        score = float(response[score_key])
                        break
                    except (ValueError, TypeError):
                        pass

            # 评分缺失时记录警告并尝试从 reasoning 中 fallback 提取
            if score == 0.0 and bp.output_format == "json":
                reasoning_text = str(response.get("reasoning", ""))
                # 尝试从 reasoning 中提取 "XX分" 或 "评分：XX" 之类的数值
                m = re.search(r"(?:评分|得分|分数)[:：\s]*(\d+(?:\.\d+)?)", reasoning_text)
                if m:
                    try:
                        score = float(m.group(1))
                        logger.warning(
                            "Agent %s 的 JSON 中缺少 score 字段，从 reasoning 中 fallback 提取到 %.1f",
                            bp.agent_name, score,
                        )
                    except (ValueError, TypeError):
                        pass
                else:
                    logger.warning(
                        "Agent %s 返回的 JSON 中缺少 score 字段，response_keys=%s",
                        bp.agent_name, list(response.keys()),
                    )

            # 兼容多种问题/警告/亮点字段名
            issues = response.get("issues") or response.get("key_issues") or []
            warnings = response.get("warnings") or response.get("weaknesses") or []
            highlights = (
                response.get("highlights")
                or response.get("key_strengths")
                or response.get("strengths")
                or []
            )
            reasoning = (
                response.get("reasoning", "")
                or response.get("analysis", "")
                or response.get("comment", "")
                or ""
            )

            result = TaskExecutionResult(
                agent_id=agent.id,
                agent_name=bp.agent_name,
                role=bp.role,
                dimension=bp.dimension,
                weight=bp.weight,
                execution_kind=bp.execution_kind,
                created_by=bp.created_by,
                invocation_kind=bp.invocation_kind,
                score=score,
                issues=issues,
                warnings=warnings,
                highlights=highlights,
                reasoning=reasoning,
                raw_response=response,
                started_at=started_at,
                completed_at=completed_at,
            )
            agent.output = result

            logger.info(
                "Agent 执行完成: %s，评分: %.1f，耗时: %dms",
                bp.agent_name,
                result.score,
                result.duration_ms or 0,
            )
            return result

        except Exception as e:
            completed_at = datetime.now(timezone.utc)
            agent.status = DynamicAgentStatus.FAILED
            agent.completed_at = completed_at

            result = TaskExecutionResult(
                agent_id=agent.id,
                agent_name=bp.agent_name,
                role=bp.role,
                dimension=bp.dimension,
                weight=bp.weight,
                execution_kind=bp.execution_kind,
                created_by=bp.created_by,
                invocation_kind=bp.invocation_kind,
                error=str(e),
                started_at=started_at,
                completed_at=completed_at,
            )
            agent.output = result

            logger.error(
                "Agent 执行失败: %s，错误: %s，output_format=%s，template_vars=%s",
                bp.agent_name, e, bp.output_format, list(variables.keys()),
            )
            return result
