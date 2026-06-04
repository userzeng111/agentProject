from __future__ import annotations

import asyncio
import json

from app.observability import get_logger

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.domain.models import ChatRequest, ContinueDraftRequest, RecoveryRequest, ResumeRequest, RollbackChapterPlanRequest, TaskActionRequest, TaskCreateRequest
from app.storage.task_store import TaskNotFoundError

logger = get_logger(__name__)


def build_router(
    task_service,
    chat_service=None,
    rag_service=None,
    rag_rebuild_service=None,
    style_profile_service=None,
    novel_skill_service=None,
    settings=None,
) -> APIRouter:
    router = APIRouter()
    active_style_service = novel_skill_service or style_profile_service

    def _handle_error(exc: Exception) -> HTTPException:
        if isinstance(exc, TaskNotFoundError):
            return HTTPException(status_code=404, detail="任务不存在")
        if isinstance(exc, FileNotFoundError):
            return HTTPException(status_code=404, detail="文件不存在")
        if isinstance(exc, ValueError):
            return HTTPException(status_code=400, detail=str(exc))
        if isinstance(exc, PermissionError):
            return HTTPException(status_code=403, detail="权限不足")
        logger.exception("内部错误")
        return HTTPException(status_code=500, detail="服务内部错误，请稍后重试")

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

    async def _read_upload_text(file: UploadFile) -> str:
        max_bytes = max(int(getattr(settings, "upload_max_bytes", 2 * 1024 * 1024) or 0), 1)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(status_code=413, detail=f"文件过大，最大允许 {max_bytes} 字节。")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/models")
    def list_models(refresh: bool = Query(False, description="是否强制绕过服务端缓存刷新模型目录")):
        try:
            return task_service.list_models_payload(force_refresh=refresh)
        except Exception as exc:  # pragma: no cover
            logger.exception("读取模型列表失败")
            raise HTTPException(status_code=500, detail=f"读取模型列表失败：{exc}") from exc

    @router.patch("/settings/default-model")
    def update_default_model(payload: dict[str, str]):
        model_id = payload.get("model_id", "").strip()
        if not model_id:
            raise HTTPException(status_code=400, detail="model_id 不能为空。")
        try:
            return task_service.update_default_model(model_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("更新默认模型失败")
            raise HTTPException(status_code=500, detail=f"更新默认模型失败：{exc}") from exc

    @router.get("/settings/protocols")
    def get_protocol_settings():
        from app.settings.runtime_settings import get_model_protocol_overrides
        default_protocol = getattr(settings, "default_protocol", "openai") if settings is not None else "openai"
        effective_overrides = (
            getattr(settings, "effective_protocol_overrides", None)
            if settings is not None
            else None
        )
        return {
            "default_protocol": default_protocol,
            "overrides": effective_overrides or get_model_protocol_overrides(),
        }

    @router.patch("/settings/protocols/{model_id}")
    def update_model_protocol(model_id: str, payload: dict[str, str]):
        from app.settings.runtime_settings import set_model_protocol_override
        protocol = payload.get("protocol", "").strip()
        if protocol not in {"openai", "anthropic"}:
            raise HTTPException(status_code=400, detail="protocol 必须是 openai 或 anthropic")
        set_model_protocol_override(model_id, protocol)
        return {"model_id": model_id, "protocol": protocol}

    @router.delete("/settings/protocols/{model_id}")
    def delete_model_protocol(model_id: str):
        from app.settings.runtime_settings import remove_model_protocol_override
        remove_model_protocol_override(model_id)
        return {"model_id": model_id}

    @router.get("/settings/rag")
    def get_rag_status():
        if rag_rebuild_service is None:
            return {
                "available": False,
                "library_dir": "",
                "faiss_index_path": "",
                "sqlite_path": "",
                "sources": [],
                "last_result": None,
            }
        try:
            return rag_rebuild_service.get_status()
        except Exception as exc:
            logger.exception("读取 RAG 设置失败")
            raise HTTPException(status_code=500, detail=f"读取 RAG 设置失败：{exc}") from exc

    @router.post("/settings/rag/rebuild")
    def rebuild_rag_library():
        if rag_rebuild_service is None:
            raise HTTPException(status_code=503, detail="RAG 重建服务未配置。")
        try:
            return rag_rebuild_service.rebuild()
        except Exception:
            logger.exception("RAG 重建失败")
            return {
                "success": False,
                "message": "RAG 重建失败，请检查配置或稍后重试。",
                "scanned_files": 0,
                "indexed_documents": 0,
                "output_dir": "",
                "duration_ms": 0,
                "sources": [],
                "warnings": [],
            }

    @router.get("/style-profiles")
    def list_style_profiles():
        if active_style_service is None:
            return {"items": []}
        try:
            if hasattr(active_style_service, "list_style_profiles"):
                return {"items": active_style_service.list_style_profiles()}
            return {"items": active_style_service.list_profiles()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取风格实例失败：{exc}") from exc

    @router.post("/tasks")
    def create_task(payload: TaskCreateRequest):
        try:
            return task_service.create_task(payload)
        except Exception as exc:
            logger.exception("创建任务失败")
            raise _handle_error(exc) from exc

    @router.get("/dashboard")
    def get_dashboard():
        try:
            return task_service.get_dashboard()
        except Exception as exc:
            logger.exception("获取仪表盘失败")
            raise _handle_error(exc) from exc

    @router.get("/archive")
    def get_archive(
        page: int = Query(1, ge=1, description="页码"),
        page_size: int = Query(10, ge=1, le=50, description="每页条数"),
    ):
        try:
            return task_service.get_archive_list(page=page, page_size=page_size)
        except Exception as exc:
            logger.exception("获取归档列表失败")
            raise _handle_error(exc) from exc

    @router.get("/archive/{task_id}")
    def get_archive_detail(task_id: str):
        try:
            return task_service.get_archive_detail(task_id)
        except Exception as exc:
            logger.exception("获取归档详情失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}")
    def get_task(task_id: str):
        try:
            return task_service.get_task(task_id)
        except Exception as exc:
            logger.exception("获取任务失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/cancel")
    def cancel_task(task_id: str, payload: dict[str, str] | None = None):
        """取消一个正在运行或等待审核的任务。"""
        comment = (payload or {}).get("comment", "")
        try:
            return task_service.cancel_task(task_id, comment=comment)
        except Exception as exc:
            logger.exception("取消任务失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.delete("/tasks/{task_id}")
    def delete_task(task_id: str):
        """删除一个已取消/已完成/失败的任务（不能删除运行中的任务）。"""
        try:
            return task_service.delete_task(task_id)
        except Exception as exc:
            logger.exception("删除任务失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/assets")
    async def upload_asset(task_id: str, file: UploadFile = File(...)):
        try:
            content = await _read_upload_text(file)
            return task_service.add_source(
                task_id,
                filename=file.filename or "reference.txt",
                media_type=file.content_type or "text/plain",
                content=content,
            )
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="当前 demo 仅支持 UTF-8 文本文件。") from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("上传资源失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/run")
    def run_task(task_id: str, payload: TaskActionRequest | None = None):
        try:
            return task_service.run_task(task_id, model_id=(payload.model_id if payload else ""))
        except Exception as exc:
            logger.exception("运行任务失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/resume")
    def resume_task(task_id: str, payload: ResumeRequest):
        try:
            return task_service.resume_task(
                task_id,
                approved=payload.approved,
                comment=payload.comment,
                model_id=payload.model_id,
            )
        except Exception as exc:
            logger.exception("恢复任务失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/continue")
    def continue_task(task_id: str, payload: ContinueDraftRequest):
        try:
            if hasattr(task_service, "queue_continue_task"):
                return task_service.queue_continue_task(task_id, payload)
            return task_service.continue_task(task_id, payload)
        except Exception as exc:
            logger.exception("继续任务失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/recover")
    def recover_task(task_id: str, payload: RecoveryRequest | None = None):
        try:
            return task_service.recover_task(
                task_id,
                force=True,
                model_id=(payload.model_id if payload else ""),
                recovery_mode=(payload.recovery_mode.value if payload else "recover_to_stable"),
            )
        except Exception as exc:
            logger.exception("恢复任务失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/rollback-chapter-plan")
    def rollback_chapter_plan(task_id: str, payload: RollbackChapterPlanRequest):
        try:
            return task_service.rollback_chapter_plan(task_id, payload.keep_batch_count)
        except Exception as exc:
            logger.exception("回滚章节计划失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/workspace")
    def get_workspace(task_id: str):
        try:
            return task_service.get_workspace(task_id)
        except Exception as exc:
            logger.exception("获取工作区失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/supervisor")
    def get_supervisor(task_id: str):
        try:
            return task_service.get_supervisor_plan(task_id)
        except Exception as exc:
            logger.exception("获取 Supervisor 计划失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/review")
    def get_review(task_id: str):
        try:
            return task_service.get_review(task_id)
        except Exception as exc:
            logger.exception("获取审核结果失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/result")
    def get_result(task_id: str):
        try:
            return task_service.get_result(task_id)
        except Exception as exc:
            logger.exception("获取结果失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/chapters")
    def get_current_chapters(task_id: str):
        try:
            return {"task_id": task_id, "chapters": task_service.get_current_chapters(task_id)}
        except Exception as exc:
            logger.exception("获取章节失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    @router.get("/file-text")
    def get_file_text(ref: str = Query(..., description="tasklog 相对路径")):
        try:
            task_id, relative_path = _split_file_ref(ref)
            content = task_service.read_file_text(task_id, relative_path)
            return PlainTextResponse(content, media_type="text/plain; charset=utf-8")
        except Exception as exc:
            logger.exception("读取文件失败 ref=%s", ref)
            raise _handle_error(exc) from exc

    import re
    _SAFE_PATH_RE = re.compile(r"^[a-zA-Z0-9_\-][a-zA-Z0-9_\-\./]*$")

    @router.get("/tasks/{task_id}/files/{path:path}")
    def get_task_file_text(task_id: str, path: str):
        if ".." in path or not _SAFE_PATH_RE.match(path):
            raise HTTPException(status_code=400, detail="非法文件路径。")
        normalized = path.lstrip("/")
        if not normalized:
            raise HTTPException(status_code=400, detail="文件路径不能为空。")
        try:
            content = task_service.read_file_text(task_id, normalized)
            return PlainTextResponse(content, media_type="text/plain; charset=utf-8")
        except Exception as exc:
            logger.exception("读取任务文件失败 task_id=%s path=%s", task_id, path)
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
                    # 检查任务是否已终止但事件队列为空，避免永久挂起
                    try:
                        latest = task_service.store.get(task_id)
                        if latest.status.value in {"completed", "cancelled", "failed"}:
                            yield _sse_payload(
                                "task.done",
                                {"task_id": task_id, "event_type": f"task.{latest.status.value}"},
                            )
                            break
                    except Exception:
                        pass
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
            logger.exception("列出产物失败 task_id=%s", task_id)
            raise _handle_error(exc) from exc

    # ── 流式聊天端点 ──

    @router.post("/chat/stream")
    async def chat_stream(payload: ChatRequest):
        """流式聊天端点，SSE 逐 token 返回。"""
        if chat_service is None:
            raise HTTPException(status_code=503, detail="聊天服务未配置。")

        try:
            stream = await chat_service.chat_stream(payload)
        except HTTPException:
            raise
        except Exception:
            logger.exception("聊天流初始化失败")
            raise HTTPException(status_code=500, detail="聊天服务内部错误，请稍后重试。")

        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/chat/completions")
    async def chat_completions(payload: ChatRequest):
        """OpenAI 兼容端点，同时支持流式和非流式。"""
        if chat_service is None:
            raise HTTPException(status_code=503, detail="聊天服务未配置。")

        try:
            result = await chat_service.chat_completions(payload)
        except HTTPException:
            raise
        except Exception:
            logger.exception("聊天补全初始化失败")
            raise HTTPException(status_code=500, detail="聊天服务内部错误，请稍后重试。")

        # 如果返回的是异步生成器，则包装为 StreamingResponse
        if hasattr(result, "__aiter__"):
            return StreamingResponse(
                result,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        return result

    return router
