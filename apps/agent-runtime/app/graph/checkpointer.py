from __future__ import annotations

from app.observability import get_logger
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
    if _HAS_SQLITE and db_path:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = __import__("sqlite3").connect(str(db_path), check_same_thread=False, timeout=30.0)
        return SqliteSaver(conn)
    if db_path and not _HAS_SQLITE:
        logger.warning(
            "未检测到 langgraph-checkpoint-sqlite，当前退回内存 checkpoint，服务重启后将无法恢复待审核状态。"
        )
    return MemorySaver()
