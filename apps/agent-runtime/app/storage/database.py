"""数据库引擎与会话管理。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event
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
        cursor.close()

    import app.storage.db_models  # noqa: F401
    Base.metadata.create_all(_engine)

    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _session_factory


def get_session() -> Session:
    """创建一个新的数据库会话。"""
    if _session_factory is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_db()")
    return _session_factory()
