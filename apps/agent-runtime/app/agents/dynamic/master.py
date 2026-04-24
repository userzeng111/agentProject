"""
Master Agent

通过 LLM 动态分析任务，自主决定需要创建哪些 Agent 角色。
不依赖预定义配置，完全由 LLM 根据任务特征生成 AgentBlueprint。
"""

from __future__ import annotations

from app.observability import get_logger
from typing import Any

from app.agents.base import BaseAgent
from app.agents.dynamic.models import AgentBlueprint
from app.agents.dynamic.prompts import MASTER_BLUEPRINT_PROMPT, MASTER_SYSTEM_PROMPT
from app.llm.gateway_client import OpenAICompatibleGatewayClient

logger = get_logger(__name__)


class MasterAgent(BaseAgent):
    """
    主 Agent — LLM 驱动的动态 Agent 规划器。

    职责：
    - 分析任务类型、复杂度、评估维度
    - 通过 LLM 动态生成 AgentBlueprint 列表
    - 每个 Blueprint 包含角色名、prompt、权重、依赖关系
    """

    _skill_subdir = "master"

    def __init__(
        self,
        gateway_client: OpenAICompatibleGatewayClient | None = None,
        default_model: str = "MiniMax-M2.7-highspeed",
    ) -> None:
        super().__init__(gateway_client=gateway_client)
        self.default_model = default_model

    def analyze_task(
        self,
        task_type: str,
        task_description: str,
        context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> list[AgentBlueprint]:
        """
        分析任务并动态生成 Agent 蓝图。

        Args:
            task_type: 任务类型（如 outline_review, chapter_review, custom）
            task_description: 任务描述
            context: 任务上下文（题材、风格、字数等）
            model: 使用的模型（默认 self.default_model）

        Returns:
            AgentBlueprint 列表
        """
        use_model = model or self.default_model
        context = context or {}

        # 构建上下文摘要
        context_summary = self._build_context_summary(context)

        # 渲染 Master prompt
        user_prompt = MASTER_BLUEPRINT_PROMPT.format(
            task_type=task_type,
            task_description=task_description,
            task_mode=context.get("task_mode", "未指定"),
            genre=context.get("genre", "未指定"),
            style=context.get("style", "未指定"),
            target_words=context.get("target_words", "未指定"),
            context_summary=context_summary,
        )

        messages = [
            {"role": "system", "content": MASTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        logger.info("Master Agent 开始分析任务: %s", task_type)

        # 调用 LLM 获取蓝图
        response = self._call_llm_json(
            messages, use_model, max_retries=1,
            stage="master_analysis",
        )

        # 解析为 AgentBlueprint
        blueprints = self._parse_blueprints(response)
        logger.info(
            "Master Agent 分析完成，生成 %d 个 Agent 蓝图: %s",
            len(blueprints),
            [bp.agent_name for bp in blueprints],
        )

        return blueprints

    def _build_context_summary(self, context: dict[str, Any]) -> str:
        """构建上下文摘要文本。"""
        if not context:
            return "无额外上下文信息"

        parts = []
        for key, value in context.items():
            if value and value != "未指定":
                parts.append(f"- {key}: {value}")

        return "\n".join(parts) if parts else "无额外上下文信息"

    def _parse_blueprints(self, response: dict[str, Any]) -> list[AgentBlueprint]:
        """将 LLM 响应解析为 AgentBlueprint 列表。"""
        agents_data = response.get("agents", [])
        if not agents_data:
            logger.warning("LLM 未返回任何 Agent 定义，使用 fallback")
            return self._fallback_blueprints()

        # 建立 role -> agent_id 的映射，用于解析依赖关系
        role_to_id: dict[str, str] = {}
        blueprints: list[AgentBlueprint] = []
        normalized_sources: list[dict[str, Any]] = []
        seen_analysis_keys: set[tuple[str, str]] = set()
        synthesis_seen = False

        # 先创建所有蓝图（不含依赖）
        for agent_data in agents_data:
            role = str(agent_data.get("role", "unknown")).strip() or "unknown"
            dimension = str(agent_data.get("dimension", "未知维度")).strip() or "未知维度"
            is_synthesis = bool(agent_data.get("is_synthesis", False) or role == "synthesis")

            if is_synthesis:
                if synthesis_seen:
                    logger.warning("检测到重复综合 Agent 定义，已忽略: %s", agent_data.get("agent_name"))
                    continue
                synthesis_seen = True
            else:
                dedupe_key = (role.lower(), dimension.lower())
                if dedupe_key in seen_analysis_keys:
                    logger.warning(
                        "检测到重复分析 Agent 定义，已忽略: role=%s, dimension=%s",
                        role,
                        dimension,
                    )
                    continue
                seen_analysis_keys.add(dedupe_key)

            bp = AgentBlueprint(
                agent_name=agent_data.get("agent_name", "未命名 Agent"),
                role=role,
                dimension=dimension,
                weight=float(agent_data.get("weight", 1.0)),
                system_prompt=agent_data.get("system_prompt", "你是一个分析专家。"),
                user_prompt_template=agent_data.get("user_prompt_template", "请分析以下内容：{content}"),
                dependencies=[],  # 先留空，后面填充
                group=agent_data.get("group", "default"),
                is_synthesis=is_synthesis,
                execution_kind="synthesis" if is_synthesis else "subagent",
                created_by="main_agent",
                invocation_kind="function_call",
                output_format=agent_data.get("output_format", "json"),
            )
            blueprints.append(bp)
            normalized_sources.append(agent_data)
            role_to_id.setdefault(bp.role, bp.agent_id)

        # 再填充依赖关系（将 role 转为 agent_id）
        for bp, agent_data in zip(blueprints, normalized_sources):
            dep_roles = agent_data.get("dependencies", [])
            dep_ids = [role_to_id[r] for r in dep_roles if r in role_to_id]
            if bp.is_synthesis and not dep_ids:
                dep_ids = [item.agent_id for item in blueprints if not item.is_synthesis]
            bp.dependencies = list(dict.fromkeys(dep_ids))

        reasoning = response.get("analysis_reasoning", "")
        logger.info("Master Agent 分析推理: %s", reasoning[:200])

        return blueprints or self._fallback_blueprints()

    def _fallback_blueprints(self) -> list[AgentBlueprint]:
        """当 LLM 无法生成有效蓝图时的降级方案。"""
        return [
            AgentBlueprint(
                agent_name="通用分析师",
                role="general_analyst",
                dimension="综合分析",
                weight=1.0,
                system_prompt="你是一个综合分析专家，请对给定内容进行全面评估。",
                user_prompt_template="请分析以下内容并返回 JSON 格式的评估结果：\n{content}",
                dependencies=[],
                group="analysis",
                is_synthesis=False,
                execution_kind="subagent",
                created_by="main_agent",
                invocation_kind="function_call",
            ),
        ]
