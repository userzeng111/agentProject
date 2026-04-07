"""
动态 Agent 创建与任务分配系统

提供 LLM 驱动的动态 Agent 创建、任务规划和执行编排能力。
与现有硬编码架构并行运行，验证一致后替换。
"""

from app.agents.dynamic.factory import AgentFactory
from app.agents.dynamic.master import MasterAgent
from app.agents.dynamic.models import (
    AgentBlueprint,
    DynamicAgent,
    DynamicAgentStatus,
    TaskDAG,
    TaskDAGEdge,
    TaskDAGNode,
    TaskExecutionResult,
)
from app.agents.dynamic.orchestrator import TaskOrchestrator
from app.agents.dynamic.planner import PlannerAgent
from app.agents.dynamic.registry import AgentRegistry

__all__ = [
    "AgentBlueprint",
    "AgentFactory",
    "AgentRegistry",
    "DynamicAgent",
    "DynamicAgentStatus",
    "MasterAgent",
    "PlannerAgent",
    "TaskDAG",
    "TaskDAGEdge",
    "TaskDAGNode",
    "TaskExecutionResult",
    "TaskOrchestrator",
]
