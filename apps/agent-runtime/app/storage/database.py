"""数据库引擎与会话管理。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """ORM 基类。"""
    pass


_engine = None
_session_factory: Optional[sessionmaker[Session]] = None


def init_db(db_path: str | Path) -> sessionmaker[Session]:
    """初始化数据库引擎并创建所有表。"""
    global _engine, _session_factory

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    import app.storage.db_models  # noqa: F401
    Base.metadata.create_all(_engine)
    _ensure_tasks_index_columns(_engine)
    _ensure_novel_project_columns(_engine)
    _ensure_novel_outline_chapter_columns(_engine)

    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _session_factory


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
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
