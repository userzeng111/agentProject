from __future__ import annotations

from app.observability import get_logger
from app.observability.performance import log_performance
from pathlib import Path

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    _HAS_SQLITE = True
except ImportError:
    _HAS_SQLITE = False

try:
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:  # pragma: no cover
    from langgraph.checkpoint.memory import InMemorySaver as MemorySaver

logger = get_logger(__name__)


def _create_checkpointer(db_path: str | Path | None = None):
    """创建 checkpointer：优先 SQLite 持久化，回退到内存。"""
    log_performance(
        logger,
        "checkpoint_create",
        has_db_path=bool(db_path),
        sqlite_available=_HAS_SQLITE,
    )
    if _HAS_SQLITE and db_path:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = __import__("sqlite3").connect(str(db_path), check_same_thread=False, timeout=30.0)
            saver = SqliteSaver(conn)
            log_performance(logger, "checkpoint_sqlite_ready", has_db_path=True)
            return saver
        except Exception as exc:
            log_performance(
                logger,
                "checkpoint_create_failed",
                level=40,
                has_db_path=True,
                error_type=type(exc).__name__,
            )
            raise
    if db_path and not _HAS_SQLITE:
        logger.warning(
            "未检测到 langgraph-checkpoint-sqlite，当前退回内存 checkpoint，服务重启后将无法恢复待审核状态。"
        )
        log_performance(logger, "checkpoint_memory_fallback", reason="sqlite_unavailable")
    else:
        log_performance(logger, "checkpoint_memory_fallback", reason="db_path_missing")
    return MemorySaver()
