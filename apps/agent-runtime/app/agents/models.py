"""
Agent Skill 数据模型

定义 Skill YAML 配置文件对应的结构化模型。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PromptConfig(BaseModel):
    """Prompt 配置：system + human 消息模板。"""

    system: str
    human: str


class ModelConfig(BaseModel):
    """模型配置。"""

    default: str = ""
    fallback: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class VariableDef(BaseModel):
    """输入变量定义。"""

    name: str
    required: bool = True
    default: Any = None
    description: str = ""


class OutputConfig(BaseModel):
    """输出格式配置。"""

    format: str = "json"  # json | text
    schema_description: str = ""


class RuntimeConfig(BaseModel):
    """运行时配置。"""

    supports_streaming: bool = True
    supports_cache: bool = True
    retry_count: int = 1
    retry_prompt: str = ""


class ReviewMeta(BaseModel):
    """审核类 Agent 的额外元信息。"""

    dimension: str = ""
    weight: float = 1.0
    review_group: str = ""  # outline | chapter | verification
    role: str = ""


class SkillConfig(BaseModel):
    """完整的 Skill 配置文件模型。"""

    skill_id: str
    skill_name: str
    skill_type: str  # writing | review | review_synthesis
    version: str = "1.0.0"
    description: str = ""

    model: ModelConfig = Field(default_factory=ModelConfig)
    prompt: PromptConfig
    input_variables: list[VariableDef] = Field(default_factory=list)
    output: OutputConfig = Field(default_factory=OutputConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    review: ReviewMeta | None = None  # 仅审核类 Agent

    # 运行时附加字段（不来自 YAML）
    source_path: Path | None = None
