from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.observability.logger import get_logger

logger = get_logger(__name__)

# 简单计数器: {label: count}
llm_call_counter: dict[str, int] = defaultdict(int)

# 简单耗时 histogram: {label: [duration_ms, ...]}
llm_latency_histogram: dict[str, list[float]] = defaultdict(list)

# 任务状态计数器: {status: count}
task_counter: dict[str, int] = defaultdict(int)


def record_llm_call(model: str, duration_ms: float, success: bool = True) -> None:
    """记录 LLM 调用指标。"""
    label = f"{model}:{('success' if success else 'failure')}"
    llm_call_counter[label] += 1
    llm_latency_histogram[model].append(duration_ms)


def log_task_progress(task_id: str, stage: str, status: str, **kwargs: Any) -> None:
    """记录任务进度并更新计数器。"""
    task_counter[status] += 1
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info("task_progress task_id=%s stage=%s status=%s %s", task_id, stage, status, extra)
