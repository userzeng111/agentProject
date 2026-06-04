"""数据库引擎与会话管理。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import time
from typing import Any, Generator, Optional

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.observability import get_logger
from app.observability.performance import log_performance

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """ORM 基类。"""
    pass


_engine = None
_session_factory: Optional[sessionmaker[Session]] = None
_VALID_JOURNAL_MODES = {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}
_VALID_SYNCHRONOUS = {"OFF", "NORMAL", "FULL", "EXTRA"}


def init_db(db_path: str | Path, *, settings: Any | None = None) -> sessionmaker[Session]:
    """初始化数据库引擎并创建所有表。"""
    global _engine, _session_factory

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    options = _database_options(settings)

    _engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={
            "check_same_thread": False,
            "timeout": options["connect_timeout_seconds"],
        },
    )

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute(f"PRAGMA journal_mode={options['journal_mode']}")
        cursor.execute(f"PRAGMA foreign_keys={'ON' if options['foreign_keys'] else 'OFF'}")
        cursor.execute(f"PRAGMA busy_timeout={options['busy_timeout_ms']}")
        cursor.execute(f"PRAGMA synchronous={options['synchronous']}")
        cursor.close()

    _install_query_logging(_engine, options)

    import app.storage.db_models  # noqa: F401
    Base.metadata.create_all(_engine)
    _ensure_tasks_index_columns(_engine)
    _ensure_novel_project_columns(_engine)
    _ensure_novel_outline_chapter_columns(_engine)

    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    logger.info(
        "database_initialized path=%s journal_mode=%s foreign_keys=%s busy_timeout_ms=%s synchronous=%s",
        db_path,
        options["journal_mode"],
        options["foreign_keys"],
        options["busy_timeout_ms"],
        options["synchronous"],
    )
    return _session_factory


def _database_options(settings: Any | None) -> dict[str, Any]:
    journal_mode = _normalize_choice(
        getattr(settings, "sqlite_journal_mode", "WAL"),
        _VALID_JOURNAL_MODES,
        "WAL",
    )
    synchronous = _normalize_choice(
        getattr(settings, "sqlite_synchronous", "NORMAL"),
        _VALID_SYNCHRONOUS,
        "NORMAL",
    )
    return {
        "busy_timeout_ms": max(int(getattr(settings, "sqlite_busy_timeout_ms", 5000) or 5000), 0),
        "connect_timeout_seconds": max(
            float(getattr(settings, "sqlite_connect_timeout_seconds", 5.0) or 5.0),
            0.1,
        ),
        "journal_mode": journal_mode,
        "foreign_keys": bool(getattr(settings, "sqlite_foreign_keys", True)),
        "synchronous": synchronous,
        "sql_log_enabled": bool(getattr(settings, "db_sql_log_enabled", False)),
        "slow_query_ms": max(float(getattr(settings, "db_slow_query_ms", 100.0) or 0), 0),
    }


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or default).strip().upper()
    return normalized if normalized in allowed else default


def _install_query_logging(engine, options: dict[str, Any]) -> None:
    sql_log_enabled = bool(options["sql_log_enabled"])
    slow_query_ms = float(options["slow_query_ms"])

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start_time", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        started_stack = conn.info.get("query_start_time") or []
        started = started_stack.pop() if started_stack else time.perf_counter()
        duration_ms = (time.perf_counter() - started) * 1000
        statement_summary = _sql_summary(statement)
        parameter_count = _parameter_count(parameters)
        rowcount = getattr(cursor, "rowcount", -1)
        if sql_log_enabled:
            logger.info(
                "sql_query duration_ms=%.2f rows=%s params=%s sql=%s",
                duration_ms,
                rowcount,
                parameter_count,
                statement_summary,
            )
        if duration_ms >= slow_query_ms:
            logger.warning(
                "slow_sql_query duration_ms=%.2f threshold_ms=%.2f rows=%s params=%s sql=%s",
                duration_ms,
                slow_query_ms,
                rowcount,
                parameter_count,
                statement_summary,
            )


def _sql_summary(statement: str) -> str:
    summary = re.sub(r"\s+", " ", str(statement)).strip()
    return summary[:240]


def _parameter_count(parameters: Any) -> int:
    if parameters is None:
        return 0
    if isinstance(parameters, dict):
        return len(parameters)
    if isinstance(parameters, (list, tuple)):
        if parameters and isinstance(parameters[0], (list, tuple, dict)):
            return len(parameters)
        return len(parameters)
    return 1


def _ensure_tasks_index_columns(engine) -> None:
    inspector = inspect(engine)
    if "tasks_index" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("tasks_index")}
    required_columns = {
        "creative_mode": "ALTER TABLE tasks_index ADD COLUMN creative_mode VARCHAR(32) DEFAULT ''",
        "novel_size": "ALTER TABLE tasks_index ADD COLUMN novel_size VARCHAR(16) DEFAULT ''",
        "chapter_word_min": "ALTER TABLE tasks_index ADD COLUMN chapter_word_min INTEGER DEFAULT 0",
    }
    with engine.begin() as connection:
        for column_name, ddl in required_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(ddl))


def _ensure_novel_project_columns(engine) -> None:
    inspector = inspect(engine)
    if "novel_project" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("novel_project")}
    required_columns = {
        "current_generating_chapter_number": (
            "ALTER TABLE novel_project ADD COLUMN current_generating_chapter_number INTEGER"
        ),
    }
    with engine.begin() as connection:
        for column_name, ddl in required_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(ddl))


def _ensure_novel_outline_chapter_columns(engine) -> None:
    inspector = inspect(engine)
    if "novel_outline_chapter" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("novel_outline_chapter")}
    required_columns = {
        "outline_batch_no": "ALTER TABLE novel_outline_chapter ADD COLUMN outline_batch_no INTEGER",
    }
    with engine.begin() as connection:
        for column_name, ddl in required_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(ddl))


@contextmanager
def get_session() -> Generator[Session, Any, None]:
    """创建一个新的数据库会话，异常时自动回滚，退出时自动关闭。"""
    if _session_factory is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_db()")
    session = _session_factory()
    session_started = time.perf_counter()
    _wrap_session_timing(session)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        duration_ms = (time.perf_counter() - session_started) * 1000
        log_performance(
            logger,
            "db_session_total",
            duration_ms=f"{duration_ms:.2f}",
        )
        session.close()


def _wrap_session_timing(session: Session) -> None:
    original_commit = session.commit
    original_rollback = session.rollback

    def timed_commit(*args: Any, **kwargs: Any):
        started = time.perf_counter()
        success = False
        try:
            result = original_commit(*args, **kwargs)
            success = True
            return result
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception("event=db_session_commit status=failed duration_ms=%.2f", duration_ms)
            raise
        finally:
            if success:
                duration_ms = (time.perf_counter() - started) * 1000
                log_performance(
                    logger,
                    "db_session_commit",
                    duration_ms=f"{duration_ms:.2f}",
                )

    def timed_rollback(*args: Any, **kwargs: Any):
        started = time.perf_counter()
        success = False
        try:
            result = original_rollback(*args, **kwargs)
            success = True
            return result
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception("event=db_session_rollback status=failed duration_ms=%.2f", duration_ms)
            raise
        finally:
            if success:
                duration_ms = (time.perf_counter() - started) * 1000
                log_performance(
                    logger,
                    "db_session_rollback",
                    duration_ms=f"{duration_ms:.2f}",
                )

    session.commit = timed_commit  # type: ignore[method-assign]
    session.rollback = timed_rollback  # type: ignore[method-assign]
