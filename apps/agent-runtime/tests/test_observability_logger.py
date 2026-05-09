from app.observability.logger import _rotate_log_filename


def test_rotated_log_filename_keeps_log_suffix() -> None:
    rotated_name = _rotate_log_filename("/tmp/app-2026-04-30.log.2026-05-02")

    assert rotated_name == "/tmp/app-2026-04-30-2026-05-02.log"
