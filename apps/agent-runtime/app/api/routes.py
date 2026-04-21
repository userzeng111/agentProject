from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.domain.models import ChatRequest, ContinueDraftRequest, ResumeRequest, TaskCreateRequest
from app.llm.gateway_client import GatewayClientError
from app.storage.task_store import TaskNotFoundError


def build_router(
    task_service,
    engine=None,
    rag_service=None,
    rag_rebuild_service=None,
    style_profile_service=None,
    novel_skill_service=None,
) -> APIRouter:
    router = APIRouter()
    active_style_service = novel_skill_service or style_profile_service
    # 从 engine 获取 gateway_client 用于流式聊天
    _gateway_client = engine.gateway_client if engine else None

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

    def _apply_chat_rag(messages: list[dict[str, str]], payload: ChatRequest) -> list[dict[str, str]]:
        if rag_service is None or not payload.rag_enabled:
            return messages
        augmented_messages, _ = rag_service.augment_chat_messages(messages, top_k=payload.rag_top_k)
        return augmented_messages

    def _resolve_chat_model(requested_model: str | None) -> str:
        candidate = (requested_model or "").strip()
        if candidate:
            return candidate
        if engine is not None and hasattr(engine, "resolve_model"):
            return str(engine.resolve_model(None) or "").strip()
        return ""

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
            raise HTTPException(status_code=500, detail=f"更新默认模型失败：{exc}") from exc

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
            raise HTTPException(status_code=500, detail=f"读取 RAG 设置失败：{exc}") from exc

    @router.post("/settings/rag/rebuild")
    def rebuild_rag_library():
        if rag_rebuild_service is None:
            raise HTTPException(status_code=503, detail="RAG 重建服务未配置。")
        try:
            return rag_rebuild_service.rebuild()
        except Exception as exc:
            return {
                "success": False,
                "message": str(exc),
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
            raise _handle_error(exc) from exc

    @router.get("/dashboard")
    def get_dashboard():
        try:
            return task_service.get_dashboard()
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/archive")
    def get_archive(
        page: int = Query(1, ge=1, description="页码"),
        page_size: int = Query(10, ge=1, le=50, description="每页条数"),
    ):
        try:
            return task_service.get_archive_list(page=page, page_size=page_size)
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

    @router.post("/tasks/{task_id}/cancel")
    def cancel_task(task_id: str, payload: dict[str, str] | None = None):
        """取消一个正在运行或等待审核的任务。"""
        comment = (payload or {}).get("comment", "")
        try:
            return task_service.cancel_task(task_id, comment=comment)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.delete("/tasks/{task_id}")
    def delete_task(task_id: str):
        """删除一个已取消/已完成/失败的任务（不能删除运行中的任务）。"""
        try:
            return task_service.delete_task(task_id)
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

    @router.post("/tasks/{task_id}/continue")
    def continue_task(task_id: str, payload: ContinueDraftRequest):
        try:
            return task_service.continue_task(task_id, payload)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.post("/tasks/{task_id}/recover")
    def recover_task(task_id: str):
        try:
            return task_service.recover_task(task_id, force=True)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/workspace")
    def get_workspace(task_id: str):
        try:
            return task_service.get_workspace(task_id)
        except Exception as exc:
            raise _handle_error(exc) from exc

    @router.get("/tasks/{task_id}/supervisor")
    def get_supervisor(task_id: str):
        try:
            return task_service.get_supervisor_plan(task_id)
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

    @router.get("/tasks/{task_id}/chapters")
    def get_current_chapters(task_id: str):
        try:
            return {"task_id": task_id, "chapters": task_service.get_current_chapters(task_id)}
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

    # ── 流式聊天端点 ──

    @router.post("/chat/stream")
    async def chat_stream(payload: ChatRequest):
        """流式聊天端点，SSE 逐 token 返回。"""
        if _gateway_client is None:
            raise HTTPException(status_code=503, detail="模型网关未配置，请检查 .env 中的 LLM_BASE_URL 与 LLM_API_KEY。")

        messages = [{"role": m.role, "content": m.content} for m in payload.messages]
        if not messages:
            raise HTTPException(status_code=400, detail="messages 不能为空。")
        messages = _apply_chat_rag(messages, payload)

        resolved_model = _resolve_chat_model(payload.model)

        async def _sse_stream():
            try:
                async for chunk in _gateway_client.complete_stream(
                    messages=messages,
                    model=resolved_model,
                ):
                    data: dict[str, Any] = {
                        "content": chunk.content,
                    }
                    if chunk.reasoning_content:
                        data["reasoning_content"] = chunk.reasoning_content
                    if chunk.finish_reason:
                        data["finish_reason"] = chunk.finish_reason
                    if chunk.usage:
                        data["usage"] = chunk.usage
                    yield _sse_payload("chat.chunk", data)
                yield _sse_payload("chat.done", {"model": resolved_model})
            except GatewayClientError as exc:
                yield _sse_payload("chat.error", {"message": str(exc)})

        return StreamingResponse(
            _sse_stream(),
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
        if _gateway_client is None:
            raise HTTPException(status_code=503, detail="模型网关未配置。")

        messages = [{"role": m.role, "content": m.content} for m in payload.messages]
        if not messages:
            raise HTTPException(status_code=400, detail="messages 不能为空。")
        messages = _apply_chat_rag(messages, payload)

        resolved_model = _resolve_chat_model(payload.model)

        if payload.stream:
            # 流式模式：以 OpenAI 兼容 SSE 格式返回
            async def _openai_sse_stream():
                chat_id = f"chatcmpl-{uuid4().hex[:24]}"
                try:
                    # 首个 chunk：带 role
                    yield f"data: {json.dumps(_openai_chunk(chat_id, resolved_model, {'role': 'assistant', 'content': ''}), ensure_ascii=False)}\n\n"

                    async for chunk in _gateway_client.complete_stream(
                        messages=messages,
                        model=resolved_model,
                    ):
                        delta: dict[str, Any] = {}
                        if chunk.content:
                            delta["content"] = chunk.content
                        if chunk.reasoning_content:
                            delta["reasoning_content"] = chunk.reasoning_content
                        if not delta and not chunk.finish_reason:
                            continue
                        yield f"data: {json.dumps(_openai_chunk(chat_id, resolved_model, delta, chunk.finish_reason), ensure_ascii=False)}\n\n"

                    yield "data: [DONE]\n\n"
                except GatewayClientError as exc:
                    error_chunk = {"error": {"message": str(exc), "type": "gateway_error"}}
                    yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                _openai_sse_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            # 非流式模式：收集全部内容一次性返回
            try:
                full_content = ""
                full_reasoning = ""
                usage_data = {}
                async for chunk in _gateway_client.complete_stream(
                    messages=messages,
                    model=resolved_model,
                ):
                    full_content += chunk.content
                    full_reasoning += chunk.reasoning_content
                    if chunk.usage:
                        usage_data = chunk.usage
                message: dict[str, Any] = {"role": "assistant", "content": full_content}
                if full_reasoning:
                    message["reasoning_content"] = full_reasoning
                return {
                    "id": f"chatcmpl-{uuid4().hex[:24]}",
                    "object": "chat.completion",
                    "model": resolved_model,
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": usage_data,
                }
            except GatewayClientError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

    return router


def _openai_chunk(
    chat_id: str,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    """构造 OpenAI 兼容的 chunk 格式。"""
    from datetime import datetime, timezone

    return {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": int(datetime.now(timezone.utc).timestamp()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
