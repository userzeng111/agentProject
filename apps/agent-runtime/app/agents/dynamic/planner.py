"""
Planner Agent

通过 LLM 动态分析 Agent 团队，自主规划任务执行 DAG。
根据 Agent 的依赖关系和并行能力生成最优执行层级。
"""

from __future__ import annotations

import json
from app.observability import get_logger
from typing import Any

from app.agents.base import BaseAgent
from app.agents.dynamic.models import (
    AgentBlueprint,
    TaskDAG,
    TaskDAGEdge,
    TaskDAGNode,
)
from app.agents.dynamic.prompts import PLANNER_DAG_PROMPT, PLANNER_SYSTEM_PROMPT
from app.llm.gateway_client import OpenAICompatibleGatewayClient

logger = get_logger(__name__)


class PlannerAgent(BaseAgent):
    """
    规划 Agent — LLM 驱动的动态任务流规划器。

    职责：
    - 接收 AgentBlueprint 列表
    - 通过 LLM 分析依赖关系，生成 DAG
    - 确定并行层级和执行顺序
    """

    _skill_subdir = "planner"

    def __init__(
        self,
        gateway_client: OpenAICompatibleGatewayClient | None = None,
        default_model: str = "MiniMax-M2.7-highspeed",
    ) -> None:
        super().__init__(gateway_client=gateway_client)
        self.default_model = default_model

    def plan(
        self,
        blueprints: list[AgentBlueprint],
        task_context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> TaskDAG:
        """
        根据 Agent 蓝图列表生成任务 DAG。

        Args:
            blueprints: Agent 蓝图列表
            task_context: 任务上下文
            model: 使用的模型

        Returns:
            TaskDAG（有向无环图）
        """
        use_model = model or self.default_model

        if not blueprints:
            logger.warning("蓝图列表为空，返回空 DAG")
            return TaskDAG()

        # 如果只有一个 Agent，直接返回单节点 DAG
        if len(blueprints) == 1:
            bp = blueprints[0]
            node = TaskDAGNode(
                agent_id=bp.agent_id,
                layer=0,
                label=bp.agent_name,
            )
            return TaskDAG(
                nodes=[node],
                edges=[],
                execution_layers=[[bp.agent_id]],
            )

        # 构建 Agent 描述 JSON 传给 LLM
        agents_json = json.dumps(
            [
                {
                    "agent_id": bp.agent_id,
                    "agent_name": bp.agent_name,
                    "role": bp.role,
                    "dimension": bp.dimension,
                    "weight": bp.weight,
                    "dependencies": bp.dependencies,
                    "group": bp.group,
                    "is_synthesis": bp.is_synthesis,
                }
                for bp in blueprints
            ],
            ensure_ascii=False,
            indent=2,
        )

        user_prompt = PLANNER_DAG_PROMPT.format(agents_json=agents_json)

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        logger.info("Planner Agent 开始规划 %d 个 Agent 的执行 DAG", len(blueprints))

        # 调用 LLM 获取 DAG 规划
        response = self._call_llm_json(
            messages, use_model, max_retries=1,
            stage="planner_plan",
        )

        # 解析为 TaskDAG
        dag = self._parse_dag(response, blueprints)

        # 验证 DAG 有效性
        dag = self._validate_and_fix_dag(dag, blueprints)

        logger.info(
            "Planner Agent 规划完成: %d 个节点，%d 条边，%d 个执行层",
            len(dag.nodes),
            len(dag.edges),
            len(dag.execution_layers),
        )

        return dag

    def _parse_dag(
        self,
        response: dict[str, Any],
        blueprints: list[AgentBlueprint],
    ) -> TaskDAG:
        """将 LLM 响应解析为 TaskDAG。"""
        # 构建 agent_id -> blueprint 映射
        bp_map = {bp.agent_id: bp for bp in blueprints}

        nodes = []
        for node_data in response.get("nodes", []):
            agent_id = node_data.get("agent_id", "")
            if agent_id not in bp_map:
                logger.warning("DAG 节点引用了不存在的 agent_id: %s，跳过", agent_id)
                continue
            bp = bp_map[agent_id]
            nodes.append(TaskDAGNode(
                agent_id=agent_id,
                layer=int(node_data.get("layer", 0)),
                label=node_data.get("label", bp.agent_name),
            ))

        edges = []
        for edge_data in response.get("edges", []):
            from_node = edge_data.get("from_node", "")
            to_node = edge_data.get("to_node", "")
            if from_node and to_node:
                edges.append(TaskDAGEdge(
                    from_node=from_node,
                    to_node=to_node,
                    condition=edge_data.get("condition", "always"),
                ))

        execution_layers = response.get("execution_layers", [])

        reasoning = response.get("planning_reasoning", "")
        logger.info("Planner Agent 规划推理: %s", reasoning[:200])

        return TaskDAG(
            nodes=nodes,
            edges=edges,
            execution_layers=execution_layers,
        )

    def _validate_and_fix_dag(
        self,
        dag: TaskDAG,
        blueprints: list[AgentBlueprint],
    ) -> TaskDAG:
        """验证 DAG 完整性，修复缺失的节点和层级。"""
        existing_ids = {n.agent_id for n in dag.nodes}

        # 补充缺失的节点
        for bp in blueprints:
            if bp.agent_id not in existing_ids:
                # 根据依赖关系推算层级
                if bp.dependencies:
                    max_dep_layer = 0
                    for dep_id in bp.dependencies:
                        for n in dag.nodes:
                            if n.agent_id == dep_id:
                                max_dep_layer = max(max_dep_layer, n.layer + 1)
                                break
                    layer = max_dep_layer
                else:
                    layer = 0

                dag.nodes.append(TaskDAGNode(
                    agent_id=bp.agent_id,
                    layer=layer,
                    label=bp.agent_name,
                ))

        # 重建 execution_layers
        if not dag.execution_layers or not all(
            isinstance(layer, list) for layer in dag.execution_layers
        ):
            max_layer = max(n.layer for n in dag.nodes) if dag.nodes else 0
            dag.execution_layers = []
            for layer_idx in range(max_layer + 1):
                layer_agents = [n.agent_id for n in dag.nodes if n.layer == layer_idx]
                if layer_agents:
                    dag.execution_layers.append(layer_agents)

        # 补充缺失的边
        existing_edges = {(e.from_node, e.to_node) for e in dag.edges}
        for bp in blueprints:
            for dep_id in bp.dependencies:
                if (dep_id, bp.agent_id) not in existing_edges:
                    dag.edges.append(TaskDAGEdge(
                        from_node=dep_id,
                        to_node=bp.agent_id,
                    ))

        return dag
