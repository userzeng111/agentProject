import logging
from pathlib import Path

from sqlalchemy import text

from app.settings.config import Settings
from app.storage.database import get_session, init_db


def test_settings_reads_database_observability_options() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_PATH="/tmp/custom-data.db",
        SQLITE_BUSY_TIMEOUT_MS=1234,
        SQLITE_CONNECT_TIMEOUT_SECONDS=12.5,
        SQLITE_JOURNAL_MODE="WAL",
        SQLITE_FOREIGN_KEYS=False,
        SQLITE_SYNCHRONOUS="NORMAL",
        DB_SQL_LOG_ENABLED=True,
        DB_SLOW_QUERY_MS=7.5,
    )

    assert settings.database_path == "/tmp/custom-data.db"
    assert settings.sqlite_busy_timeout_ms == 1234
    assert settings.sqlite_connect_timeout_seconds == 12.5
    assert settings.sqlite_journal_mode == "WAL"
    assert settings.sqlite_foreign_keys is False
    assert settings.sqlite_synchronous == "NORMAL"
    assert settings.db_sql_log_enabled is True
    assert settings.db_slow_query_ms == 7.5


def test_init_db_applies_configured_sqlite_pragmas(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    settings = Settings(
        _env_file=None,
        SQLITE_BUSY_TIMEOUT_MS=2345,
        SQLITE_JOURNAL_MODE="WAL",
        SQLITE_FOREIGN_KEYS=True,
        SQLITE_SYNCHRONOUS="NORMAL",
    )

    init_db(db_path, settings=settings)

    with get_session() as session:
        journal_mode = session.execute(text("PRAGMA journal_mode")).scalar()
        synchronous = session.execute(text("PRAGMA synchronous")).scalar()
        busy_timeout = session.execute(text("PRAGMA busy_timeout")).scalar()
        foreign_keys = session.execute(text("PRAGMA foreign_keys")).scalar()

    assert journal_mode.lower() == "wal"
    assert synchronous == 1
    assert busy_timeout == 2345
    assert foreign_keys == 1


def test_slow_query_logger_emits_sanitized_sql_summary(tmp_path: Path, caplog) -> None:
    db_path = tmp_path / "data.db"
    settings = Settings(
        _env_file=None,
        DB_SQL_LOG_ENABLED=False,
        DB_SLOW_QUERY_MS=0,
    )
    init_db(db_path, settings=settings)

    with caplog.at_level(logging.WARNING, logger="app.storage.database"):
        with get_session() as session:
            session.execute(text("SELECT :secret AS value"), {"secret": "不能出现在日志里"}).fetchall()

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "slow_sql_query" in messages
    assert "SELECT ? AS value" in messages or "SELECT :secret AS value" in messages
    assert "不能出现在日志里" not in messages
