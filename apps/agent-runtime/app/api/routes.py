from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.domain.models import ResumeRequest, TaskCreateRequest
from app.storage.task_store import TaskNotFoundError


def build_router(task_service) -> APIRouter:
    router = APIRouter()

    def _handle_error(exc: Exception) -> HTTPException:
        if isinstance(exc, TaskNotFoundError):
            return HTTPException(status_code=404, detail="任务不存在")
        if isinstance(exc, FileNotFoundError):
            return HTTPException(status_code=404, detail="文件不存在")
        if isinstance(exc, ValueError):
            return HTTPException(status_code=400, detail=str(exc))
        return HTTPException(status_code=500, detail="服务内部错误")

    def _sse_payload(event_name: str, payload: dict) -> str:
        return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _split_file_ref(ref: str) -> tuple[str, str]:
        parts = [item for item in ref.removeprefix("/").split("/") if item]
        if len(parts) < 4 or parts[0] != "tasklog":
            raise ValueError("文件引用格式不正确。")
        task_id = parts[2]
        relative_path = "/".join(parts[3:])
        if not task_id or not relative_path:
            raise ValueError("文件引用格式不完整。")
        return task_id, relative_path

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/models")
    def list_models():
        try:
            return task_service.list_models_payload()
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"读取模型列表失败：{exc}") from exc

    @router.post("/tasks")
    def create_task(payload: TaskCreateRequest):
        return task_service.create_task(payload)

    @router.get("/dashboard")
    def get_dashboard():
        try:
            return task_service.get_dashboard()
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/archive")
    def get_archive():
        try:
            return task_service.get_archive_list()
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/archive/{task_id}")
    def get_archive_detail(task_id: str):
        try:
            return task_service.get_archive_detail(task_id)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}")
    def get_task(task_id: str):
        try:
            return task_service.get_task(task_id)
        except Exception as exc:
            raise _handle_error(exc) from exc

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
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="当前 demo 仅支持 UTF-8 文本文件。") from exc
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/run")
    def run_task(task_id: str):
        try:
            return task_service.run_task(task_id)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/resume")
    def resume_task(task_id: str, payload: ResumeRequest):
        try:
            return task_service.resume_task(
                task_id,
                approved=payload.approved,
                comment=payload.comment,
            )
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/workspace")
    def get_workspace(task_id: str):
        try:
            return task_service.get_workspace(task_id)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/review")
    def get_review(task_id: str):
        try:
            return task_service.get_review(task_id)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/result")
    def get_result(task_id: str):
        try:
            return task_service.get_result(task_id)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/file-text")
    def get_file_text(ref: str = Query(..., description="tasklog 相对路径")):
        try:
            task_id, relative_path = _split_file_ref(ref)
            content = task_service.read_file_text(task_id, relative_path)
            return PlainTextResponse(content, media_type="text/plain; charset=utf-8")
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/files/{path:path}")
    def get_task_file_text(task_id: str, path: str):
        try:
            content = task_service.read_file_text(task_id, path)
            return PlainTextResponse(content, media_type="text/plain; charset=utf-8")
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/workspace/stream")
    @router.get("/tasks/{task_id}/workspace/events")
    @router.get("/tasks/{task_id}/sse")
    @router.get("/tasks/{task_id}/events/stream")
    async def stream_task_events(task_id: str):
        try:
            snapshot = task_service.build_sse_snapshot(task_id)
            queue = task_service.subscribe_task_events(task_id)
        except Exception as exc:
            raise _handle_error(exc) from exc

        async def event_stream():
            try:
                yield _sse_payload("snapshot", snapshot)
                while True:
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield _sse_payload("task.event", payload)
                    if payload.get("event_type") in {"task.completed", "task.cancelled", "task.failed"}:
                        yield _sse_payload(
                            "task.done",
                            {"task_id": task_id, "event_type": payload.get("event_type")},
                        )
                        break
            finally:
                task_service.unsubscribe_task_events(task_id, queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/tasks/{task_id}/artifacts")
    def list_artifacts(task_id: str):
        try:
            return task_service.list_artifacts(task_id)
        except Exception as exc:
            raise _handle_error(exc) from exc

    return router
