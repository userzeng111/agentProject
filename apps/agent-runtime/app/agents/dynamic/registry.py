"""
Agent 注册表

管理已创建 DynamicAgent 的生命周期：注册、查询、状态更新、清理。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.agents.dynamic.models import (
    AgentBlueprint,
    DynamicAgent,
    DynamicAgentStatus,
)

logger = logging.getLogger(__name__)


class AgentRegistry:
    """管理已创建 Agent 的生命周期。"""

    def __init__(self) -> None:
        self._agents: dict[str, DynamicAgent] = {}
        self._lock = threading.Lock()

    def register(self, agent: DynamicAgent) -> None:
        """注册一个 Agent 到注册表。"""
        with self._lock:
            self._agents[agent.id] = agent
            logger.info("注册 Agent: %s（ID: %s）", agent.blueprint.agent_name, agent.id)

    def register_batch(self, agents: list[DynamicAgent]) -> None:
        """批量注册 Agent。"""
        with self._lock:
            for agent in agents:
                self._agents[agent.id] = agent
            logger.info("批量注册 %d 个 Agent", len(agents))

    def get(self, agent_id: str) -> DynamicAgent | None:
        """按 ID 获取 Agent。"""
        with self._lock:
            return self._agents.get(agent_id)

    def get_by_role(self, role: str) -> list[DynamicAgent]:
        """按角色获取所有 Agent。"""
        with self._lock:
            return [a for a in self._agents.values() if a.blueprint.role == role]

    def get_by_group(self, group: str) -> list[DynamicAgent]:
        """按分组获取所有 Agent。"""
        with self._lock:
            return [a for a in self._agents.values() if a.blueprint.group == group]

    def get_by_status(self, status: DynamicAgentStatus) -> list[DynamicAgent]:
        """按状态获取所有 Agent。"""
        with self._lock:
            return [a for a in self._agents.values() if a.status == status]

    def update_status(self, agent_id: str, status: DynamicAgentStatus) -> None:
        """更新 Agent 状态。"""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent:
                agent.status = status

    @property
    def all_agents(self) -> list[DynamicAgent]:
        """获取所有已注册 Agent。"""
        with self._lock:
            return list(self._agents.values())

    @property
    def size(self) -> int:
        """已注册 Agent 数量。"""
        with self._lock:
            return len(self._agents)

    def clear(self) -> None:
        """清空注册表。"""
        with self._lock:
            self._agents.clear()
            logger.info("注册表已清空")

    def summary(self) -> dict[str, Any]:
        """返回注册表摘要信息。"""
        with self._lock:
            status_counts: dict[str, int] = {}
            for agent in self._agents.values():
                status_key = agent.status.value
                status_counts[status_key] = status_counts.get(status_key, 0) + 1

            return {
                "total": len(self._agents),
                "by_status": status_counts,
                "agents": [
                    {
                        "id": a.id,
                        "name": a.blueprint.agent_name,
                        "role": a.blueprint.role,
                        "status": a.status.value,
                        "group": a.blueprint.group,
                    }
                    for a in self._agents.values()
                ],
            }
