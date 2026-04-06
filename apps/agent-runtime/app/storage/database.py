"""数据库引擎与会话管理。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """ORM 基类。"""
    pass


_session_factory: Optional[sessionmaker[Session]] = None
_engine = None


def init_db(db_path: str | Path) -> sessionmaker[Session]:
    """初始化数据库引擎并创建所有表。

    参数:
        db_path: SQLite 数据库文件路径，如 "tasklog/data.db"
    """
    global _engine, _session_factory

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    url = f"sqlite:///{db_path}"
    _engine = create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # 启用 SQLite WAL 模式，提升并发读写性能
    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # 导入所有 ORM 模型，确保 create_all 能识别
    import app.storage.db_models  # noqa: F401

    Base.metadata.create_all(_engine)

    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _session_factory


def get_session_factory() -> sessionmaker[Session]:
    """获取全局会话工厂，必须先调用 init_db。"""
    if _session_factory is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_db()")
    return _session_factory


def get_session() -> Session:
    """创建一个新的数据库会话。"""
    return get_session_factory()()
