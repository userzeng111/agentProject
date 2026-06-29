import os
import time
from collections import defaultdict
from ipaddress import ip_address
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import build_router
from app.api.dynamic_routes import build_dynamic_router
from app.application.task_service import TaskService
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine
from app.novel_skills import NovelSkillService
from app.observability import TracingMiddleware, init_logging
from app.rag import NovelCorpusRebuildService, RagConfig, RagService
from app.services import ChatService
from app.settings.config import get_settings
from app.static_files import resolve_static_file
from app.style_profiles import StyleProfileService
from app.storage.task_store import TaskLogStore


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于内存的按 IP 限流中间件。

    - 通用接口：默认 60 请求 / 分钟
    - 聊天接口（/api/chat/）：默认 20 请求 / 分钟
    - 健康检查与 CORS 预检豁免
    - 每 10 分钟清理一次过期记录
    """

    _cleanup_interval = 600.0

    def __init__(
        self,
        app,
        general_limit: int = 60,
        chat_limit: int = 20,
        general_window: float = 60.0,
        chat_window: float = 60.0,
    ):
        super().__init__(app)
        self._general_limit = max(int(general_limit), 0)
        self._chat_limit = max(int(chat_limit), 0)
        self._general_window = max(float(general_window), 0.0)
        self._chat_window = max(float(chat_window), 0.0)
        self._last_cleanup = 0.0
        self._records: dict[tuple[str, str], list[float]] = defaultdict(list)

    async def dispatch(self, request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path in {"/health", "/api/health"}:
            return await call_next(request)
        # 静态资源请求豁免限流，避免首屏加载大量 JS/CSS chunk 触发 429
        if path.startswith("/_next/") or path.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2")):
            return await call_next(request)

        client_ip = request.client.host if request.client else ""
        # 本地回环地址豁免限流，便于开发调试与 E2E 全量测试
        if self._is_loopback_host(client_ip):
            return await call_next(request)
        now = time.time()

        # 定期清理过期条目
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup(now)
            self._last_cleanup = now

        is_chat = path.startswith("/api/chat/")
        scope = "chat" if is_chat else "general"
        limit = self._chat_limit if is_chat else self._general_limit
        window = self._chat_window if is_chat else self._general_window

        timestamps = self._records[(client_ip, scope)]
        # 移除窗口期外的旧记录
        cutoff = now - window
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)

        if limit > 0 and len(timestamps) >= limit:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试。"},
            )

        if limit > 0:
            timestamps.append(now)
        return await call_next(request)

    def _cleanup(self, now: float):
        for key, timestamps in list(self._records.items()):
            scope = key[1]
            window = self._chat_window if scope == "chat" else self._general_window
            cutoff = now - window
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)
            if not timestamps:
                del self._records[key]

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        if host == "localhost":
            return True
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False


class CacheControlMiddleware(BaseHTTPMiddleware):
    """为静态资源添加长期缓存，API 响应不缓存。"""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/_next/static/"):
            # 静态资源（带 hash）缓存 30 天
            response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        elif path.startswith("/api/"):
            # API 不缓存
            response.headers["Cache-Control"] = "no-store"
        else:
            # 其他（HTML 等）短缓存
            response.headers["Cache-Control"] = "public, max-age=60"
        return response


init_logging()

settings = get_settings()
store = TaskLogStore(root_dir=settings.tasklog_root)
engine = StoryEngine(settings)
model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
rag_service = RagService(RagConfig.from_env())
rag_rebuild_service = NovelCorpusRebuildService(RagConfig.from_env())
style_profile_service = StyleProfileService()
novel_skill_service = NovelSkillService(style_profile_service=style_profile_service)
auto_review_policy = {
    "auto_review_model_mode": settings.auto_review_model_mode,
    "auditor_model": settings.auto_review_auditor_model,
    "synthesis_model": settings.auto_review_synthesis_model,
    "outline_pass_threshold": 60.0,
    "outline_auto_escalate_on_critical": False,
    "outline_max_auto_revisions": 3,
    "chapter_pass_threshold": 65.0,
    "chapter_auto_escalate_on_critical": False,
    "chapter_max_auto_revisions": 3,
}
task_service = TaskService(
    store=store,
    engine=engine,
    model_catalog=model_catalog,
    rag_service=rag_service,
    novel_skill_service=novel_skill_service,
    style_profile_service=style_profile_service,
    auto_review=settings.auto_review,
    auto_review_policy=auto_review_policy,
)

chat_service = ChatService(
    gateway_client=engine.gateway_client,
    rag_service=rag_service,
    default_model_resolver=lambda: engine.resolve_model(None),
)

app = FastAPI(title=settings.app_name)


@app.on_event("shutdown")
async def close_gateway_clients() -> None:
    """关闭长期复用的模型网关连接池。"""
    gateway_client = getattr(engine, "gateway_client", None)
    if gateway_client is not None and hasattr(gateway_client, "aclose"):
        await gateway_client.aclose()

# 请求追踪中间件（放在最外层，确保捕获所有请求）
app.add_middleware(TracingMiddleware)

# 缓存控制中间件
app.add_middleware(CacheControlMiddleware)

_default_origins = [
    settings.runtime_origin,
    "http://localhost:3000",
    "http://localhost:3001",
]
_allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
if _allowed_origins:
    _default_origins = [o.strip() for o in _allowed_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)
app.add_middleware(
    RateLimitMiddleware,
    general_limit=settings.rate_limit_general_per_minute,
    chat_limit=settings.rate_limit_chat_per_minute,
)
app.include_router(
    build_router(
        task_service,
        chat_service=chat_service,
        rag_service=rag_service,
        rag_rebuild_service=rag_rebuild_service,
        novel_skill_service=novel_skill_service,
        style_profile_service=style_profile_service,
        settings=settings,
    ),
    prefix="/api",
)

# 动态 Agent 编排路由（v2 并行）
_dynamic_router = build_dynamic_router(
    gateway_client=engine.gateway_client if engine else None,
    default_model=engine.resolve_model(None) if engine else "",
)
app.include_router(_dynamic_router, prefix="/api/v2")

# 挂载前端静态文件（仅当 out 目录存在时）
# 优先使用环境变量配置，否则使用默认路径
_static_dir_str = settings.static_dir
if _static_dir_str:
    _static_dir = Path(_static_dir_str)
else:
    # 默认路径：相对于项目根目录的 apps/web/out
    _static_dir = Path(__file__).resolve().parents[3] / "apps" / "web" / "out"
if _static_dir.is_dir():
    _index_html = _static_dir / "index.html"

    # 先挂载静态资源目录（JS/CSS/图片等走 StaticFiles 高效服务）
    app.mount("/_next", StaticFiles(directory=str(_static_dir / "_next")), name="static-next")

    @app.get("/{path:path}")
    async def spa_fallback(request: Request, path: str):
        """SPA 回退：静态文件优先，否则返回 index.html 让前端路由接管。"""
        if path:
            # 尝试匹配静态文件
            candidate = resolve_static_file(_static_dir, path)
            if candidate is not None:
                return FileResponse(candidate)
            # 尝试 index.html（如 /archive/ → archive/index.html）
            index_candidate = resolve_static_file(_static_dir, f"{path.strip('/')}/index.html")
            if index_candidate is not None:
                return FileResponse(index_candidate)
        # 所有其他路径回退到 index.html（SPA 路由）
        return FileResponse(_index_html)
