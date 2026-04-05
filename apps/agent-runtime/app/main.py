from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api.routes import build_router
from app.application.task_service import TaskService
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine
from app.settings.config import get_settings
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


settings = get_settings()
store = TaskLogStore(root_dir=settings.tasklog_root)
engine = StoryEngine(settings)
model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
auto_review_policy = {
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
    auto_review=settings.auto_review,
    auto_review_policy=auto_review_policy,
)

app = FastAPI(title=settings.app_name)

# 缓存控制中间件（必须在 CORS 之后）
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
app.include_router(build_router(task_service, engine=engine), prefix="/api")

# 挂载前端静态文件（仅当 out 目录存在时）
_static_dir = Path("/home/user01/WorkSpace/AgentProject/apps/web/out")
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
