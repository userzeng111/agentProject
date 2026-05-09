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
from app.style_profiles import StyleProfileService
from app.storage.task_store import TaskLogStore


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.runtime_origin,
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
        "https://app.yuegui666.icu",
        "https://api.yuegui666.icu",
        "https://yuegui666.icu",
        "https://agentproject.pages.dev",
    ],
    allow_origin_regex=r"^https?://((localhost)|(127\.0\.0\.1)|(\d{1,3}(\.\d{1,3}){3}))(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(
    build_router(
        task_service,
        chat_service=chat_service,
        rag_service=rag_service,
        rag_rebuild_service=rag_rebuild_service,
        novel_skill_service=novel_skill_service,
        style_profile_service=style_profile_service,
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
_static_dir = Path("/home/user01/WorkSpace/AgentProject/apps/web/out")
if _static_dir.is_dir():
    _index_html = _static_dir / "index.html"

    # 先挂载静态资源目录（JS/CSS/图片等走 StaticFiles 高效服务）
    app.mount("/_next", StaticFiles(directory=str(_static_dir / "_next")), name="static-next")

    @app.get("/{path:path}")
    async def spa_fallback(request: Request, path: str):
        """SPA 回退：静态文件优先，否则返回 index.html 让前端路由接管。"""
        if path:
            # 尝试匹配静态文件
            candidate = _static_dir / path.strip("/")
            if candidate.is_file():
                return FileResponse(candidate)
            # 尝试 index.html（如 /archive/ → archive/index.html）
            index_candidate = _static_dir / path.strip("/") / "index.html"
            if index_candidate.is_file():
                return FileResponse(index_candidate)
        # 所有其他路径回退到 index.html（SPA 路由）
        return FileResponse(_index_html)
