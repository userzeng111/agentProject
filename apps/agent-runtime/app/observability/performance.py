"""性能埋点辅助工具。"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import time
from typing import Any, Iterator


def _format_value(value: Any) -> str:
    text = str(value)
    text = text.replace("\n", " ").replace("\r", " ")
    if " " in text:
        text = text.replace(" ", "_")
    return text[:240]


def _format_fields(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def log_performance(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """输出稳定的性能日志事件。"""
    payload = _format_fields({"event": event, **fields})
    logger.log(level, payload)


@contextmanager
def performance_span(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> Iterator[None]:
    """记录代码块耗时，异常时保留 traceback 并继续抛出。"""
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        span_fields = dict(fields)
        span_fields.update(
            {
                "status": "failed",
                "duration_ms": f"{duration_ms:.2f}",
                "error_type": type(exc).__name__,
            }
        )
        payload = _format_fields(
            {
                "event": event,
                **span_fields,
            }
        )
        logger.exception(payload)
        raise
    else:
        duration_ms = (time.perf_counter() - started) * 1000
        span_fields = dict(fields)
        span_fields.update(
            {
                "status": "success",
                "duration_ms": f"{duration_ms:.2f}",
            }
        )
        log_performance(
            logger,
            event,
            level=level,
            **span_fields,
        )
