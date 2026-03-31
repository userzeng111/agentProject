from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import build_router
from app.application.task_service import TaskService
from app.llm.story_engine import StoryEngine
from app.settings.config import get_settings
from app.storage.task_store import TaskLogStore


settings = get_settings()
store = TaskLogStore(root_dir=settings.tasklog_root)
engine = StoryEngine(settings)
task_service = TaskService(store=store, engine=engine)

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
