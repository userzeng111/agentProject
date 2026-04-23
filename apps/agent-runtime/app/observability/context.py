from __future__ import annotations

import contextvars
import uuid
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id")
task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)


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
