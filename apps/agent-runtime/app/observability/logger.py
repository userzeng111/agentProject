from __future__ import annotations

import logging
import sys

from app.observability.context import request_id_var, task_id_var


class _StructuredFormatter(logging.Formatter):
    """带 request_id / task_id 的结构化日志格式器。"""

    def format(self, record: logging.LogRecord) -> str:
        request_id = ""
        task_id = ""
        try:
            request_id = request_id_var.get()
        except LookupError:
            pass
        try:
            task_id = task_id_var.get() or ""
        except LookupError:
            pass

        extra = ""
        if request_id:
            extra += f" request_id={request_id}"
        if task_id:
            extra += f" task_id={task_id}"

        return f"{self.formatTime(record)} [{record.levelname}] {record.name}{extra} {record.getMessage()}"


def get_logger(name: str) -> logging.Logger:
    """获取带结构化格式的 logger。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_StructuredFormatter())
        logger.addHandler(handler)
    return logger
