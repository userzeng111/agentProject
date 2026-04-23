"""
动态 Agent 数据模型

定义动态 Agent 系统的全部数据结构：
- AgentBlueprint: Master Agent 输出的 Agent 蓝图
- DynamicAgent: 可执行 Agent 实例
- TaskDAG: Planner Agent 输出的任务有向无环图
- TaskExecutionResult: 单个 Agent 的执行结果
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


# ─────────────────────────────────────────────
# Agent 蓝图（Master Agent 输出）
# ─────────────────────────────────────────────


class AgentBlueprint(BaseModel):
    """Agent 蓝图 — Master Agent 通过 LLM 分析任务后生成的角色定义。"""

    agent_id: str = Field(default_factory=lambda: _new_id("bp"))
    agent_name: str  # 显示名称（如"结构分析师"）
    role: str  # 角色标签（如 structure/quality/synthesis）
    dimension: str  # 评估维度名称
    weight: float = 1.0  # 权重（0-1）
    system_prompt: str  # 系统 prompt（由 LLM 生成）
    user_prompt_template: str  # 用户 prompt 模板（含 {variable} 占位符）
    dependencies: list[str] = Field(default_factory=list)  # 依赖的 agent_id
    group: str = ""  # 分组标识（同组可并行）
    is_synthesis: bool = False  # 是否为综合决策 Agent
    execution_kind: str = "subagent"  # subagent | synthesis
    created_by: str = "main_agent"  # 只有主 Agent 可以派发蓝图
    invocation_kind: str = "function_call"  # 子执行单元的调用方式
    output_format: str = "json"  # json | text


# ─────────────────────────────────────────────
# 动态 Agent 实例
# ─────────────────────────────────────────────


class DynamicAgentStatus(str, Enum):
    """动态 Agent 生命周期状态。"""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DynamicAgent(BaseModel):
    """动态 Agent 实例 — 可直接执行的 Agent。"""

    id: str = Field(default_factory=lambda: _new_id("agent"))
    blueprint: AgentBlueprint
    status: DynamicAgentStatus = DynamicAgentStatus.IDLE
    output: TaskExecutionResult | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_ms(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return None


# ─────────────────────────────────────────────
# 任务 DAG（Planner Agent 输出）
# ─────────────────────────────────────────────


class TaskDAGNode(BaseModel):
    """DAG 节点 — 一个执行单元，关联一个 DynamicAgent。"""

    node_id: str = Field(default_factory=lambda: _new_id("node"))
    agent_id: str  # 对应 DynamicAgent.id
    layer: int = 0  # 执行层级（同层可并行，层级从小到大串行）
    label: str = ""  # 节点标签（用于日志）


class TaskDAGEdge(BaseModel):
    """DAG 边 — 节点间依赖关系。"""

    from_node: str  # 上游 node_id
    to_node: str  # 下游 node_id
    condition: str = "always"  # always | on_success | on_failure


class TaskDAG(BaseModel):
    """任务有向无环图 — Planner Agent 的输出。"""

    dag_id: str = Field(default_factory=lambda: _new_id("dag"))
    nodes: list[TaskDAGNode] = Field(default_factory=list)
    edges: list[TaskDAGEdge] = Field(default_factory=list)
    execution_layers: list[list[str]] = Field(default_factory=list)  # 按层级排列的 node_id
    metadata: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────
# 执行结果
# ─────────────────────────────────────────────


class TaskExecutionResult(BaseModel):
    """单个 Agent 的执行结果。"""

    agent_id: str
    agent_name: str
    role: str
    dimension: str
    weight: float = 1.0
    execution_kind: str = "subagent"
    parent_agent_id: str | None = None
    created_by: str = "main_agent"
    invocation_kind: str = "function_call"
    score: float = 0.0
    issues: list[dict[str, Any] | str] = Field(default_factory=list)
    warnings: list[dict[str, Any] | str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    reasoning: str = ""
    raw_response: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_ms(self) -> int | None:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return None

    @property
    def is_success(self) -> bool:
        return self.error is None


# ─────────────────────────────────────────────
# 编排汇总结果
# ─────────────────────────────────────────────


class OrchestrationResult(BaseModel):
    """整个动态编排的最终汇总结果。"""

    orchestration_id: str = Field(default_factory=lambda: _new_id("orch"))
    task_description: str = ""
    agents_created: int = 0
    agents_succeeded: int = 0
    agents_failed: int = 0
    agent_results: list[TaskExecutionResult] = Field(default_factory=list)
    synthesis_result: TaskExecutionResult | None = None
    overall_score: float = 0.0
    overall_approved: bool = False
    dag_snapshot: TaskDAG | None = None
    blueprint_snapshot: list[AgentBlueprint] = Field(default_factory=list)
    total_duration_ms: int = 0
    created_at: datetime = Field(default_factory=_utc_now)

    model_config = {"arbitrary_types_allowed": True}
