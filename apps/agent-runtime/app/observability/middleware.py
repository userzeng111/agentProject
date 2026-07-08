from __future__ import annotations

import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.observability.context import (
    clear_request_flow,
    get_request_flow,
    request_flow_var,
    request_id_var,
)
from app.observability.logger import get_logger

logger = get_logger(__name__)


class TracingMiddleware(BaseHTTPMiddleware):
    """FastAPI 请求追踪中间件：注入 request_id，记录请求耗时、异常和调用链。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        token = request_id_var.set(request_id)

        # 初始化调用链
        clear_request_flow()
        flow_token = request_flow_var.set([request.method])

        start = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000
            flow = get_request_flow()
            logger.info(
                "request method=%s path=%s status=%d duration_ms=%.2f flow=%s",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                flow,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            flow = get_request_flow()
            logger.exception(
                "request_failed method=%s path=%s duration_ms=%.2f flow=%s",
                request.method,
                request.url.path,
                duration_ms,
                flow,
            )
            raise
        finally:
            request_flow_var.reset(flow_token)
            request_id_var.reset(token)
