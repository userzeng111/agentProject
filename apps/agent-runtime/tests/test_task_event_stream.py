from app.api.routes import (
    _is_task_stream_done_event,
    _task_stream_done_event_type,
)


def test_task_stream_done_event_type_includes_manual_action() -> None:
    assert _task_stream_done_event_type("completed") == "task.completed"
    assert _task_stream_done_event_type("waiting_manual_action") == "task.recovery.blocked"


def test_is_task_stream_done_event_includes_recovery_blocked() -> None:
    assert _is_task_stream_done_event("task.completed") is True
    assert _is_task_stream_done_event("task.recovery.blocked") is True
    assert _is_task_stream_done_event("chapter.saved") is False
