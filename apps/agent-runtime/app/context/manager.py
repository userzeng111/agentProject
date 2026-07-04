from __future__ import annotations

import hashlib
import json

from pydantic import ValidationError

from app.context.assembler import ContextAssembler
from app.context.cache_store import CacheStore, InMemoryCacheStore
from app.context.compressor import ReferenceCompressor
from app.context.models import (
    ContextBudget,
    ContextSnapshot,
    ModelContextProfile,
    ReferenceMaterial,
)
from app.observability import get_logger

logger = get_logger(__name__)


class ContextManager:
    def __init__(
        self,
        cache_store: CacheStore | None = None,
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
        try:
            cached_snapshot = self.cache_store.get(cache_key)
        except Exception as exc:
            logger.warning("读取上下文缓存失败: task_id=%s stage=%s error=%s", task_id, stage, exc)
            cached_snapshot = None

        if isinstance(cached_snapshot, dict):
            try:
                cached_snapshot = ContextSnapshot.model_validate(cached_snapshot)
            except ValidationError as exc:
                logger.warning("上下文缓存结构已失效，将重新构建: task_id=%s stage=%s error=%s", task_id, stage, exc)
                cached_snapshot = None
        elif cached_snapshot is not None and not isinstance(cached_snapshot, ContextSnapshot):
            logger.warning(
                "上下文缓存类型无效，将重新构建: task_id=%s stage=%s type=%s",
                task_id,
                stage,
                type(cached_snapshot).__name__,
            )
            cached_snapshot = None
        logger.debug(
            "上下文缓存查询: task_id=%s stage=%s model_id=%s cache_key=%s reference_count=%d memory_item_count=%d hit=%s",
            task_id,
            stage,
            model_profile.model_id,
            cache_key,
            len(references),
            len(memory_items or []),
            cached_snapshot is not None,
        )
        if cached_snapshot is not None:
            logger.info("上下文缓存命中: task_id=%s stage=%s cache_key=%s", task_id, stage, cache_key)
            packet = cached_snapshot.packet.model_copy(update={"task_id": task_id}, deep=True)
            return cached_snapshot.model_copy(
                update={
                    "task_id": task_id,
                    "cache_hit": True,
                    "packet": packet,
                },
                deep=True,
            )

        logger.debug("上下文缓存未命中，开始构建: task_id=%s stage=%s", task_id, stage)
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
        try:
            self.cache_store.set(cache_key, snapshot.model_dump(mode="json"))
        except Exception as exc:
            logger.warning("写入上下文缓存失败: task_id=%s stage=%s error=%s", task_id, stage, exc)
        logger.info(
            "上下文构建完成: task_id=%s stage=%s references=%d memory=%d tokens=%d/%d",
            task_id,
            stage,
            len(references),
            len(memory_items or []),
            packet.estimated_input_tokens,
            budget.available_input_tokens,
        )
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
