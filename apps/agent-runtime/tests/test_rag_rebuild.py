import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import build_router
from app.application.task_service import TaskService
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine
from app.rag.config import RagConfig
from app.rag.rebuild_service import IndexedDocument, NovelCorpusRebuildService
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore


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


class RagRebuildTests(unittest.TestCase):
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

    def test_settings_routes_expose_rag_status_and_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                LLM_API_KEY="",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
            task_service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            app = FastAPI()
            app.include_router(
                build_router(task_service, rag_rebuild_service=FakeRagRebuildService()),
                prefix="/api",
            )
            client = TestClient(app)

            status_response = client.get("/api/settings/rag")
            rebuild_response = client.post("/api/settings/rag/rebuild")

            self.assertEqual(status_response.status_code, 200)
            self.assertEqual(rebuild_response.status_code, 200)
            self.assertTrue(status_response.json()["available"])
            self.assertTrue(rebuild_response.json()["success"])


if __name__ == "__main__":
    unittest.main()
