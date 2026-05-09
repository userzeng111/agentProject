from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.rag.config import RagConfig


@dataclass(slots=True)
class IndexedDocument:
    doc_id: int
    content: str
    metadata: dict[str, Any]


class NovelCorpusBuilder(Protocol):
    def build(self, documents: list[IndexedDocument], config: RagConfig) -> dict[str, object]:
        raise NotImplementedError


class EmbeddingProjectNovelCorpusBuilder:
    def build(self, documents: list[IndexedDocument], config: RagConfig) -> dict[str, object]:
        config.library_dir.mkdir(parents=True, exist_ok=True)
        if config.sqlite_path.exists():
            config.sqlite_path.unlink()
        if config.faiss_index_path.exists():
            config.faiss_index_path.unlink()

        self._ensure_import_path(config)
        embedder_module = importlib.import_module("embedder.llama_cpp_embedder")
        faiss_module = importlib.import_module("storage.faiss_store")
        sqlite_module = importlib.import_module("storage.sqlite_store")
        pipeline_module = importlib.import_module("pipeline.indexing")
        schemas_module = importlib.import_module("schemas")

        embedder_cls = getattr(embedder_module, "LlamaCppEmbedder")
        faiss_cls = getattr(faiss_module, "FaissStore")
        sqlite_cls = getattr(sqlite_module, "SQLiteStore")
        index_documents = getattr(pipeline_module, "index_documents")
        document_input_cls = getattr(schemas_module, "DocumentInput")

        embedder = embedder_cls(
            model_path=config.gguf_path,
            model_name=config.model_name,
            n_ctx=config.n_ctx,
            n_threads=config.n_threads,
            n_batch=config.n_batch,
        )
        faiss_store = faiss_cls(dimension=embedder.dimension)
        sqlite_store = sqlite_cls(
            connection=sqlite3.connect(config.sqlite_path),
            table_name="documents",
        )
        sqlite_store.initialize()
        try:
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
            faiss_store.save(config.faiss_index_path)
        finally:
            sqlite_store.connection.close()

        return {
            "indexed_documents": len(documents),
            "output_dir": str(config.library_dir),
        }

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
        started_at = time.perf_counter()
        source_files = self._collect_source_files()
        documents = self._build_documents(source_files)
        build_result = self.builder.build(documents, self.config)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        result = {
            "success": True,
            "message": "小说语料索引重建完成。",
            "scanned_files": len(source_files),
            "indexed_documents": int(build_result.get("indexed_documents", len(documents))),
            "output_dir": str(build_result.get("output_dir", self.config.library_dir)),
            "duration_ms": duration_ms,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "sources": self._source_patterns(),
            "warnings": [],
        }
        self._write_status(result)
        return result

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
        if not items:
            raise ValueError("未扫描到任何可入库的小说语料。")
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
                self._ensure_import_path(self.config)
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

    def _build_documents(self, source_files: list[tuple[str, Path]]) -> list[IndexedDocument]:
        documents: list[IndexedDocument] = []
        for source_type, path in source_files:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            chunk_size, chunk_overlap = self._chunk_profile(source_type)
            chunks = self._chunk_text(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            for chunk_index, chunk in enumerate(chunks):
                metadata = {
                    "source_type": source_type,
                    "source_path": str(path.relative_to(self.config.example_root.parent if source_type == "example_novel" else self.config.archive_root.parent)),
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
            return json.loads(self.config.status_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_status(self, payload: dict[str, Any]) -> None:
        self.config.library_dir.mkdir(parents=True, exist_ok=True)
        self.config.status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
