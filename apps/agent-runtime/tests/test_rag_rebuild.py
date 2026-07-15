import hashlib
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import build_router
from app.application.task_service import TaskService
from app.llm.story_engine import StoryEngine
from app.rag.config import RagConfig
from app.rag.rebuild_service import (
    EmbeddingProjectNovelCorpusBuilder,
    FullRebuildRequired,
    IndexedDocument,
    NovelCorpusRebuildService,
)
from app.rag.sync_jobs import RagSyncJobService
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore
from tests.fakes import build_verified_gateway_model_catalog


class FakeNovelCorpusBuilder:
    def __init__(self) -> None:
        self.documents: list[IndexedDocument] = []

    def build(self, documents: list[IndexedDocument], config: RagConfig) -> dict[str, object]:
        self.documents = list(documents)
        config.library_dir.mkdir(parents=True, exist_ok=True)
        config.faiss_index_path.write_text("fake-index", encoding="utf-8")
        config.sqlite_path.write_text("fake-db", encoding="utf-8")
        return {
            "indexed_documents": len(documents),
            "output_dir": str(config.library_dir),
        }


class CountingEmbedder:
    dimension = 2

    def __init__(self, builder: "CountingEmbeddingProjectBuilder") -> None:
        self.builder = builder

    def embed_texts(self, texts: list[str], is_query: bool = False):
        if self.builder.fail_embeddings:
            raise RuntimeError("测试注入的 embedding 失败")
        self.builder.embedding_batches.append(list(texts))
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([float(digest[0] + 1), float(digest[1] + 1)])
        return SimpleNamespace(vectors=np.asarray(vectors, dtype=np.float32))


class CountingEmbeddingProjectBuilder(EmbeddingProjectNovelCorpusBuilder):
    def __init__(self) -> None:
        self.embedding_batches: list[list[str]] = []
        self.fail_embeddings = False

    def _create_embedder(self, embedder_cls, config):
        return CountingEmbedder(self)


class FakeRagRebuildService:
    def get_status(self):
        return {
            "available": True,
            "library_dir": "/tmp/novel-corpus",
            "sources": ["exampleIndexData/*.txt"],
        }

    def rebuild(self):
        return {
            "success": True,
            "message": "重建完成",
            "scanned_files": 3,
            "indexed_documents": 12,
            "output_dir": "/tmp/novel-corpus",
            "duration_ms": 1200,
            "sources": ["exampleIndexData/*.txt"],
            "warnings": [],
        }


class FakeRagSyncJobService:
    def create_plan(self, mode):
        return {
            "plan_id": "plan_001",
            "mode": mode,
            "state": "ready",
            "can_start": True,
            "summary": {"embedded_documents": 2},
            "confirmation": {"required": mode == "full", "token": "confirm" if mode == "full" else None},
        }

    def create_job(self, *, plan_id, mode, idempotency_key, confirmation_token=None):
        return (
            {
                "job_id": "job_001",
                "mode": mode,
                "status": "queued",
                "phase": "queued",
                "progress": 0,
                "poll_after_ms": 1000,
            },
            True,
        )

    def get_current_job(self):
        return {"job_id": "job_001", "mode": "incremental", "status": "running", "phase": "index_builder"}

    def get_job(self, job_id):
        if job_id == "job_001":
            return {"job_id": job_id, "mode": "incremental", "status": "succeeded", "phase": "completed"}
        return None


class RagRebuildTests(unittest.TestCase):
    def test_explicit_incremental_requires_compatible_manifest_without_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_root = root / "exampleIndexData"
            archive_root = root / "tasklog" / "archive"
            example_root.mkdir(parents=True)
            archive_root.mkdir(parents=True)
            (example_root / "示例.txt").write_text("测试内容", encoding="utf-8")
            config = RagConfig(
                enabled=True,
                example_root=example_root,
                archive_root=archive_root,
                artifacts_root=root / "Data" / "rag" / "novel_corpus",
                gguf_path=root / "models" / "fake.gguf",
            )
            builder = CountingEmbeddingProjectBuilder()
            service = NovelCorpusRebuildService(config=config, builder=builder)

            with self.assertRaises(FullRebuildRequired) as plan_error:
                service.plan_sync("incremental")
            self.assertEqual(plan_error.exception.reason_code, "index_missing")
            with self.assertRaises(FullRebuildRequired):
                service.synchronize("incremental")
            self.assertEqual(builder.embedding_batches, [])
            self.assertFalse(config.faiss_index_path.exists())
            self.assertFalse(config.sqlite_path.exists())

            full = service.synchronize("full")
            self.assertEqual(full["sync_mode"], "full")
            self.assertEqual(len(builder.embedding_batches), 1)
            incremental = service.synchronize("incremental")
            self.assertEqual(incremental["sync_mode"], "noop")
            self.assertEqual(len(builder.embedding_batches), 1)

            with sqlite3.connect(config.sqlite_path) as connection:
                connection.execute("DROP TABLE rag_source_documents")
                connection.execute("DROP TABLE rag_sources")
                connection.execute("DROP TABLE rag_corpus_meta")
            with self.assertRaises(FullRebuildRequired) as legacy_error:
                service.synchronize("incremental")
            self.assertEqual(legacy_error.exception.reason_code, "index_incompatible")
            self.assertEqual(len(builder.embedding_batches), 1)

    def test_background_jobs_persist_progress_confirm_full_and_deduplicate_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_root = root / "exampleIndexData"
            archive_root = root / "tasklog" / "archive"
            example_root.mkdir(parents=True)
            archive_root.mkdir(parents=True)
            (example_root / "示例.txt").write_text("后台构建内容", encoding="utf-8")
            config = RagConfig(
                enabled=True,
                example_root=example_root,
                archive_root=archive_root,
                artifacts_root=root / "Data" / "rag" / "novel_corpus",
                gguf_path=root / "models" / "fake.gguf",
            )
            builder = CountingEmbeddingProjectBuilder()
            rebuild_service = NovelCorpusRebuildService(config=config, builder=builder)
            jobs = RagSyncJobService(rebuild_service)
            try:
                incremental_plan = jobs.create_plan("incremental")
                self.assertEqual(incremental_plan["state"], "full_rebuild_required")
                self.assertFalse(incremental_plan["can_start"])
                self.assertEqual(builder.embedding_batches, [])

                full_plan = jobs.create_plan("full")
                self.assertTrue(full_plan["confirmation"]["required"])
                job, created = jobs.create_job(
                    plan_id=full_plan["plan_id"],
                    mode="full",
                    idempotency_key="full-first-request",
                    confirmation_token=full_plan["confirmation"]["token"],
                )
                self.assertTrue(created)
                self.assertEqual(job["status"], "queued")
                same_job, created_again = jobs.create_job(
                    plan_id=full_plan["plan_id"],
                    mode="full",
                    idempotency_key="full-first-request",
                    confirmation_token=full_plan["confirmation"]["token"],
                )
                self.assertFalse(created_again)
                self.assertEqual(same_job["job_id"], job["job_id"])

                deadline = time.monotonic() + 5
                completed = None
                while time.monotonic() < deadline:
                    completed = jobs.get_job(job["job_id"])
                    if completed and completed["status"] not in {"queued", "running"}:
                        break
                    time.sleep(0.02)
                self.assertIsNotNone(completed)
                self.assertEqual(completed["status"], "succeeded")
                self.assertEqual(completed["result"]["sync_mode"], "full")
                self.assertEqual(jobs.get_current_job()["job_id"], job["job_id"])
                self.assertTrue((config.library_dir / "sync_jobs" / "jobs" / f"{job['job_id']}.json").exists())
            finally:
                jobs.close()

    def test_incremental_builder_only_embeds_changed_sources_and_removes_deleted_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_root = root / "exampleIndexData"
            archive_root = root / "tasklog" / "archive"
            example_root.mkdir(parents=True)
            archive_task_root = archive_root / "task_001"
            archive_artifacts = archive_task_root / "artifacts"
            archive_artifacts.mkdir(parents=True)
            (example_root / "示例.txt").write_text("示例小说内容", encoding="utf-8")
            final_path = archive_artifacts / "final.md"
            final_path.write_text("归档正文初版", encoding="utf-8")

            config = RagConfig(
                enabled=True,
                example_root=example_root,
                archive_root=archive_root,
                artifacts_root=root / "Data" / "rag" / "novel_corpus",
                gguf_path=root / "models" / "fake.gguf",
            )
            builder = CountingEmbeddingProjectBuilder()
            service = NovelCorpusRebuildService(config=config, builder=builder)

            first = service.rebuild()
            self.assertEqual(first["sync_mode"], "full")
            self.assertEqual(first["indexed_documents"], 2)
            self.assertEqual(first["embedded_documents"], 2)
            self.assertEqual(len(builder.embedding_batches), 1)
            self.assertEqual(len(builder.embedding_batches[0]), 2)

            noop = service.rebuild()
            self.assertEqual(noop["sync_mode"], "noop")
            self.assertEqual(noop["embedded_documents"], 0)
            self.assertEqual(len(builder.embedding_batches), 1)

            outline_path = archive_task_root / "outline.md"
            outline_path.write_text("归档大纲", encoding="utf-8")
            added = service.rebuild()
            self.assertEqual(added["sync_mode"], "incremental")
            self.assertEqual(added["added_sources"], 1)
            self.assertEqual(added["embedded_documents"], 1)
            self.assertEqual(added["reused_documents"], 2)
            self.assertEqual(len(builder.embedding_batches), 2)
            self.assertEqual(builder.embedding_batches[-1], ["归档大纲"])

            final_path.write_text("归档正文修订版", encoding="utf-8")
            changed = service.rebuild()
            self.assertEqual(changed["sync_mode"], "incremental")
            self.assertEqual(changed["embedded_documents"], 1)
            self.assertEqual(changed["changed_sources"], 1)
            self.assertEqual(changed["reused_documents"], 2)
            self.assertEqual(len(builder.embedding_batches), 3)
            self.assertEqual(builder.embedding_batches[-1], ["归档正文修订版"])

            final_path.unlink()
            deleted = service.rebuild()
            self.assertEqual(deleted["sync_mode"], "incremental")
            self.assertEqual(deleted["deleted_sources"], 1)
            self.assertEqual(deleted["removed_documents"], 1)
            self.assertEqual(deleted["embedded_documents"], 0)
            self.assertEqual(deleted["indexed_documents"], 2)
            self.assertEqual(len(builder.embedding_batches), 3)

            with sqlite3.connect(config.sqlite_path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 2)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM rag_source_documents").fetchone()[0],
                    2,
                )
            health = service.get_status()["index_health"]
            self.assertTrue(health["ok"])
            self.assertEqual(health["faiss"]["vector_count"], 2)

            (example_root / "示例.txt").unlink()
            outline_path.unlink()
            emptied = service.rebuild()
            self.assertEqual(emptied["sync_mode"], "incremental")
            self.assertEqual(emptied["deleted_sources"], 2)
            self.assertEqual(emptied["removed_documents"], 2)
            self.assertEqual(emptied["indexed_documents"], 0)
            self.assertEqual(emptied["embedded_documents"], 0)
            self.assertEqual(len(builder.embedding_batches), 3)

            with sqlite3.connect(config.sqlite_path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM rag_sources").fetchone()[0], 0)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM rag_source_documents").fetchone()[0],
                    0,
                )
            self.assertTrue(service.get_status()["index_health"]["ok"])

    def test_legacy_or_failed_sync_keeps_existing_artifacts_until_staging_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_root = root / "exampleIndexData"
            archive_root = root / "tasklog" / "archive"
            example_root.mkdir(parents=True)
            archive_root.mkdir(parents=True)
            source_path = example_root / "示例.txt"
            source_path.write_text("可用旧内容", encoding="utf-8")

            config = RagConfig(
                enabled=True,
                example_root=example_root,
                archive_root=archive_root,
                artifacts_root=root / "Data" / "rag" / "novel_corpus",
                gguf_path=root / "models" / "fake.gguf",
            )
            builder = CountingEmbeddingProjectBuilder()
            service = NovelCorpusRebuildService(config=config, builder=builder)
            self.assertEqual(service.rebuild()["sync_mode"], "full")

            with sqlite3.connect(config.sqlite_path) as connection:
                connection.execute("DROP TABLE rag_source_documents")
                connection.execute("DROP TABLE rag_sources")
                connection.execute("DROP TABLE rag_corpus_meta")
            old_faiss = config.faiss_index_path.read_bytes()
            old_sqlite = config.sqlite_path.read_bytes()
            source_path.write_text("触发全量迁移但失败", encoding="utf-8")
            builder.fail_embeddings = True

            with self.assertRaisesRegex(RuntimeError, "embedding 失败"):
                service.rebuild()

            self.assertEqual(config.faiss_index_path.read_bytes(), old_faiss)
            self.assertEqual(config.sqlite_path.read_bytes(), old_sqlite)

            builder.fail_embeddings = False
            migrated = service.rebuild()
            self.assertEqual(migrated["sync_mode"], "full")
            self.assertIn("缺少增量清单", "；".join(migrated["warnings"]))

    def test_rebuild_service_scans_example_and_archive_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_root = root / "exampleIndexData"
            example_root.mkdir(parents=True, exist_ok=True)
            (example_root / "斗罗大陆.txt").write_text("斗罗大陆内容", encoding="utf-8")

            archive_root = root / "tasklog" / "archive" / "task_001" / "artifacts"
            archive_root.mkdir(parents=True, exist_ok=True)
            (archive_root / "final.md").write_text("归档正文内容", encoding="utf-8")
            (archive_root.parent / "outline.md").write_text("归档大纲内容", encoding="utf-8")

            config = RagConfig(
                enabled=True,
                example_root=example_root,
                archive_root=root / "tasklog" / "archive",
                artifacts_root=root / "Data" / "rag" / "novel_corpus",
                gguf_path=root / "models" / "bge.gguf",
            )
            builder = FakeNovelCorpusBuilder()
            service = NovelCorpusRebuildService(config=config, builder=builder)

            result = service.rebuild()

            self.assertTrue(result["success"])
            self.assertEqual(result["scanned_files"], 3)
            self.assertEqual(result["indexed_documents"], 3)
            self.assertTrue(config.status_path.exists())
            source_types = {document.metadata["source_type"] for document in builder.documents}
            self.assertEqual(source_types, {"example_novel", "archived_final", "archived_outline"})

    def test_rebuild_service_uses_larger_chunks_for_example_novel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_root = root / "exampleIndexData"
            example_root.mkdir(parents=True, exist_ok=True)
            (example_root / "斗罗大陆.txt").write_text("甲" * 5000, encoding="utf-8")

            archive_root = root / "tasklog" / "archive"
            archive_root.mkdir(parents=True, exist_ok=True)

            config = RagConfig(
                enabled=True,
                example_root=example_root,
                archive_root=archive_root,
                artifacts_root=root / "Data" / "rag" / "novel_corpus",
                gguf_path=root / "models" / "bge.gguf",
            )
            service = NovelCorpusRebuildService(config=config, builder=FakeNovelCorpusBuilder())

            documents = service._build_documents([("example_novel", example_root / "斗罗大陆.txt")])

            self.assertEqual(len(documents), 3)
            self.assertEqual(documents[0].metadata["chunk_index"], 0)
            self.assertEqual(documents[-1].metadata["chunk_index"], 2)

    def test_get_status_warns_when_status_file_is_corrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_root = root / "exampleIndexData"
            archive_root = root / "tasklog" / "archive"
            example_root.mkdir(parents=True, exist_ok=True)
            archive_root.mkdir(parents=True, exist_ok=True)
            (example_root / "斗罗大陆.txt").write_text("斗罗大陆内容", encoding="utf-8")

            config = RagConfig(
                enabled=True,
                example_root=example_root,
                archive_root=archive_root,
                artifacts_root=root / "Data" / "rag" / "novel_corpus",
                gguf_path=root / "models" / "bge.gguf",
            )
            config.library_dir.mkdir(parents=True, exist_ok=True)
            config.status_path.write_text("{bad json", encoding="utf-8")
            service = NovelCorpusRebuildService(config=config, builder=FakeNovelCorpusBuilder())

            with self.assertLogs("app.rag.rebuild_service", level="WARNING") as logs:
                status = service.get_status()

            self.assertIsNone(status["last_result"])
            self.assertIn("读取 RAG 重建状态失败", "\n".join(logs.output))

    def test_get_status_warns_when_status_file_is_not_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            example_root = root / "exampleIndexData"
            archive_root = root / "tasklog" / "archive"
            example_root.mkdir(parents=True, exist_ok=True)
            archive_root.mkdir(parents=True, exist_ok=True)
            (example_root / "斗罗大陆.txt").write_text("斗罗大陆内容", encoding="utf-8")

            config = RagConfig(
                enabled=True,
                example_root=example_root,
                archive_root=archive_root,
                artifacts_root=root / "Data" / "rag" / "novel_corpus",
                gguf_path=root / "models" / "bge.gguf",
            )
            config.library_dir.mkdir(parents=True, exist_ok=True)
            config.status_path.write_text("[]", encoding="utf-8")
            service = NovelCorpusRebuildService(config=config, builder=FakeNovelCorpusBuilder())

            with self.assertLogs("app.rag.rebuild_service", level="WARNING") as logs:
                status = service.get_status()

            self.assertIsNone(status["last_result"])
            self.assertIn("RAG 重建状态格式不正确", "\n".join(logs.output))

    def test_settings_routes_expose_rag_status_and_async_sync_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                LLM_API_KEY="",
                DEFAULT_CHAT_MODEL="",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
            task_service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            app = FastAPI()
            app.include_router(
                build_router(
                    task_service,
                    rag_rebuild_service=FakeRagRebuildService(),
                    rag_sync_job_service=FakeRagSyncJobService(),
                ),
                prefix="/api",
            )
            client = TestClient(app)

            status_response = client.get("/api/settings/rag")
            rebuild_response = client.post("/api/settings/rag/rebuild")
            plan_response = client.post("/api/settings/rag/plans", json={"mode": "incremental"})
            job_response = client.post(
                "/api/settings/rag/jobs",
                json={"plan_id": "plan_001", "mode": "incremental", "idempotency_key": "request-1"},
            )
            current_response = client.get("/api/settings/rag/jobs/current")
            completed_response = client.get("/api/settings/rag/jobs/job_001")

            self.assertEqual(status_response.status_code, 200)
            self.assertEqual(rebuild_response.status_code, 410)
            self.assertEqual(plan_response.status_code, 200)
            self.assertEqual(job_response.status_code, 202)
            self.assertEqual(current_response.status_code, 200)
            self.assertEqual(completed_response.status_code, 200)
            self.assertTrue(status_response.json()["available"])
            self.assertEqual(plan_response.json()["plan_id"], "plan_001")
            self.assertEqual(job_response.json()["job_id"], "job_001")


if __name__ == "__main__":
    unittest.main()
