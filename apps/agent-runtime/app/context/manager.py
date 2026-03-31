from __future__ import annotations

import hashlib
import json

from app.context.assembler import ContextAssembler
from app.context.cache_store import InMemoryCacheStore
from app.context.compressor import ReferenceCompressor
from app.context.models import (
    ContextBudget,
    ContextSnapshot,
    ModelContextProfile,
    ReferenceMaterial,
)


class ContextManager:
    def __init__(
        self,
        cache_store: InMemoryCacheStore | None = None,
        compressor: ReferenceCompressor | None = None,
        assembler: ContextAssembler | None = None,
    ) -> None:
        self.cache_store = cache_store or InMemoryCacheStore()
        self.compressor = compressor or ReferenceCompressor()
        self.assembler = assembler or ContextAssembler()

    def build_snapshot(
        self,
        task_id: str,
        stage: str,
        instruction: str,
        model_profile: ModelContextProfile,
        references: list[ReferenceMaterial],
        memory_items: list[str] | None = None,
    ) -> ContextSnapshot:
        budget = ContextBudget.from_profile(model_profile)
        cache_key = self._build_cache_key(
            task_id=task_id,
            stage=stage,
            instruction=instruction,
            model_profile=model_profile,
            references=references,
            memory_items=memory_items or [],
        )
        cached_snapshot = self.cache_store.get(cache_key)
        if isinstance(cached_snapshot, dict):
            cached_snapshot = ContextSnapshot.model_validate(cached_snapshot)
        if cached_snapshot is not None:
            packet = cached_snapshot.packet.model_copy(update={"task_id": task_id}, deep=True)
            return cached_snapshot.model_copy(
                update={
                    "task_id": task_id,
                    "cache_hit": True,
                    "packet": packet,
                },
                deep=True,
            )

        compressed_references = self.compressor.compress_references(references, budget.max_reference_chars)
        packet = self.assembler.assemble(
            task_id=task_id,
            stage=stage,
            budget=budget,
            instruction=instruction,
            compressed_references=compressed_references,
            memory_items=memory_items,
        )
        snapshot = ContextSnapshot(
            task_id=task_id,
            stage=stage,
            model_id=model_profile.model_id,
            cache_key=cache_key,
            cache_hit=False,
            budget=budget,
            packet=packet,
            compressed_references=compressed_references,
            diagnostics={
                "reference_count": len(references),
                "memory_item_count": len(memory_items or []),
                "within_budget": packet.estimated_input_tokens <= budget.available_input_tokens,
            },
        )
        self.cache_store.set(cache_key, snapshot.model_dump(mode="json"))
        return snapshot

    def _build_cache_key(
        self,
        task_id: str,
        stage: str,
        instruction: str,
        model_profile: ModelContextProfile,
        references: list[ReferenceMaterial],
        memory_items: list[str],
    ) -> str:
        payload = {
            "stage": stage,
            "instruction": instruction,
            "model_profile": model_profile.model_dump(mode="json"),
            "references": [item.model_dump(mode="json") for item in references],
            "memory_items": memory_items,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return f"context:{digest}"
