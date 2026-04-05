"""
Agent 标准化模块

提供 Skill 驱动的 Agent 架构：
- SkillConfig: Skill 配置数据模型
- SkillLoader: YAML Skill 加载器
- BaseAgent: Agent 基类
"""

from app.agents.base import BaseAgent
from app.agents.loader import SkillLoadError, SkillLoader
from app.agents.models import SkillConfig

__all__ = [
    "BaseAgent",
    "SkillConfig",
    "SkillLoadError",
    "SkillLoader",
]
