from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import sqlite3
import sys
import threading
from typing import Any, Protocol

from app.context.models import ReferenceMaterial
from app.rag.config import RagConfig


@dataclass(slots=True)
class RagHit:
    doc_id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RagSearchResult:
    query: str
    hits: list[RagHit]
    selected_contexts: list[str]
    error: str | None = None
    selected_hits: list[RagHit] = field(default_factory=list)


class SearchBackend(Protocol):
    def search(self, query: str, top_k: int) -> list[RagHit]:
        raise NotImplementedError


class EmbeddingProjectSearchBackend:
    def __init__(self, config: RagConfig) -> None:
        self.config = config
        self._embedder = None
        self._lock = threading.RLock()

    def search(self, query: str, top_k: int) -> list[RagHit]:
        if not self.config.faiss_index_path.exists():
            raise FileNotFoundError(f"未找到 FAISS 索引文件：{self.config.faiss_index_path}")
        if not self.config.sqlite_path.exists():
            raise FileNotFoundError(f"未找到 SQLite 元数据文件：{self.config.sqlite_path}")

        search_documents, faiss_store_cls, sqlite_store_cls = self._load_modules()
        faiss_store = faiss_store_cls.load(self.config.faiss_index_path)
        sqlite_store = sqlite_store_cls(
            connection=sqlite3.connect(self.config.sqlite_path),
            table_name="documents",
        )
        try:
            with self._lock:
                result = search_documents(
                    embedder=self._get_embedder(),
                    faiss_store=faiss_store,
                    sqlite_store=sqlite_store,
                    query=query,
                    top_k=top_k,
                )
        finally:
            sqlite_store.connection.close()

        return [
            RagHit(
                doc_id=str(hit.doc_id),
                content=hit.content,
                score=hit.score,
                metadata=dict(hit.metadata or {}),
            )
            for hit in result.hits
        ]

    def _get_embedder(self):
        with self._lock:
            if self._embedder is not None:
                return self._embedder

            self._ensure_import_path()
            module = importlib.import_module("embedder.llama_cpp_embedder")
            embedder_cls = getattr(module, "LlamaCppEmbedder")
            self._embedder = embedder_cls(
                model_path=self.config.gguf_path,
                model_name=self.config.model_name,
                n_ctx=self.config.n_ctx,
                n_threads=self.config.n_threads,
                n_batch=self.config.n_batch,
            )
            return self._embedder

    def _load_modules(self):
        self._ensure_import_path()
        search_module = importlib.import_module("pipeline.search")
        faiss_store_module = importlib.import_module("storage.faiss_store")
        sqlite_store_module = importlib.import_module("storage.sqlite_store")
        return (
            getattr(search_module, "search_documents"),
            getattr(faiss_store_module, "FaissStore"),
            getattr(sqlite_store_module, "SQLiteStore"),
        )

    def _ensure_import_path(self) -> None:
        root = str(self.config.embedding_project_root)
        if root not in sys.path:
            sys.path.insert(0, root)


def _jaccard_similarity(a: str, b: str) -> float:
    """计算两个字符串基于空白分词的 Jaccard 相似度。"""
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


class RagService:
    def __init__(
        self,
        config: RagConfig,
        search_backend: SearchBackend | None = None,
        *,
        score_threshold: float = 0.3,
        dedup_jaccard_threshold: float = 0.85,
    ) -> None:
        self.config = config
        self.search_backend = search_backend or EmbeddingProjectSearchBackend(config)
        self.score_threshold = score_threshold
        self.dedup_jaccard_threshold = dedup_jaccard_threshold

    def is_ready(self) -> bool:
        return self.config.faiss_index_path.exists() and self.config.sqlite_path.exists()

    def readiness_error(self) -> str:
        return "小说RAG知识库尚未构建，请先前往设置页完成索引构建。"

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        max_context_chars: int | None = None,
    ) -> RagSearchResult:
        normalized_query = query.strip()
        if not self.config.enabled or not normalized_query:
            return RagSearchResult(
                query=normalized_query,
                hits=[],
                selected_contexts=[],
                selected_hits=[],
                error=None,
            )

        try:
            hits = self.search_backend.search(normalized_query, top_k or self.config.top_k)
        except Exception as exc:
            return RagSearchResult(
                query=normalized_query,
                hits=[],
                selected_contexts=[],
                selected_hits=[],
                error=str(exc),
            )

        hits = self._filter_and_dedup_hits(hits)
        selected_hits = self._select_hits(hits, max_context_chars or self.config.max_context_chars)
        return RagSearchResult(
            query=normalized_query,
            hits=hits,
            selected_contexts=[hit.content for hit in selected_hits],
            selected_hits=selected_hits,
            error=None,
        )

    def search_for_story_outline(self, *, spec: dict[str, Any]) -> RagSearchResult:
        query = " ".join(
            item.strip()
            for item in [
                str(spec.get("prompt") or ""),
                str(spec.get("genre") or ""),
                str(spec.get("style") or ""),
                str(spec.get("title_hint") or ""),
            ]
            if item and item.strip()
        )
        return self.search(query)

    def search_for_story_chapter(
        self,
        *,
        spec: dict[str, Any],
        story_plan: dict[str, Any] | None,
        batch_index: int,
        batch_size: int = 2,
        completed_chapters: list[dict[str, Any]],
    ) -> RagSearchResult:
        plan = story_plan or {}
        chapter_plan = [item for item in (plan.get("chapter_plan") or []) if isinstance(item, dict)]
        effective_batch_size = max(batch_size, 1)
        current = chapter_plan[batch_index : batch_index + effective_batch_size]
        current_summary = " ".join(
            f"第{item.get('number')}章 {item.get('title')} {item.get('goal')}"
            for item in current
        )
        completed_summary = " ".join(str(item.get("summary") or "") for item in completed_chapters[-2:])
        query = " ".join(
            item.strip()
            for item in [
                str(plan.get("working_title") or ""),
                str(plan.get("logline") or ""),
                str(spec.get("prompt") or ""),
                current_summary,
                completed_summary,
            ]
            if item and item.strip()
        )
        return self.search(query)

    def augment_chat_messages(
        self,
        messages: list[dict[str, str]],
        top_k: int | None = None,
    ) -> tuple[list[dict[str, str]], RagSearchResult]:
        latest_user_message = next(
            (item.get("content", "") for item in reversed(messages) if item.get("role") == "user"),
            "",
        )
        result = self.search(latest_user_message, top_k=top_k)
        if not result.selected_contexts:
            return messages, result

        rag_message = {
            "role": "system",
            "content": self._build_chat_context_message(result),
        }
        if messages and messages[0].get("role") == "system":
            merged_system = dict(messages[0])
            merged_system["content"] = f"{messages[0].get('content', '').rstrip()}\n\n{rag_message['content']}".strip()
            return [merged_system, *messages[1:]], result
        return [rag_message, *messages], result

    def build_reference_materials(
        self,
        result: RagSearchResult,
        *,
        prefix: str,
        start_priority: int = 40,
    ) -> list[ReferenceMaterial]:
        references: list[ReferenceMaterial] = []
        for index, hit in enumerate(result.selected_hits):
            title = (
                str(hit.metadata.get("source_path") or "").strip()
                or str(hit.metadata.get("title") or "").strip()
                or f"{prefix}片段{index + 1}"
            )
            references.append(
                ReferenceMaterial(
                    source_id=f"rag-{prefix}-{hit.doc_id}",
                    title=title,
                    content=hit.content,
                    priority=max(start_priority - index, 1),
                    metadata={
                        "score": hit.score,
                        **hit.metadata,
                    },
                )
            )
        return references

    def _filter_and_dedup_hits(self, hits: list[RagHit]) -> list[RagHit]:
        """按 score 阈值过滤，并用 Jaccard 相似度去重（保留 score 更高的）。"""
        threshold = getattr(self, "score_threshold", 0.3)
        dedup_threshold = getattr(self, "dedup_jaccard_threshold", 0.85)

        filtered = [hit for hit in hits if hit.score >= threshold]
        filtered.sort(key=lambda h: h.score, reverse=True)

        deduped: list[RagHit] = []
        for hit in filtered:
            if any(
                _jaccard_similarity(hit.content, existing.content) >= dedup_threshold
                for existing in deduped
            ):
                continue
            deduped.append(hit)
        return deduped

    def _select_hits(self, hits: list[RagHit], max_context_chars: int) -> list[RagHit]:
        selected: list[RagHit] = []
        total_chars = 0
        for hit in hits:
            length = len(hit.content)
            if total_chars + length > max_context_chars:
                continue
            selected.append(hit)
            total_chars += length
        return selected

    def _build_chat_context_message(self, result: RagSearchResult) -> str:
        blocks = []
        for index, hit in enumerate(result.selected_hits, start=1):
            title = (
                str(hit.metadata.get("source_path") or "").strip()
                or str(hit.metadata.get("title") or "").strip()
                or f"片段 {index}"
            )
            blocks.append(f"[{title}]\n{hit.content}")
        return (
            "你可以优先参考以下检索到的资料回答用户问题；如果资料不足，请明确说明资料不足，不要编造。\n\n"
            + "\n\n".join(blocks)
        )
