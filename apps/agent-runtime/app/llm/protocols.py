from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StreamChunk:
    """流式响应的单个 chunk。

    与 gateway_client.py 中的 StreamChunk 保持语义一致，
    用于 ProtocolAdapter.parse_stream_chunk 的返回结构。
    """

    __slots__ = ("content", "reasoning_content", "finish_reason", "model", "usage")

    def __init__(
        self,
        *,
        content: str = "",
        reasoning_content: str = "",
        finish_reason: str | None = None,
        model: str = "",
        usage: dict[str, Any] | None = None,
    ) -> None:
        self.content = content
        self.reasoning_content = reasoning_content
        self.finish_reason = finish_reason
        self.model = model
        self.usage = usage or {}


class ProtocolAdapter(ABC):
    """LLM 网关协议适配器抽象基类。

    子类需实现 OpenAI、Anthropic 等不同协议的 endpoint、请求体构造与响应解析。
    """

    @abstractmethod
    def get_endpoint(self) -> str:
        """返回聊天补全的 endpoint 路径，如 '/chat/completions' 或 '/v1/messages'。"""
        ...

    @abstractmethod
    def build_payload(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """构造请求体。"""
        ...

    @abstractmethod
    def parse_completion_response(self, response_json: dict[str, Any]) -> str:
        """解析非流式响应的 JSON，返回文本内容。"""
        ...

    @abstractmethod
    def parse_stream_chunk(self, chunk_data: dict[str, Any]) -> dict[str, Any] | None:
        """解析单个流式 chunk 的 JSON。

        返回字典格式::

            {
                "content": str,
                "reasoning_content": str,
                "finish_reason": str | None,
                "usage": dict | None,
            }

        或 None（表示该 chunk 无需向下游传递）。
        """
        ...


def _extract_system_message(
    messages: list[dict[str, str]],
) -> tuple[str | None, list[dict[str, str]]]:
    """提取 system 消息，返回 (system_content, 过滤后的 messages)。"""
    system_content: str | None = None
    filtered: list[dict[str, str]] = []
    for msg in messages:
        if msg.get("role") == "system":
            # 若存在多条 system 消息，以第一条为准；后续可扩展为拼接
            if system_content is None:
                system_content = msg.get("content", "")
        else:
            filtered.append(msg)
    return system_content, filtered


class OpenAIAdapter(ProtocolAdapter):
    """OpenAI 兼容协议适配器。"""

    def get_endpoint(self) -> str:
        return "/chat/completions"

    def build_payload(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        payload.update(kwargs)
        return payload

    def parse_completion_response(self, response_json: dict[str, Any]) -> str:
        return response_json["choices"][0]["message"]["content"]

    def parse_stream_chunk(self, chunk_data: dict[str, Any]) -> dict[str, Any] | None:
        choices = chunk_data.get("choices") or []
        if not choices:
            usage = chunk_data.get("usage")
            if usage:
                return {
                    "content": "",
                    "reasoning_content": "",
                    "finish_reason": None,
                    "usage": usage,
                }
            return None

        choice = choices[0]
        delta = choice.get("delta") or {}
        content = delta.get("content") or ""
        reasoning_content = delta.get("reasoning_content") or ""
        finish_reason = choice.get("finish_reason")
        return {
            "content": content,
            "reasoning_content": reasoning_content,
            "finish_reason": finish_reason,
            "usage": None,
        }


class AnthropicAdapter(ProtocolAdapter):
    """Anthropic Messages API 协议适配器。"""

    def get_endpoint(self) -> str:
        return "/messages"

    def build_payload(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        system_content, filtered_messages = _extract_system_message(messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": filtered_messages,
            "stream": stream,
        }
        if system_content is not None:
            payload["system"] = system_content
        # 仅在 kwargs 未显式提供 max_tokens 时才使用默认值 4096
        if "max_tokens" not in kwargs:
            payload["max_tokens"] = 4096
        payload.update(kwargs)
        # 若调用方显式传入 max_tokens=None，则不在 payload 中发送该字段
        if payload.get("max_tokens") is None:
            payload.pop("max_tokens", None)
        return payload

    def parse_completion_response(self, response_json: dict[str, Any]) -> str:
        content_blocks = response_json.get("content") or []
        if content_blocks and content_blocks[0].get("type") == "text":
            return content_blocks[0]["text"]
        return ""

    def parse_stream_chunk(self, chunk_data: dict[str, Any]) -> dict[str, Any] | None:
        chunk_type = chunk_data.get("type")

        if chunk_type == "content_block_delta":
            delta = chunk_data.get("delta") or {}
            if delta.get("type") == "text_delta":
                return {
                    "content": delta.get("text", ""),
                    "reasoning_content": "",
                    "finish_reason": None,
                    "usage": None,
                }
            if delta.get("type") == "thinking_delta":
                return {
                    "content": "",
                    "reasoning_content": delta.get("thinking", ""),
                    "finish_reason": None,
                    "usage": None,
                }
            return None

        if chunk_type == "message_delta":
            delta = chunk_data.get("delta") or {}
            stop_reason = delta.get("stop_reason")
            # Anthropic 的 stop_reason 映射为 finish_reason
            finish_reason = stop_reason if stop_reason else None
            usage = chunk_data.get("usage")
            if usage and "total_tokens" not in usage:
                usage = dict(usage)
                usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            return {
                "content": "",
                "reasoning_content": "",
                "finish_reason": finish_reason,
                "usage": usage,
            }

        # 以下类型为控制消息，无需向下游传递
        if chunk_type in (
            "message_start",
            "content_block_start",
            "content_block_stop",
            "message_stop",
        ):
            return None

        return None
