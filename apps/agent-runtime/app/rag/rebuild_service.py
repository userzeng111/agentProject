from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from app.observability import get_logger
from app.observability.performance import log_performance
from app.rag.config import RagConfig

logger = get_logger(__name__)


@dataclass(slots=True)
class IndexedDocument:
    doc_id: int
    content: str
    metadata: dict[str, Any]
    source_key: str = ""
    source_hash: str = ""


@dataclass(slots=True)
class SourceDocumentGroup:
    source_key: str
    source_type: str
    source_path: str
    source_hash: str
    documents: list[IndexedDocument]


@dataclass(slots=True)
class ExistingCorpusState:
    source_hashes: dict[str, str]
    source_document_ids: dict[str, list[int]]
    document_count: int
    vector_dimension: int


class FullRebuildRequired(RuntimeError):
    """增量同步无法安全执行时，要求调用方显式发起全量重建。"""

    def __init__(self, reason: str, *, reason_code: str = "index_incompatible") -> None:
        super().__init__(reason)
        self.reason = reason
        self.reason_code = reason_code


class NovelCorpusBuilder(Protocol):
    def build(self, documents: list[IndexedDocument], config: RagConfig) -> dict[str, object]:
        raise NotImplementedError


class EmbeddingProjectNovelCorpusBuilder:
    """使用 embeddingProject 构建可增量同步的小说语料索引。"""

    _MANIFEST_SCHEMA_VERSION = "1"
    _CHUNK_PROFILE_VERSION = "example:2400/240|archived_final:1800/180|archived_outline:1200/120"
    _DELETE_BATCH_SIZE = 500

    def build(self, documents: list[IndexedDocument], config: RagConfig) -> dict[str, object]:
        """兼容旧调用方的自动同步入口。

        新的双模式作业只能调用 :meth:`build_with_mode`。保留这里是为了避免
        旧的内部脚本在升级时立刻失效；它会沿用过去的“必要时全量构建”语义。
        """
        return self.build_with_mode(documents, config, mode="auto")

    def build_with_mode(
        self,
        documents: list[IndexedDocument],
        config: RagConfig,
        *,
        mode: str,
    ) -> dict[str, object]:
        if mode not in {"auto", "incremental", "full"}:
            raise ValueError("RAG 同步模式必须是 incremental、full 或 auto。")
        config.library_dir.mkdir(parents=True, exist_ok=True)
        components = self._load_components(config)
        source_groups = self._group_documents(documents)
        compatibility_fingerprint = self._compatibility_fingerprint(config)

        state: ExistingCorpusState | None = None
        state_warning: str | None = None
        if mode != "full":
            state, state_warning = self._load_existing_state(
                config=config,
                faiss_cls=components[1],
                compatibility_fingerprint=compatibility_fingerprint,
            )
            if state is None and mode == "incremental":
                raise FullRebuildRequired(
                    state_warning or "当前索引不存在，必须先执行一次全量重建。",
                    reason_code=self._full_rebuild_reason_code(config),
                )

        if state is not None:
            added_keys, changed_keys, deleted_keys = self._diff_sources(source_groups, state)
            if mode != "full" and not added_keys and not changed_keys and not deleted_keys:
                return {
                    "indexed_documents": state.document_count,
                    "output_dir": str(config.library_dir),
                    "sync_mode": "noop",
                    "embedded_documents": 0,
                    "reused_documents": state.document_count,
                    "added_sources": 0,
                    "changed_sources": 0,
                    "deleted_sources": 0,
                    "removed_documents": 0,
                    "warnings": [],
                }
        else:
            added_keys = set(source_groups)
            changed_keys: set[str] = set()
            deleted_keys: set[str] = set()

        embedder = self._create_embedder(components[0], config)
        vector_dimension = int(embedder.dimension)
        if state is not None and state.vector_dimension != vector_dimension:
            state_warning = "现有索引向量维度与当前模型不一致，必须执行全量重建。"
            if mode == "incremental":
                raise FullRebuildRequired(state_warning, reason_code="vector_dimension_changed")
            state = None
            added_keys = set(source_groups)
            changed_keys = set()
            deleted_keys = set()

        self._validate_document_ids(source_groups)
        staging_dir = Path(tempfile.mkdtemp(prefix=".rag-sync-", dir=config.library_dir))
        staged_faiss_path = staging_dir / "index.faiss"
        staged_sqlite_path = staging_dir / "metadata.sqlite3"
        try:
            if state is None:
                faiss_store, indexed_documents = self._build_full_staging(
                    staged_sqlite_path=staged_sqlite_path,
                    documents=documents,
                    source_groups=source_groups,
                    compatibility_fingerprint=compatibility_fingerprint,
                    vector_dimension=vector_dimension,
                    components=components,
                    embedder=embedder,
                )
                sync_mode = "full"
                embedded_documents = len(documents)
                reused_documents = 0
                removed_documents = 0
                added_source_count = len(source_groups)
                changed_source_count = 0
                deleted_source_count = 0
            else:
                faiss_store, indexed_documents, removed_documents = self._build_incremental_staging(
                    source_sqlite_path=config.sqlite_path,
                    staged_sqlite_path=staged_sqlite_path,
                    source_faiss_path=config.faiss_index_path,
                    source_groups=source_groups,
                    state=state,
                    added_keys=added_keys,
                    changed_keys=changed_keys,
                    deleted_keys=deleted_keys,
                    components=components,
                    embedder=embedder,
                )
                sync_mode = "incremental"
                embedded_documents = sum(
                    len(source_groups[key].documents) for key in added_keys | changed_keys
                )
                reused_documents = indexed_documents - embedded_documents
                added_source_count = len(added_keys)
                changed_source_count = len(changed_keys)
                deleted_source_count = len(deleted_keys)

            faiss_store.save(staged_faiss_path)
            self._validate_staged_corpus(
                staged_sqlite_path=staged_sqlite_path,
                faiss_store=faiss_store,
                expected_documents=indexed_documents,
            )
            self._publish_staged_artifacts(
                config=config,
                staged_faiss_path=staged_faiss_path,
                staged_sqlite_path=staged_sqlite_path,
                staging_dir=staging_dir,
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        return {
            "indexed_documents": indexed_documents,
            "output_dir": str(config.library_dir),
            "sync_mode": sync_mode,
            "embedded_documents": embedded_documents,
            "reused_documents": reused_documents,
            "added_sources": added_source_count,
            "changed_sources": changed_source_count,
            "deleted_sources": deleted_source_count,
            "removed_documents": removed_documents,
            "warnings": [state_warning] if state_warning else [],
        }

    def plan(
        self,
        documents: list[IndexedDocument],
        config: RagConfig,
        *,
        mode: str,
    ) -> dict[str, object]:
        """只读取来源和索引清单，绝不创建 embedder 或写入索引。"""
        if mode not in {"incremental", "full"}:
            raise ValueError("RAG 同步模式必须是 incremental 或 full。")
        source_groups = self._group_documents(documents)
        if mode == "full":
            return {
                "sync_mode": "full",
                "scanned_files": len(source_groups),
                "indexed_documents": len(documents),
                "embedded_documents": len(documents),
                "reused_documents": 0,
                "added_sources": len(source_groups),
                "changed_sources": 0,
                "deleted_sources": 0,
                "removed_documents": 0,
            }

        components = self._load_components(config)
        state, warning = self._load_existing_state(
            config=config,
            faiss_cls=components[1],
            compatibility_fingerprint=self._compatibility_fingerprint(config),
        )
        if state is None:
            raise FullRebuildRequired(
                warning or "当前索引不存在，必须先执行一次全量重建。",
                reason_code=self._full_rebuild_reason_code(config),
            )
        added_keys, changed_keys, deleted_keys = self._diff_sources(source_groups, state)
        embedded_documents = sum(
            len(source_groups[key].documents) for key in added_keys | changed_keys
        )
        removed_documents = sum(
            len(state.source_document_ids.get(key, [])) for key in changed_keys | deleted_keys
        )
        return {
            "sync_mode": "noop" if not (added_keys or changed_keys or deleted_keys) else "incremental",
            "scanned_files": len(source_groups),
            "indexed_documents": state.document_count - removed_documents + embedded_documents,
            "embedded_documents": embedded_documents,
            "reused_documents": state.document_count - removed_documents,
            "added_sources": len(added_keys),
            "changed_sources": len(changed_keys),
            "deleted_sources": len(deleted_keys),
            "removed_documents": removed_documents,
        }

    def _full_rebuild_reason_code(self, config: RagConfig) -> str:
        if not config.faiss_index_path.exists() and not config.sqlite_path.exists():
            return "index_missing"
        if not config.faiss_index_path.exists() or not config.sqlite_path.exists():
            return "index_incomplete"
        return "index_incompatible"

    def _load_components(self, config: RagConfig) -> tuple[Any, Any, Any, Any, Any]:
        self._ensure_import_path(config)
        embedder_module = importlib.import_module("embedder.llama_cpp_embedder")
        faiss_module = importlib.import_module("storage.faiss_store")
        sqlite_module = importlib.import_module("storage.sqlite_store")
        pipeline_module = importlib.import_module("pipeline.indexing")
        schemas_module = importlib.import_module("schemas")
        return (
            getattr(embedder_module, "LlamaCppEmbedder"),
            getattr(faiss_module, "FaissStore"),
            getattr(sqlite_module, "SQLiteStore"),
            getattr(pipeline_module, "index_documents"),
            getattr(schemas_module, "DocumentInput"),
        )

    def _create_embedder(self, embedder_cls: Any, config: RagConfig) -> Any:
        return embedder_cls(
            model_path=config.gguf_path,
            model_name=config.model_name,
            n_ctx=config.n_ctx,
            n_threads=config.n_threads,
            n_batch=config.n_batch,
        )

    def _group_documents(self, documents: list[IndexedDocument]) -> dict[str, SourceDocumentGroup]:
        groups: dict[str, SourceDocumentGroup] = {}
        for document in documents:
            source_type = str(document.metadata.get("source_type") or "unknown")
            source_path = str(document.metadata.get("source_path") or f"document/{document.doc_id}")
            source_key = document.source_key or f"{source_type}:{source_path}"
            source_hash = document.source_hash or hashlib.sha256(
                document.content.encode("utf-8")
            ).hexdigest()
            group = groups.get(source_key)
            if group is None:
                groups[source_key] = SourceDocumentGroup(
                    source_key=source_key,
                    source_type=source_type,
                    source_path=source_path,
                    source_hash=source_hash,
                    documents=[document],
                )
                continue
            if group.source_hash != source_hash:
                raise ValueError(f"来源 {source_key} 的内容指纹不一致，无法执行增量同步。")
            group.documents.append(document)
        return groups

    def _compatibility_fingerprint(self, config: RagConfig) -> str:
        model_signature: dict[str, object] = {"path": str(config.gguf_path)}
        try:
            stat_result = config.gguf_path.stat()
            model_signature.update(
                {
                    "size_bytes": stat_result.st_size,
                    "mtime_ns": stat_result.st_mtime_ns,
                }
            )
        except OSError:
            model_signature["missing"] = True
        payload = {
            "manifest_schema_version": self._MANIFEST_SCHEMA_VERSION,
            "chunk_profile_version": self._CHUNK_PROFILE_VERSION,
            "doc_id_scheme": "source-path-chunk-index-v1",
            "runtime": config.runtime,
            "namespace": config.namespace,
            "model_name": config.model_name,
            "model": model_signature,
            "n_ctx": config.n_ctx,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _load_existing_state(
        self,
        *,
        config: RagConfig,
        faiss_cls: Any,
        compatibility_fingerprint: str,
    ) -> tuple[ExistingCorpusState | None, str | None]:
        faiss_exists = config.faiss_index_path.exists()
        sqlite_exists = config.sqlite_path.exists()
        if not faiss_exists and not sqlite_exists:
            return None, None
        if not faiss_exists or not sqlite_exists:
            return None, "现有索引文件不完整，已安全执行全量构建。"

        required_tables = {"rag_corpus_meta", "rag_sources", "rag_source_documents"}
        try:
            with sqlite3.connect(self._readonly_sqlite_uri(config.sqlite_path), uri=True) as connection:
                table_names = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                if not required_tables.issubset(table_names):
                    return None, "现有索引缺少增量清单，已安全执行首次全量构建。"

                metadata = {
                    str(key): str(value)
                    for key, value in connection.execute(
                        "SELECT key, value FROM rag_corpus_meta"
                    ).fetchall()
                }
                if metadata.get("schema_version") != self._MANIFEST_SCHEMA_VERSION:
                    return None, "现有索引清单版本不兼容，已安全执行全量构建。"
                if metadata.get("compatibility_fingerprint") != compatibility_fingerprint:
                    return None, "索引配置或模型已变化，已安全执行全量构建。"
                try:
                    vector_dimension = int(metadata["vector_dimension"])
                except (KeyError, TypeError, ValueError):
                    return None, "现有索引缺少向量维度信息，已安全执行全量构建。"

                source_hashes = {
                    str(source_key): str(source_hash)
                    for source_key, source_hash in connection.execute(
                        "SELECT source_key, source_hash FROM rag_sources"
                    ).fetchall()
                }
                source_document_ids = {source_key: [] for source_key in source_hashes}
                for source_key, doc_id in connection.execute(
                    "SELECT source_key, doc_id FROM rag_source_documents ORDER BY source_key, doc_id"
                ).fetchall():
                    source_document_ids.setdefault(str(source_key), []).append(int(doc_id))

                document_count = int(
                    connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] or 0
                )
                mapping_count, distinct_mapping_count = connection.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT doc_id) FROM rag_source_documents"
                ).fetchone()
                if int(mapping_count or 0) != document_count or int(
                    distinct_mapping_count or 0
                ) != document_count:
                    return None, "现有索引清单与文档数量不一致，已安全执行全量构建。"

            faiss_store = faiss_cls.load(config.faiss_index_path)
            faiss_count = int(getattr(faiss_store.index, "ntotal", 0))
            if faiss_count != document_count:
                return None, "现有 FAISS 与 SQLite 数量不一致，已安全执行全量构建。"
        except Exception as exc:
            logger.warning("读取增量 RAG 清单失败，改为全量构建: error=%s", exc)
            return None, "现有索引无法验证，已安全执行全量构建。"

        return (
            ExistingCorpusState(
                source_hashes=source_hashes,
                source_document_ids=source_document_ids,
                document_count=document_count,
                vector_dimension=vector_dimension,
            ),
            None,
        )

    def _diff_sources(
        self,
        source_groups: dict[str, SourceDocumentGroup],
        state: ExistingCorpusState,
    ) -> tuple[set[str], set[str], set[str]]:
        current_keys = set(source_groups)
        previous_keys = set(state.source_hashes)
        added_keys = current_keys - previous_keys
        deleted_keys = previous_keys - current_keys
        changed_keys = {
            source_key
            for source_key in current_keys & previous_keys
            if source_groups[source_key].source_hash != state.source_hashes[source_key]
        }
        return added_keys, changed_keys, deleted_keys

    def _validate_document_ids(self, source_groups: dict[str, SourceDocumentGroup]) -> None:
        seen: dict[int, str] = {}
        for source_key, group in source_groups.items():
            group_ids: set[int] = set()
            for document in group.documents:
                previous_source = seen.get(document.doc_id)
                if (
                    previous_source is not None
                    or document.doc_id in group_ids
                ):
                    raise ValueError(f"检测到重复文档 ID：{document.doc_id}。")
                seen[document.doc_id] = source_key
                group_ids.add(document.doc_id)

    def _build_full_staging(
        self,
        *,
        staged_sqlite_path: Path,
        documents: list[IndexedDocument],
        source_groups: dict[str, SourceDocumentGroup],
        compatibility_fingerprint: str,
        vector_dimension: int,
        components: tuple[Any, Any, Any, Any, Any],
        embedder: Any,
    ) -> tuple[Any, int]:
        _embedder_cls, faiss_cls, sqlite_cls, index_documents, document_input_cls = components
        connection = sqlite3.connect(staged_sqlite_path)
        sqlite_store = sqlite_cls(connection=connection, table_name="documents")
        try:
            sqlite_store.initialize()
            self._initialize_manifest_schema(
                connection=connection,
                compatibility_fingerprint=compatibility_fingerprint,
                vector_dimension=vector_dimension,
            )
            faiss_store = faiss_cls(dimension=vector_dimension)
            self._index_documents(
                documents=documents,
                document_input_cls=document_input_cls,
                index_documents=index_documents,
                embedder=embedder,
                faiss_store=faiss_store,
                sqlite_store=sqlite_store,
            )
            self._replace_manifest(connection, source_groups)
            document_count = self._count_documents(connection)
            return faiss_store, document_count
        finally:
            connection.close()

    def _build_incremental_staging(
        self,
        *,
        source_sqlite_path: Path,
        staged_sqlite_path: Path,
        source_faiss_path: Path,
        source_groups: dict[str, SourceDocumentGroup],
        state: ExistingCorpusState,
        added_keys: set[str],
        changed_keys: set[str],
        deleted_keys: set[str],
        components: tuple[Any, Any, Any, Any, Any],
        embedder: Any,
    ) -> tuple[Any, int, int]:
        _embedder_cls, faiss_cls, sqlite_cls, index_documents, document_input_cls = components
        self._copy_sqlite(source_sqlite_path, staged_sqlite_path)
        faiss_store = faiss_cls.load(source_faiss_path)
        connection = sqlite3.connect(staged_sqlite_path)
        sqlite_store = sqlite_cls(connection=connection, table_name="documents")
        replacement_keys = changed_keys | deleted_keys
        removed_documents = sum(
            len(state.source_document_ids.get(source_key, [])) for source_key in replacement_keys
        )
        try:
            self._validate_incremental_document_ids(
                source_groups=source_groups,
                state=state,
                replacement_keys=replacement_keys,
                updated_keys=added_keys | changed_keys,
            )
            for source_key in sorted(replacement_keys):
                self._delete_source_documents(
                    connection=connection,
                    sqlite_store=sqlite_store,
                    faiss_store=faiss_store,
                    source_key=source_key,
                    doc_ids=state.source_document_ids.get(source_key, []),
                )

            updated_documents = [
                document
                for source_key in sorted(added_keys | changed_keys)
                for document in source_groups[source_key].documents
            ]
            self._index_documents(
                documents=updated_documents,
                document_input_cls=document_input_cls,
                index_documents=index_documents,
                embedder=embedder,
                faiss_store=faiss_store,
                sqlite_store=sqlite_store,
            )
            for source_key in sorted(added_keys | changed_keys):
                self._write_source_manifest(connection, source_groups[source_key])
            connection.commit()
            return faiss_store, self._count_documents(connection), removed_documents
        finally:
            connection.close()

    def _initialize_manifest_schema(
        self,
        *,
        connection: sqlite3.Connection,
        compatibility_fingerprint: str,
        vector_dimension: int,
    ) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_corpus_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_sources (
                source_key TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                chunk_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_source_documents (
                source_key TEXT NOT NULL,
                doc_id INTEGER NOT NULL UNIQUE,
                chunk_index INTEGER NOT NULL,
                PRIMARY KEY (source_key, doc_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_source_documents_source "
            "ON rag_source_documents(source_key)"
        )
        metadata_rows = [
            ("schema_version", self._MANIFEST_SCHEMA_VERSION),
            ("compatibility_fingerprint", compatibility_fingerprint),
            ("vector_dimension", str(vector_dimension)),
        ]
        connection.executemany(
            """
            INSERT INTO rag_corpus_meta (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            metadata_rows,
        )
        connection.commit()

    def _replace_manifest(
        self,
        connection: sqlite3.Connection,
        source_groups: dict[str, SourceDocumentGroup],
    ) -> None:
        connection.execute("DELETE FROM rag_source_documents")
        connection.execute("DELETE FROM rag_sources")
        for source_key in sorted(source_groups):
            self._write_source_manifest(connection, source_groups[source_key])
        connection.commit()

    def _write_source_manifest(
        self,
        connection: sqlite3.Connection,
        group: SourceDocumentGroup,
    ) -> None:
        connection.execute(
            """
            INSERT INTO rag_sources (
                source_key, source_type, source_path, source_hash, chunk_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                source_type = excluded.source_type,
                source_path = excluded.source_path,
                source_hash = excluded.source_hash,
                chunk_count = excluded.chunk_count,
                updated_at = excluded.updated_at
            """,
            (
                group.source_key,
                group.source_type,
                group.source_path,
                group.source_hash,
                len(group.documents),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.executemany(
            """
            INSERT INTO rag_source_documents (source_key, doc_id, chunk_index)
            VALUES (?, ?, ?)
            """,
            [
                (
                    group.source_key,
                    document.doc_id,
                    int(document.metadata.get("chunk_index") or 0),
                )
                for document in group.documents
            ],
        )

    def _index_documents(
        self,
        *,
        documents: list[IndexedDocument],
        document_input_cls: Any,
        index_documents: Any,
        embedder: Any,
        faiss_store: Any,
        sqlite_store: Any,
    ) -> None:
        if not documents:
            return
        index_documents(
            embedder=embedder,
            faiss_store=faiss_store,
            sqlite_store=sqlite_store,
            documents=[
                document_input_cls(
                    doc_id=document.doc_id,
                    content=document.content,
                    metadata=document.metadata,
                )
                for document in documents
            ],
        )

    def _validate_incremental_document_ids(
        self,
        *,
        source_groups: dict[str, SourceDocumentGroup],
        state: ExistingCorpusState,
        replacement_keys: set[str],
        updated_keys: set[str],
    ) -> None:
        retained_ids = {
            doc_id
            for source_key, doc_ids in state.source_document_ids.items()
            if source_key not in replacement_keys
            for doc_id in doc_ids
        }
        updated_ids: set[int] = set()
        for source_key in updated_keys:
            for document in source_groups[source_key].documents:
                if document.doc_id in retained_ids or document.doc_id in updated_ids:
                    raise ValueError(f"检测到与现有索引冲突的文档 ID：{document.doc_id}。")
                updated_ids.add(document.doc_id)

    def _delete_source_documents(
        self,
        *,
        connection: sqlite3.Connection,
        sqlite_store: Any,
        faiss_store: Any,
        source_key: str,
        doc_ids: list[int],
    ) -> None:
        for start in range(0, len(doc_ids), self._DELETE_BATCH_SIZE):
            batch = doc_ids[start : start + self._DELETE_BATCH_SIZE]
            faiss_store.delete_by_ids(batch)
            sqlite_store.delete_by_ids(batch)
        connection.execute("DELETE FROM rag_source_documents WHERE source_key = ?", (source_key,))
        connection.execute("DELETE FROM rag_sources WHERE source_key = ?", (source_key,))

    def _validate_staged_corpus(
        self,
        *,
        staged_sqlite_path: Path,
        faiss_store: Any,
        expected_documents: int,
    ) -> None:
        with sqlite3.connect(staged_sqlite_path) as connection:
            document_count = self._count_documents(connection)
            mapping_count = int(
                connection.execute("SELECT COUNT(*) FROM rag_source_documents").fetchone()[0] or 0
            )
        faiss_count = int(getattr(faiss_store.index, "ntotal", 0))
        if document_count != expected_documents or mapping_count != expected_documents:
            raise ValueError("暂存索引的文档数量与增量清单不一致。")
        if faiss_count != expected_documents:
            raise ValueError("暂存 FAISS 向量数量与 SQLite 文档数量不一致。")

    def _publish_staged_artifacts(
        self,
        *,
        config: RagConfig,
        staged_faiss_path: Path,
        staged_sqlite_path: Path,
        staging_dir: Path,
    ) -> None:
        previous_faiss_path = staging_dir / "previous-index.faiss"
        previous_sqlite_path = staging_dir / "previous-metadata.sqlite3"
        had_faiss = config.faiss_index_path.exists()
        had_sqlite = config.sqlite_path.exists()
        if had_faiss:
            shutil.copy2(config.faiss_index_path, previous_faiss_path)
        if had_sqlite:
            shutil.copy2(config.sqlite_path, previous_sqlite_path)

        faiss_replaced = False
        sqlite_replaced = False
        try:
            staged_faiss_path.replace(config.faiss_index_path)
            faiss_replaced = True
            staged_sqlite_path.replace(config.sqlite_path)
            sqlite_replaced = True
        except Exception:
            if faiss_replaced:
                self._restore_artifact(
                    target_path=config.faiss_index_path,
                    backup_path=previous_faiss_path,
                    had_previous=had_faiss,
                )
            if sqlite_replaced:
                self._restore_artifact(
                    target_path=config.sqlite_path,
                    backup_path=previous_sqlite_path,
                    had_previous=had_sqlite,
                )
            raise

    def _restore_artifact(
        self,
        *,
        target_path: Path,
        backup_path: Path,
        had_previous: bool,
    ) -> None:
        if had_previous and backup_path.exists():
            backup_path.replace(target_path)
        elif target_path.exists():
            target_path.unlink()

    def _copy_sqlite(self, source_path: Path, target_path: Path) -> None:
        source = sqlite3.connect(self._readonly_sqlite_uri(source_path), uri=True)
        target = sqlite3.connect(target_path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    def _readonly_sqlite_uri(self, path: Path) -> str:
        return f"{path.resolve().as_uri()}?mode=ro"

    def _count_documents(self, connection: sqlite3.Connection) -> int:
        return int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] or 0)

    def _ensure_import_path(self, config: RagConfig) -> None:
        root = str(config.embedding_project_root)
        if root not in sys.path:
            sys.path.insert(0, root)


class NovelCorpusRebuildService:
    def __init__(self, config: RagConfig, builder: NovelCorpusBuilder | None = None) -> None:
        self.config = config
        self.builder = builder or EmbeddingProjectNovelCorpusBuilder()

    def get_status(self) -> dict[str, Any]:
        status_payload = self._load_status()
        index_health = self._inspect_index_health(status_payload)
        return {
            "available": self.config.faiss_index_path.exists() and self.config.sqlite_path.exists(),
            "library_dir": str(self.config.library_dir),
            "faiss_index_path": str(self.config.faiss_index_path),
            "sqlite_path": str(self.config.sqlite_path),
            "sources": self._source_patterns(),
            "last_result": status_payload,
            "index_health": index_health,
        }

    def rebuild(self) -> dict[str, Any]:
        """旧内部调用的兼容入口。

        HTTP API 不再使用此方法，避免旧接口继续同步阻塞请求。新调用方必须
        使用 ``plan_sync`` 与 ``synchronize`` 选择明确模式。
        """
        return self._run_sync(mode="auto")

    def plan_sync(self, mode: str) -> dict[str, Any]:
        if mode not in {"incremental", "full"}:
            raise ValueError("RAG 同步模式必须是 incremental 或 full。")
        source_files = self._collect_source_files()
        if not source_files and not (
            self.config.faiss_index_path.exists() and self.config.sqlite_path.exists()
        ):
            raise ValueError("未扫描到任何可入库的小说语料。")
        documents = self._build_documents(source_files)
        plan_method = getattr(self.builder, "plan", None)
        if not callable(plan_method):
            if mode == "incremental":
                raise FullRebuildRequired(
                    "当前 RAG 构建器不支持增量清单，必须执行全量重建。",
                    reason_code="builder_incompatible",
                )
            build_plan = {
                "sync_mode": "full",
                "scanned_files": len(source_files),
                "indexed_documents": len(documents),
                "embedded_documents": len(documents),
                "reused_documents": 0,
                "added_sources": len(source_files),
                "changed_sources": 0,
                "deleted_sources": 0,
                "removed_documents": 0,
            }
        else:
            build_plan = plan_method(documents, self.config, mode=mode)
        return {
            "mode": mode,
            "scanned_files": len(source_files),
            "sources": self._source_patterns(),
            **{key: value for key, value in dict(build_plan).items()},
        }

    def synchronize(
        self,
        mode: str,
        *,
        phase_callback: Callable[[str, str, int], None] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"incremental", "full"}:
            raise ValueError("RAG 同步模式必须是 incremental 或 full。")
        return self._run_sync(mode=mode, phase_callback=phase_callback)

    def _run_sync(
        self,
        *,
        mode: str,
        phase_callback: Callable[[str, str, int], None] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        phase = "collect_sources"
        try:
            self._report_phase(phase_callback, "collect_sources", "扫描语料来源", 10)
            phase_started = time.perf_counter()
            source_files = self._collect_source_files()
            if not source_files and not (
                self.config.faiss_index_path.exists() and self.config.sqlite_path.exists()
            ):
                raise ValueError("未扫描到任何可入库的小说语料。")
            source_counts: dict[str, int] = {}
            for source_type, _path in source_files:
                source_counts[source_type] = source_counts.get(source_type, 0) + 1
            log_performance(
                logger,
                "rag_rebuild_collect_sources",
                duration_ms=f"{(time.perf_counter() - phase_started) * 1000:.2f}",
                scanned_files=len(source_files),
                source_counts=",".join(f"{key}:{value}" for key, value in sorted(source_counts.items())),
            )

            phase = "build_documents"
            self._report_phase(phase_callback, phase, "构建文本分块", 25)
            phase_started = time.perf_counter()
            documents = self._build_documents(source_files)
            log_performance(
                logger,
                "rag_rebuild_build_documents",
                duration_ms=f"{(time.perf_counter() - phase_started) * 1000:.2f}",
                document_count=len(documents),
            )

            phase = "index_builder"
            self._report_phase(phase_callback, phase, "生成并校验索引", 45)
            phase_started = time.perf_counter()
            build_with_mode = getattr(self.builder, "build_with_mode", None)
            if callable(build_with_mode):
                build_result = build_with_mode(documents, self.config, mode=mode)
            elif mode == "auto":
                build_result = self.builder.build(documents, self.config)
            else:
                raise RuntimeError("当前 RAG 构建器不支持显式同步模式。")
            indexed_documents = int(build_result.get("indexed_documents", len(documents)))
            sync_mode = str(build_result.get("sync_mode") or "full")
            embedded_documents = int(build_result.get("embedded_documents", indexed_documents))
            reused_documents = int(build_result.get("reused_documents", 0))
            added_sources = int(build_result.get("added_sources", 0))
            changed_sources = int(build_result.get("changed_sources", 0))
            deleted_sources = int(build_result.get("deleted_sources", 0))
            removed_documents = int(build_result.get("removed_documents", 0))
            build_warnings = [
                str(warning)
                for warning in (build_result.get("warnings") or [])
                if str(warning).strip()
            ]
            log_performance(
                logger,
                "rag_rebuild_index_builder",
                duration_ms=f"{(time.perf_counter() - phase_started) * 1000:.2f}",
                indexed_documents=indexed_documents,
                sync_mode=sync_mode,
                embedded_documents=embedded_documents,
            )

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            result = {
                "success": True,
                "message": "小说语料索引同步完成。",
                "scanned_files": len(source_files),
                "indexed_documents": indexed_documents,
                "sync_mode": sync_mode,
                "embedded_documents": embedded_documents,
                "reused_documents": reused_documents,
                "added_sources": added_sources,
                "changed_sources": changed_sources,
                "deleted_sources": deleted_sources,
                "removed_documents": removed_documents,
                "output_dir": str(build_result.get("output_dir", self.config.library_dir)),
                "duration_ms": duration_ms,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "sources": self._source_patterns(),
                "warnings": build_warnings,
            }
            phase = "status_write"
            self._report_phase(phase_callback, phase, "发布索引并写入状态", 90)
            phase_started = time.perf_counter()
            self._write_status(result)
            log_performance(
                logger,
                "rag_rebuild_status_write",
                duration_ms=f"{(time.perf_counter() - phase_started) * 1000:.2f}",
            )
            return result
        except Exception as exc:
            log_performance(
                logger,
                "rag_rebuild_failed",
                level=40,
                phase=phase,
                duration_ms=f"{(time.perf_counter() - started_at) * 1000:.2f}",
                error_type=type(exc).__name__,
            )
            raise

    def _report_phase(
        self,
        callback: Callable[[str, str, int], None] | None,
        phase: str,
        label: str,
        progress: int,
    ) -> None:
        if callback is not None:
            callback(phase, label, progress)

    def _collect_source_files(self) -> list[tuple[str, Path]]:
        if not self.config.example_root.exists():
            raise FileNotFoundError(f"示例小说目录不存在：{self.config.example_root}")
        if not self.config.archive_root.exists():
            raise FileNotFoundError(f"归档小说目录不存在：{self.config.archive_root}")

        items: list[tuple[str, Path]] = []
        for path in sorted(self.config.example_root.rglob("*.txt")):
            if path.is_file():
                items.append(("example_novel", path))
        for path in sorted(self.config.archive_root.glob("*/artifacts/final.md")):
            if path.is_file():
                items.append(("archived_final", path))
        for path in sorted(self.config.archive_root.glob("*/outline.md")):
            if path.is_file():
                items.append(("archived_outline", path))
        return items

    def _inspect_index_health(self, status_payload: dict[str, Any] | None) -> dict[str, Any]:
        warnings: list[str] = []
        faiss_count: int | None = None
        faiss_dimension: int | None = None
        sqlite_count: int | None = None
        sqlite_min_doc_id: int | None = None
        sqlite_max_doc_id: int | None = None
        source_mtime_max: float | None = None

        faiss_exists = self.config.faiss_index_path.exists()
        sqlite_exists = self.config.sqlite_path.exists()

        if sqlite_exists:
            try:
                with sqlite3.connect(self.config.sqlite_path) as connection:
                    row = connection.execute("SELECT COUNT(*), MIN(doc_id), MAX(doc_id) FROM documents").fetchone()
                    if row is not None:
                        sqlite_count = int(row[0] or 0)
                        sqlite_min_doc_id = int(row[1]) if row[1] is not None else None
                        sqlite_max_doc_id = int(row[2]) if row[2] is not None else None
            except Exception as exc:
                warnings.append(f"SQLite 元数据读取失败：{exc}")
        else:
            warnings.append("SQLite 元数据文件不存在。")

        if faiss_exists:
            try:
                self._ensure_embedding_project_import_path()
                faiss_module = importlib.import_module("storage.faiss_store")
                faiss_store = getattr(faiss_module, "FaissStore").load(self.config.faiss_index_path)
                faiss_count = int(getattr(faiss_store.index, "ntotal", 0))
                faiss_dimension = int(getattr(faiss_store.index, "d", 0))
            except Exception as exc:
                warnings.append(f"FAISS 索引读取失败：{exc}")
        else:
            warnings.append("FAISS 索引文件不存在。")

        if faiss_count is not None and sqlite_count is not None and faiss_count != sqlite_count:
            warnings.append(f"FAISS 向量数与 SQLite 文档数不一致：FAISS={faiss_count}，SQLite={sqlite_count}。")

        expected_count = None
        if isinstance(status_payload, dict):
            try:
                expected_count = int(status_payload.get("indexed_documents") or 0)
            except Exception:
                expected_count = None
        if expected_count and sqlite_count is not None and sqlite_count != expected_count:
            warnings.append(f"SQLite 文档数与最近重建记录不一致：SQLite={sqlite_count}，最近记录={expected_count}。")

        try:
            source_files = self._collect_source_files()
            mtimes = [path.stat().st_mtime for _, path in source_files if path.exists()]
            source_mtime_max = max(mtimes) if mtimes else None
        except Exception as exc:
            warnings.append(f"源文件状态读取失败：{exc}")

        index_mtimes = [
            path.stat().st_mtime
            for path in (self.config.faiss_index_path, self.config.sqlite_path)
            if path.exists()
        ]
        index_mtime_min = min(index_mtimes) if index_mtimes else None
        if source_mtime_max is not None and index_mtime_min is not None and source_mtime_max > index_mtime_min:
            warnings.append("存在源文件更新时间晚于索引文件，建议重建小说知识库索引。")

        return {
            "ok": bool(faiss_exists and sqlite_exists and not warnings),
            "warnings": warnings,
            "faiss": {
                "exists": faiss_exists,
                "vector_count": faiss_count,
                "dimension": faiss_dimension,
                "mtime": self.config.faiss_index_path.stat().st_mtime if faiss_exists else None,
                "size_bytes": self.config.faiss_index_path.stat().st_size if faiss_exists else None,
            },
            "sqlite": {
                "exists": sqlite_exists,
                "document_count": sqlite_count,
                "min_doc_id": sqlite_min_doc_id,
                "max_doc_id": sqlite_max_doc_id,
                "mtime": self.config.sqlite_path.stat().st_mtime if sqlite_exists else None,
                "size_bytes": self.config.sqlite_path.stat().st_size if sqlite_exists else None,
            },
            "sources": {
                "max_mtime": source_mtime_max,
            },
        }

    def _ensure_embedding_project_import_path(self) -> None:
        root = str(self.config.embedding_project_root)
        if root not in sys.path:
            sys.path.insert(0, root)

    def _build_documents(self, source_files: list[tuple[str, Path]]) -> list[IndexedDocument]:
        documents: list[IndexedDocument] = []
        for source_type, path in source_files:
            raw_content = path.read_text(encoding="utf-8")
            source_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
            content = raw_content.strip()
            if not content:
                continue
            chunk_size, chunk_overlap = self._chunk_profile(source_type)
            chunks = self._chunk_text(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            source_path = str(
                path.relative_to(
                    self.config.example_root.parent
                    if source_type == "example_novel"
                    else self.config.archive_root.parent
                )
            )
            source_key = f"{source_type}:{source_path}"
            for chunk_index, chunk in enumerate(chunks):
                metadata = {
                    "source_type": source_type,
                    "source_path": source_path,
                    "title": path.stem,
                    "chunk_index": chunk_index,
                }
                if source_type != "example_novel":
                    metadata["task_id"] = path.parts[-3] if source_type == "archived_final" else path.parts[-2]
                documents.append(
                    IndexedDocument(
                        doc_id=self._stable_doc_id(path, chunk_index, source_type),
                        content=chunk,
                        metadata=metadata,
                        source_key=source_key,
                        source_hash=source_hash,
                    )
                )
        return documents

    def _chunk_profile(self, source_type: str) -> tuple[int, int]:
        if source_type == "example_novel":
            return 2400, 240
        if source_type == "archived_final":
            return 1800, 180
        if source_type == "archived_outline":
            return 1200, 120
        return 800, 80

    def _chunk_text(self, text: str, chunk_size: int = 400, chunk_overlap: int = 50) -> list[str]:
        normalized = text.strip()
        if not normalized:
            return []
        if len(normalized) <= chunk_size:
            return [normalized]

        chunks: list[str] = []
        start = 0
        step = max(1, chunk_size - chunk_overlap)
        while start < len(normalized):
            chunk = normalized[start : start + chunk_size]
            if chunk:
                chunks.append(chunk)
            if start + chunk_size >= len(normalized):
                break
            start += step
        return chunks

    def _stable_doc_id(self, path: Path, chunk_index: int, source_type: str) -> int:
        digest = hashlib.sha1(f"{source_type}:{path.resolve()}#{chunk_index}".encode("utf-8")).hexdigest()[:15]
        return int(digest, 16)

    def _source_patterns(self) -> list[str]:
        return [
            str(self.config.example_root / "*.txt"),
            str(self.config.archive_root / "*/artifacts/final.md"),
            str(self.config.archive_root / "*/outline.md"),
        ]

    def _load_status(self) -> dict[str, Any] | None:
        if not self.config.status_path.exists():
            return None
        try:
            payload = json.loads(self.config.status_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取 RAG 重建状态失败: path=%s error=%s", self.config.status_path, exc)
            return None
        if not isinstance(payload, dict):
            logger.warning("RAG 重建状态格式不正确: path=%s type=%s", self.config.status_path, type(payload).__name__)
            return None
        return payload

    def _write_status(self, payload: dict[str, Any]) -> None:
        self.config.library_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = self.config.status_path.with_name(f".{self.config.status_path.name}.tmp")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self.config.status_path)
