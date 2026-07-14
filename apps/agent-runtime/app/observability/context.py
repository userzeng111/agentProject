from __future__ import annotations

import contextvars
import uuid
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id")
task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)

# 调用链流转追踪：累积 [service.method] 路径。
# 默认值必须是 None，避免多个 Context 共享同一个可变 list。
request_flow_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("request_flow", default=None)


def push_request_flow(marker: str) -> None:
    """向当前请求的调用链追加一个标记（如 core.sync_task、store.save）。"""
    flow = request_flow_var.get()
    if flow is None:
        flow = []
        request_flow_var.set(flow)
    flow.append(marker)


def pop_request_flow(marker: str | None = None) -> str | None:
    """移除最后一个标记（可选匹配），返回被移除的标记。"""
    flow = request_flow_var.get()
    if not flow:
        return None
    if marker is not None and flow[-1] != marker:
        return None
    removed = flow.pop()
    return removed


def get_request_flow() -> str:
    """返回当前请求的调用链，格式如 api→core→store→db。"""
    flow = request_flow_var.get()
    return "→".join(flow) if flow else ""


def clear_request_flow() -> None:
    """清空调用链。"""
    request_flow_var.set([])


class RequestContext(AbstractContextManager, AbstractAsyncContextManager):
    """设置 request_id 和 task_id 的上下文管理器，支持 sync / async with。"""

    def __init__(self, request_id: str | None = None, task_id: str | None = None) -> None:
        self.request_id = request_id or str(uuid.uuid4())
        self.task_id = task_id
        self._req_token: contextvars.Token[str] | None = None
        self._task_token: contextvars.Token[str | None] | None = None

    def __enter__(self) -> "RequestContext":
        self._req_token = request_id_var.set(self.request_id)
        self._task_token = task_id_var.set(self.task_id)
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._req_token is not None:
            request_id_var.reset(self._req_token)
        if self._task_token is not None:
            task_id_var.reset(self._task_token)

    async def __aenter__(self) -> "RequestContext":
        return self.__enter__()

    async def __aexit__(self, *exc: Any) -> None:
        self.__exit__(*exc)
