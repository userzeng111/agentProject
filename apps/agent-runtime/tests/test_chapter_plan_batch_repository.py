from pathlib import Path

from app.settings.config import Settings
from app.storage.database import init_db
from app.storage.db_repository import create_chapter_plan_batch, get_chapter_plan_batch


def test_create_chapter_plan_batch_is_idempotent_for_same_task_and_batch(tmp_path: Path) -> None:
    init_db(
        tmp_path / "data.db",
        settings=Settings(_env_file=None, SQLITE_JOURNAL_MODE="WAL"),
    )

    first = create_chapter_plan_batch(
        task_id="task-repeat",
        batch_no=1,
        start_chapter=1,
        end_chapter=8,
        requested_count=20,
        effective_count=8,
        status="waiting_review",
    )
    second = create_chapter_plan_batch(
        task_id="task-repeat",
        batch_no=1,
        start_chapter=1,
        end_chapter=8,
        requested_count=20,
        effective_count=8,
        status="waiting_review",
    )

    stored = get_chapter_plan_batch("task-repeat", 1)

    assert stored is not None
    assert first.id == second.id == stored.id
    assert stored.status == "waiting_review"
