from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return ceil(len(text) / 4)


class ModelContextProfile(BaseModel):
    model_id: str
    provider: str
    max_input_tokens: int
    max_output_tokens: int
    reserved_output_tokens: int = 2048
    supports_runtime_cache: bool = True
    profile_version: str = "v1"


class ContextBudget(BaseModel):
    max_input_tokens: int
    reserved_output_tokens: int
    available_input_tokens: int
    max_instruction_chars: int
    max_memory_chars: int
    max_reference_chars: int

    @classmethod
    def from_profile(cls, profile: ModelContextProfile) -> "ContextBudget":
        available_input_tokens = max(profile.max_input_tokens - profile.reserved_output_tokens, 0)
        instruction_tokens = max(int(available_input_tokens * 0.2), 16)
        memory_tokens = max(int(available_input_tokens * 0.2), 16)
        reference_tokens = max(available_input_tokens - instruction_tokens - memory_tokens, 16)
        return cls(
            max_input_tokens=profile.max_input_tokens,
            reserved_output_tokens=profile.reserved_output_tokens,
            available_input_tokens=available_input_tokens,
            max_instruction_chars=instruction_tokens * 4,
            max_memory_chars=memory_tokens * 4,
            max_reference_chars=reference_tokens * 4,
        )


class ReferenceMaterial(BaseModel):
    source_id: str
    title: str
    content: str
    priority: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompressedReference(BaseModel):
    source_id: str
    title: str
    priority: int
    content: str
    original_chars: int
    compressed_chars: int
    was_compressed: bool
    strategy: str


class ContextPacket(BaseModel):
    task_id: str
    stage: str
    instruction_text: str
    memory_text: str
    references_text: str
    assembled_text: str
    estimated_input_tokens: int
    truncated: bool = False


class ContextSnapshot(BaseModel):
    task_id: str
    stage: str
    model_id: str
    cache_key: str
    cache_hit: bool = False
    budget: ContextBudget
    packet: ContextPacket
    compressed_references: list[CompressedReference] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
