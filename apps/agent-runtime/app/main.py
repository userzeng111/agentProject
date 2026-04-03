from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import build_router
from app.application.task_service import TaskService
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine
from app.settings.config import get_settings
from app.storage.task_store import TaskLogStore


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.runtime_origin,
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
    ],
    allow_origin_regex=r"^https?://((localhost)|(127\.0\.0\.1)|(\d{1,3}(\.\d{1,3}){3}))(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(build_router(task_service), prefix="/api")
