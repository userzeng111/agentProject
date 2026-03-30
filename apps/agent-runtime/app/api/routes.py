from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.domain.models import ResumeRequest, TaskCreateRequest
from app.storage.task_store import TaskNotFoundError


def build_router(task_service) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/models")
    def list_models():
        try:
            return {"data": task_service.list_models()}
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"读取模型列表失败：{exc}") from exc

    @router.post("/tasks")
    def create_task(payload: TaskCreateRequest):
        return task_service.create_task(payload)

    @router.get("/tasks/{task_id}")
    def get_task(task_id: str):
        try:
            return task_service.get_task(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @router.post("/tasks/{task_id}/assets")
    async def upload_asset(task_id: str, file: UploadFile = File(...)):
        try:
            content = (await file.read()).decode("utf-8")
            return task_service.add_source(
                task_id,
                filename=file.filename or "reference.txt",
                media_type=file.content_type or "text/plain",
                content=content,
            )
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="当前 demo 仅支持 UTF-8 文本文件。") from exc

    @router.post("/tasks/{task_id}/run")
    def run_task(task_id: str):
        try:
            return task_service.run_task(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover
            task_service.store.set_failed(task_id, f"运行失败：{exc}")
            raise HTTPException(status_code=500, detail="运行时内部错误") from exc

    @router.post("/tasks/{task_id}/resume")
    def resume_task(task_id: str, payload: ResumeRequest):
        try:
            return task_service.resume_task(task_id, approved=payload.approved, comment=payload.comment)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover
            task_service.store.set_failed(task_id, f"恢复执行失败：{exc}")
            raise HTTPException(status_code=500, detail="恢复执行时发生内部错误") from exc

    @router.get("/tasks/{task_id}/artifacts")
    def list_artifacts(task_id: str):
        try:
            return task_service.list_artifacts(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    return router
