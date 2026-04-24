from __future__ import annotations

import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.observability.context import request_id_var, task_id_var


# 日志目录 - 在 apps/agent-runtime/logs/ 下
LOG_DIR = Path(__file__).parent.parent / "logs"

# 日志格式
LOG_FORMAT = "[%(levelname)s] %(asctime)s %(name)s %(filename)s:%(lineno)d - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 是否已初始化
_initialized = False


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


def _ensure_log_dir():
    """确保日志目录存在"""
    if not LOG_DIR.exists():
        LOG_DIR.mkdir(parents=True, exist_ok=True)


def _create_console_handler() -> logging.StreamHandler:
    """创建控制台处理器 (INFO 级别)"""
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(_StructuredFormatter())
    return handler


def _create_file_handler() -> TimedRotatingFileHandler:
    """创建文件处理器 (DEBUG 级别，按天轮转，保留7天)"""
    _ensure_log_dir()
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"app-{today}.log"
    handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_StructuredFormatter())
    # 自定义文件命名格式: app-YYYY-MM-DD.log
    handler.namer = lambda name: name.replace(".log.", "-").replace(".log", ".log")
    return handler


def init_logging():
    """初始化日志系统"""
    global _initialized
    if _initialized:
        return

    _ensure_log_dir()

    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 清除现有处理器
    root_logger.handlers.clear()

    # 添加处理器
    root_logger.addHandler(_create_console_handler())
    root_logger.addHandler(_create_file_handler())

    # 配置 uvicorn 日志器
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.addHandler(_create_console_handler())
        logger.addHandler(_create_file_handler())
        logger.setLevel(logging.INFO)

    _initialized = True

    # 记录初始化完成
    logging.getLogger("backend.app").info("日志系统初始化完成")


def get_logger(name: str) -> logging.Logger:
    """
    获取日志器实例

    Args:
        name: 日志器名称，建议使用模块路径如 'backend.app.auth'

    Returns:
        配置好的 Logger 实例
    """
    if not _initialized:
        init_logging()

    logger = logging.getLogger(name)
    return logger


# 便捷的模块级日志器
logger = get_logger("backend.app")
