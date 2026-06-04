from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.application.task_service.core import TaskServiceCoreMixin
from app.domain.models import TaskCreateRequest
from app.llm.gateway_client import OpenAICompatibleGatewayClient
from app.observability.context import RequestContext, request_id_var, task_id_var
from app.observability.performance import performance_span
from app.rag.config import RagConfig
from app.rag.rebuild_service import IndexedDocument, NovelCorpusRebuildService
from app.rag.service import RagHit, RagService
from app.storage.database import get_session, init_db
from app.storage.task_store import TaskLogStore


class _FakeStreamResponse:
    status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def iter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"甲"},"finish_reason":null}],"model":"test-model"}'
        yield 'data: {"choices":[{"delta":{"reasoning_content":"想"},"finish_reason":null}],"model":"test-model"}'
        yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"model":"test-model"}'
        yield 'data: {"usage":{"completion_tokens":2}}'
        yield "data: [DONE]"

    def read(self) -> bytes:
        return b""


class _FakeClient:
    is_closed = False

    def stream(self, *args: Any, **kwargs: Any) -> _FakeStreamResponse:
        return _FakeStreamResponse()


class _StubSearchBackend:
    def __init__(self, hits: list[RagHit] | None = None, error: Exception | None = None) -> None:
        self.hits = list(hits or [])
        self.error = error

    def search(self, query: str, top_k: int) -> list[RagHit]:
        if self.error is not None:
            raise self.error
        return list(self.hits)


class _FakeNovelCorpusBuilder:
    def build(self, documents: list[IndexedDocument], config: RagConfig) -> dict[str, object]:
        config.library_dir.mkdir(parents=True, exist_ok=True)
        config.faiss_index_path.write_text("fake-index", encoding="utf-8")
        config.sqlite_path.write_text("fake-db", encoding="utf-8")
        return {"indexed_documents": len(documents), "output_dir": str(config.library_dir)}


def _messages(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


def test_performance_span_logs_success_and_failure(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("tests.performance_span")

    with caplog.at_level(logging.INFO, logger="tests.performance_span"):
        with performance_span(logger, "unit_operation", item_id="abc"):
            pass

    messages = _messages(caplog)
    assert "unit_operation" in messages
    assert "status=success" in messages
    assert "duration_ms=" in messages
    assert "item_id=abc" in messages

    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="tests.performance_span"):
        with pytest.raises(RuntimeError):
            with performance_span(logger, "unit_operation_failed", item_id="abc"):
                raise RuntimeError("模拟失败")

    messages = _messages(caplog)
    assert "unit_operation_failed" in messages
    assert "status=failed" in messages
    assert "error_type=RuntimeError" in messages


def test_db_session_logs_total_commit_and_rollback(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    init_db(tmp_path / "data.db")

    with caplog.at_level(logging.INFO, logger="app.storage.database"):
        with get_session() as session:
            session.execute(text("SELECT 1")).fetchall()
            session.commit()

    messages = _messages(caplog)
    assert "db_session_commit" in messages
    assert "db_session_total" in messages

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.storage.database"):
        with pytest.raises(RuntimeError):
            with get_session():
                raise RuntimeError("触发回滚")

    messages = _messages(caplog)
    assert "db_session_rollback" in messages
    assert "db_session_total" in messages


def test_task_store_logs_save_and_file_io(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    init_db(tmp_path / "data.db")
    store = TaskLogStore(root_dir=str(tmp_path / "tasklog"))
    payload = TaskCreateRequest(prompt="测试性能日志", genre="玄幻", style="冷静")

    with caplog.at_level(logging.INFO, logger="app.storage.task_store"):
        task = store.create_task(payload)
        store.append_event(task.id, stage="unit", message="追加事件", event_type="unit.event")

    messages = _messages(caplog)
    assert "task_store_save" in messages
    assert "task_store_write_task_files" in messages
    assert "task_store_sync_to_db" in messages
    assert "task_store_append_event" in messages
    assert "task_store_write_file" in messages


def test_background_task_inherits_request_context_and_logs_lifecycle(caplog: pytest.LogCaptureFixture) -> None:
    service = TaskServiceCoreMixin.__new__(TaskServiceCoreMixin)
    service._run_lock = threading.Lock()
    service._active_runs = set()
    service._active_threads = {}
    service._stop_requested = set()

    seen: dict[str, str | None] = {}
    done = threading.Event()

    def target() -> None:
        seen["request_id"] = request_id_var.get()
        seen["task_id"] = task_id_var.get()
        done.set()

    with caplog.at_level(logging.INFO, logger="app.application.task_service.core"):
        with RequestContext(request_id="req-perf", task_id="outer-task"):
            service._start_background("task-perf", target)
        assert done.wait(timeout=2)
        deadline = time.time() + 2
        while "background_task_end" not in _messages(caplog) and time.time() < deadline:
            time.sleep(0.01)

    messages = _messages(caplog)
    assert seen == {"request_id": "req-perf", "task_id": "task-perf"}
    assert "background_task_start" in messages
    assert "background_task_end" in messages
    assert "request_id=req-perf" in "\n".join(
        f"{record.getMessage()} request_id={getattr(record, 'request_id', '')}" for record in caplog.records
    ) or "request_id=req-perf" in messages
    assert "task_id=task-perf" in messages


def test_llm_stream_sync_logs_chunk_metrics(caplog: pytest.LogCaptureFixture) -> None:
    client = OpenAICompatibleGatewayClient(
        base_url="http://example.com",
        api_key="test-key",
        model="test-model",
    )
    client._client = _FakeClient()

    with caplog.at_level(logging.INFO, logger="app.llm.gateway_client"):
        chunks = list(client.complete_stream_sync([{"role": "user", "content": "测试"}]))

    assert [chunk.content for chunk in chunks if chunk.content] == ["甲"]
    messages = _messages(caplog)
    assert "llm_stream_sync_first_token" in messages
    assert "llm_stream_sync_metrics" in messages
    assert "chunk_count=2" in messages
    assert "finish_reason=stop" in messages


def test_rag_search_logs_phases(caplog: pytest.LogCaptureFixture) -> None:
    service = RagService(
        RagConfig(enabled=True, top_k=2, max_context_chars=100),
        search_backend=_StubSearchBackend(
            hits=[RagHit(doc_id="1", content="命中内容", score=0.9)]
        ),
    )

    with caplog.at_level(logging.INFO, logger="app.rag.service"):
        result = service.search("检索词")

    assert result.selected_contexts == ["命中内容"]
    messages = _messages(caplog)
    assert "rag_search_backend" in messages
    assert "rag_search_filter" in messages
    assert "rag_search_select" in messages


def test_rag_rebuild_logs_phases(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    example_root = tmp_path / "exampleIndexData"
    example_root.mkdir(parents=True)
    (example_root / "demo.txt").write_text("甲" * 100, encoding="utf-8")
    archive_root = tmp_path / "tasklog" / "archive"
    archive_root.mkdir(parents=True)
    config = RagConfig(
        enabled=True,
        example_root=example_root,
        archive_root=archive_root,
        artifacts_root=tmp_path / "Data" / "rag" / "novel_corpus",
        gguf_path=tmp_path / "models" / "bge.gguf",
    )
    service = NovelCorpusRebuildService(config=config, builder=_FakeNovelCorpusBuilder())

    with caplog.at_level(logging.INFO, logger="app.rag.rebuild_service"):
        result = service.rebuild()

    assert result["success"] is True
    messages = _messages(caplog)
    assert "rag_rebuild_collect_sources" in messages
    assert "rag_rebuild_build_documents" in messages
    assert "rag_rebuild_index_builder" in messages
    assert "rag_rebuild_status_write" in messages
