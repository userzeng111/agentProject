import io
import logging

from app.observability.logger import _rotate_log_filename
from app.observability.logger import _StructuredFormatter


def test_rotated_log_filename_keeps_log_suffix() -> None:
    rotated_name = _rotate_log_filename("/tmp/app-2026-04-30.log.2026-05-02")

    assert rotated_name == "/tmp/app-2026-04-30-2026-05-02.log"


def test_structured_formatter_keeps_exception_traceback() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_StructuredFormatter())
    logger = logging.getLogger("tests.traceback")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    try:
        raise RuntimeError("模拟异常")
    except RuntimeError:
        logger.exception("记录异常")

    output = stream.getvalue()
    assert "记录异常" in output
    assert "Traceback" in output
    assert "RuntimeError: 模拟异常" in output
