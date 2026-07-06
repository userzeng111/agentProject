from __future__ import annotations

import logging
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.observability.context import request_id_var, task_id_var


# 日志目录 - 在 apps/agent-runtime/logs/ 下
LOG_DIR = Path(__file__).parent.parent / "logs"

# 是否已初始化
_initialized = False

# 日志文件前缀 → 对应的 logger 名称列表
_LOG_FILE_MAP: dict[str, list[str]] = {
    "app": [
        "app",
        "backend",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "__main__",
    ],
    "gateway": [
        "backend.gateway",
    ],
}


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

        message = f"{self.formatTime(record)} [{record.levelname}] {record.name}{extra} {record.getMessage()}"
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            message += "\n" + self.formatStack(record.stack_info)
        return message


class _NamespaceFilter(logging.Filter):
    """只放行指定 logger 名称空间下的日志记录，可排除子名称空间。"""

    def __init__(self, namespace_prefixes: list[str], exclude_prefixes: list[str] | None = None) -> None:
        super().__init__()
        self._prefixes = namespace_prefixes
        self._excludes = exclude_prefixes or []

    def filter(self, record: logging.LogRecord) -> bool:
        # 先检查排除列表
        for excl in self._excludes:
            if record.name == excl or record.name.startswith(excl + "."):
                return False
        # 再检查包含列表
        return any(record.name == prefix or record.name.startswith(prefix + ".") for prefix in self._prefixes)


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


def _rotate_log_filename(name: str) -> str:
    """将轮转日志命名为 前缀-源日期-轮转日期.log。"""
    if ".log." not in name:
        return name
    return f"{name.replace('.log.', '-')}.log"


def _create_file_handler(log_prefix: str, namespace_prefixes: list[str], exclude_prefixes: list[str] | None = None) -> TimedRotatingFileHandler:
    """创建指定日志文件处理器 (DEBUG 级别，按天轮转，保留7天)。"""
    _ensure_log_dir()
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{log_prefix}-{today}.log"
    handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_StructuredFormatter())
    handler.namer = _rotate_log_filename
    handler.addFilter(_NamespaceFilter(namespace_prefixes, exclude_prefixes))
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

    # 控制台处理器（所有日志均输出到控制台）
    root_logger.addHandler(_create_console_handler())

    # ═══ 按名称空间分流到不同文件 ═══
    # app-{date}.log：业务逻辑、系统日志（排除网关日志避免重复）
    app_loggers = _LOG_FILE_MAP.get("app", ["backend"])
    root_logger.addHandler(
        _create_file_handler("app", app_loggers, exclude_prefixes=["backend.gateway"])
    )

    # gateway-{date}.log：LLM 网关调用日志
    gateway_loggers = _LOG_FILE_MAP.get("gateway", ["backend.gateway"])
    gateway_handler = _create_file_handler("gateway", gateway_loggers)
    root_logger.addHandler(gateway_handler)

    # 配置 uvicorn 日志器
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.addHandler(_create_console_handler())
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
