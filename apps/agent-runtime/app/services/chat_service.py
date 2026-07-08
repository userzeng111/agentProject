from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.domain.models import ChatRequest
from app.llm.gateway_client import GatewayClientError
from app.observability import get_logger

logger = get_logger(__name__)


class ChatService:
    """聊天服务，封装与模型网关的交互及 RAG 增强逻辑。"""

    def __init__(self, gateway_client, rag_service=None, default_model_resolver=None):
        self.gateway_client = gateway_client
        self.rag_service = rag_service
        self._default_model_resolver = default_model_resolver

    def _apply_chat_rag(self, messages: list[dict[str, str]], payload: ChatRequest) -> list[dict[str, str]]:
        """根据请求对消息进行 RAG 增强。"""
        if self.rag_service is None or not payload.rag_enabled:
            return messages
        try:
            augmented_messages, _ = self.rag_service.augment_chat_messages(messages, top_k=payload.rag_top_k)
            return augmented_messages
        except Exception:
            logger.exception("RAG 增强失败，回退到原始消息 rag_top_k=%s", payload.rag_top_k)
            return messages

    def _resolve_chat_model(self, requested_model: str | None) -> str:
        """解析最终使用的模型 ID。"""
        candidate = (requested_model or "").strip()
        if candidate:
            return candidate
        if self._default_model_resolver is not None:
            candidate = str(self._default_model_resolver() or "").strip()
            if candidate:
                return candidate
        raise HTTPException(status_code=400, detail="未指定模型且系统默认模型不可用。")

    def _build_thinking_param(self, model_id: str) -> dict[str, Any] | None:
        """为支持 extended thinking 的模型构造 thinking 参数（Anthropic 协议）。"""
        if model_id == "K2.6":
            return {"type": "enabled", "budget_tokens": 1024}
        return None

    def _sse_payload(self, event_name: str, payload: dict) -> str:
        """构造 SSE 事件 payload。"""
        return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def chat_stream(self, payload: ChatRequest):
        """流式聊天，返回 SSE 异步生成器。"""
        if self.gateway_client is None:
            raise HTTPException(status_code=503, detail="模型网关未配置，请检查 .env 中的 LLM_BASE_URL 与 LLM_API_KEY。")

        messages = [{"role": m.role, "content": m.content} for m in payload.messages]
        if not messages:
            raise HTTPException(status_code=400, detail="messages 不能为空。")
        messages = self._apply_chat_rag(messages, payload)

        resolved_model = self._resolve_chat_model(payload.model)

        async def _sse_stream():
            try:
                thinking_param = self._build_thinking_param(resolved_model)
                async for chunk in self.gateway_client.complete_stream(
                    messages=messages,
                    model=resolved_model,
                    **({"thinking": thinking_param} if thinking_param else {}),
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
                    yield self._sse_payload("chat.chunk", data)
                yield self._sse_payload("chat.done", {"model": resolved_model})
            except GatewayClientError as exc:
                logger.exception("流式聊天网关错误 model=%s", resolved_model)
                yield self._sse_payload("chat.error", {"message": str(exc)})

        return _sse_stream()

    async def chat_completions(self, payload: ChatRequest):
        """OpenAI 兼容端点，同时支持流式和非流式。"""
        if self.gateway_client is None:
            raise HTTPException(status_code=503, detail="模型网关未配置。")

        messages = [{"role": m.role, "content": m.content} for m in payload.messages]
        if not messages:
            raise HTTPException(status_code=400, detail="messages 不能为空。")
        messages = self._apply_chat_rag(messages, payload)

        resolved_model = self._resolve_chat_model(payload.model)

        if payload.stream:
            # 流式模式：以 OpenAI 兼容 SSE 格式返回
            async def _openai_sse_stream():
                chat_id = f"chatcmpl-{uuid4().hex[:24]}"
                try:
                    # 首个 chunk：带 role
                    yield f"data: {json.dumps(_openai_chunk(chat_id, resolved_model, {'role': 'assistant', 'content': ''}), ensure_ascii=False)}\n\n"

                    thinking_param = self._build_thinking_param(resolved_model)
                    async for chunk in self.gateway_client.complete_stream(
                        messages=messages,
                        model=resolved_model,
                        **({"thinking": thinking_param} if thinking_param else {}),
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
                    logger.exception("OpenAI 流式聊天网关错误 model=%s", resolved_model)
                    error_chunk = {"error": {"message": str(exc), "type": "gateway_error"}}
                    yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"

            return _openai_sse_stream()
        else:
            # 非流式模式：收集全部内容一次性返回
            try:
                full_content = ""
                full_reasoning = ""
                usage_data = {}
                thinking_param = self._build_thinking_param(resolved_model)
                async for chunk in self.gateway_client.complete_stream(
                    messages=messages,
                    model=resolved_model,
                    **({"thinking": thinking_param} if thinking_param else {}),
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
                logger.exception("OpenAI 非流式聊天网关错误 model=%s", resolved_model)
                raise HTTPException(status_code=502, detail=str(exc)) from exc


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
