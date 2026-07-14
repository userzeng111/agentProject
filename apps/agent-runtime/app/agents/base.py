"""
Agent 基类

所有具体 Agent 的公共父类，提供完整的 Agent 通用能力：
- Skill YAML 加载与管理
- gateway_client 守卫
- 流式 LLM 调用（支持思考链透传）
- JSON 解析与清理
- LLM 调用 + JSON 解析 + 重试
- 子类按需扩展业务方法
"""

from __future__ import annotations

import json
from app.observability import get_logger
from collections.abc import Callable
from pathlib import Path
import time
from typing import Any

from app.agents.loader import SkillLoader
from app.llm.gateway_client import (
    GatewayClientError,
    OpenAICompatibleGatewayClient,
    StreamInterruptedAfterStartError,
)

logger = get_logger(__name__)

# JSON 重试提示词（全局共享）
_RETRY_JSON_PROMPT = (
    "上一次返回结果不是可解析的目标 JSON。"
    "请重新输出一个完整、可解析的 JSON 对象。"
    "不要输出 Markdown 代码围栏，不要解释，不要补充说明，只返回最终 JSON 对象。"
)


class BaseAgent:
    """
    Agent 基类。

    提供所有 Agent 共享的核心能力：
    - Skill YAML 加载（通过 _skill_subdir 指定子目录）
    - gateway_client 守卫
    - 流式 LLM 调用（含思考链透传）
    - JSON 解析与清理
    - LLM 调用 + JSON 解析 + 自动重试

    子类只需设置 _skill_subdir 并按需扩展业务方法。
    """

    _skill_subdir: str  # 子类必须设置：story_engine / auto_reviewer

    def __init__(
        self,
        gateway_client: OpenAICompatibleGatewayClient | None = None,
    ) -> None:
        self.gateway_client = gateway_client
        self._skill_loader: SkillLoader | None = None
        self._skills_loaded: bool = False

    # ── Skill 加载 ──────────────────────────────

    def _load_skills(self) -> None:
        """加载 _skill_subdir 目录下的 Skill YAML，失败时静默 fallback。"""
        try:
            skills_root = Path(__file__).parent / "skills" / self._skill_subdir
            self._skill_loader = SkillLoader(skills_root)
            registry = self._skill_loader.load_all()
            if registry:
                self._skills_loaded = True
                logger.info(
                    "%s 已加载 %d 个 Skill: %s",
                    self.__class__.__name__,
                    len(registry),
                    list(registry.keys()),
                )
        except Exception as exc:
            logger.warning("Skill YAML 加载失败，使用内置 prompt fallback: %s", exc)
            self._skills_loaded = False

    # ── Gateway 守卫 ────────────────────────────

    def _require_gateway_client(self) -> OpenAICompatibleGatewayClient:
        """返回 gateway_client，未配置时抛出 GatewayClientError。"""
        if self.gateway_client is None:
            raise GatewayClientError(
                "当前没有可用的模型网关，请检查 apps/agent-runtime/.env 中的 LLM_BASE_URL 与 LLM_API_KEY 配置。"
            )
        return self.gateway_client

    # ── 流式 LLM 调用 ────────────────────────────

    def _call_llm_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stage: str = "",
        unit_id: str = "",
        max_tokens: int | None = None,
        request_options: dict[str, Any] | None = None,
    ) -> str:
        """
        流式调用 LLM，返回完整文本内容。

        可选通过 progress_callback 透传思考链事件。
        """
        content, _, _ = self._call_llm_stream_with_metadata(
            messages,
            model,
            progress_callback=progress_callback,
            stage=stage,
            unit_id=unit_id,
            max_tokens=max_tokens,
            request_options=request_options,
        )
        return content

    def _call_llm_stream_with_metadata(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stage: str = "",
        unit_id: str = "",
        max_tokens: int | None = None,
        request_options: dict[str, Any] | None = None,
    ) -> tuple[str, str | None, dict[str, Any]]:
        """流式调用 LLM，返回完整文本内容、终止原因和耗时元数据。"""
        gc = self._require_gateway_client()
        full_content = ""
        full_reasoning = ""
        finish_reason: str | None = None
        saw_stream_output = False
        request_kwargs: dict[str, Any] = dict(request_options or {})
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        request_kwargs["_obs_stage"] = stage
        request_kwargs["_obs_exchange_label"] = unit_id
        started = time.perf_counter()
        first_token_ms: float | None = None
        try:
            for chunk in gc.complete_stream_sync(messages, model=model, **request_kwargs):
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                if chunk.usage and progress_callback:
                    progress_callback({
                        "event_type": "model.usage",
                        "stage": stage,
                        "unit_id": unit_id,
                        "message": "模型调用用量已更新。",
                        "payload": {
                            **chunk.usage,
                            "model": chunk.model or model,
                            "finish_reason": chunk.finish_reason,
                        },
                    })
                if chunk.reasoning_content:
                    saw_stream_output = True
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - started) * 1000
                    full_reasoning += chunk.reasoning_content
                    if progress_callback:
                        progress_callback({
                            "event_type": "model.thinking",
                            "stage": stage,
                            "unit_id": unit_id,
                            "message": "模型思考中...",
                            "payload": {
                                "reasoning_chunk": chunk.reasoning_content,
                                "accumulated_length": len(full_reasoning),
                                "model": chunk.model,
                                "finish_reason": chunk.finish_reason,
                            },
                        })
                if chunk.content:
                    saw_stream_output = True
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - started) * 1000
                    full_content += chunk.content
        except Exception as exc:
            if saw_stream_output:
                raise StreamInterruptedAfterStartError(
                    "流式响应已开始后中断，已保留最近稳定阶段，请从恢复入口继续。"
                ) from exc
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        return full_content, finish_reason, {
            "stage": stage,
            "exchange_label": unit_id,
            "model": model,
            "first_token_ms": first_token_ms,
            "duration_ms": duration_ms,
            "finish_reason": finish_reason,
            "content_chars": len(full_content),
            "reasoning_chars": len(full_reasoning),
            "status": "success",
            "attempt": 1,
        }

    async def _call_llm_stream_async(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stage: str = "",
        unit_id: str = "",
        max_tokens: int | None = None,
        request_options: dict[str, Any] | None = None,
    ) -> str:
        """
        异步流式调用 LLM，返回完整文本内容。

        可选通过 progress_callback 透传思考链事件。
        """
        gc = self._require_gateway_client()
        full_content = ""
        full_reasoning = ""
        saw_stream_output = False
        request_kwargs: dict[str, Any] = dict(request_options or {})
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        try:
            async for chunk in gc.complete_stream(messages, model=model, **request_kwargs):
                if chunk.usage and progress_callback:
                    progress_callback({
                        "event_type": "model.usage",
                        "stage": stage,
                        "unit_id": unit_id,
                        "message": "模型调用用量已更新。",
                        "payload": {
                            **chunk.usage,
                            "model": chunk.model or model,
                            "finish_reason": chunk.finish_reason,
                        },
                    })
                if chunk.reasoning_content:
                    saw_stream_output = True
                    if progress_callback:
                        full_reasoning += chunk.reasoning_content
                        progress_callback({
                            "event_type": "model.thinking",
                            "stage": stage,
                            "unit_id": unit_id,
                            "message": "模型思考中...",
                            "payload": {
                                "reasoning_chunk": chunk.reasoning_content,
                                "accumulated_length": len(full_reasoning),
                                "model": chunk.model,
                                "finish_reason": chunk.finish_reason,
                            },
                        })
                if chunk.content:
                    saw_stream_output = True
                    full_content += chunk.content
        except Exception as exc:
            if saw_stream_output:
                raise StreamInterruptedAfterStartError(
                    "流式响应已开始后中断，已保留最近稳定阶段，请从恢复入口继续。"
                ) from exc
            raise
        return full_content

    # ── JSON 解析 ──────────────────────────────

    # 常见供应商错误关键词，匹配时直接给出友好提示而非 JSON 解析失败
    _PROVIDER_ERROR_PATTERNS: list[str] = [
        "请重试",
        "模型暂时不可用",
        "模型供应商返回了错误消息",
        "模型输出被上游内容安全策略过滤",
        "content_filter",
        "refusal",
        "temporarily unavailable",
        "please try again later",
    ]

    def _strip_and_parse_json(self, raw: str) -> dict[str, Any]:
        """清理 Markdown 围栏并解析 JSON，失败时尝试提取或修复截断的 JSON。"""
        gc = self._require_gateway_client()
        cleaned = gc._strip_markdown_fences(raw)

        # 先检查是否为供应商错误消息（非 JSON）
        self._raise_if_provider_error(raw)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # 尝试提取首个完整 JSON 值
            extracted = gc._extract_first_json_value(cleaned)
            if extracted is not None:
                return extracted
            # 尝试修复被截断的 JSON（模型输出 token 上限导致）
            repaired = self._repair_truncated_json(cleaned)
            if repaired is not None:
                return repaired
            # 再次检查供应商错误（可能在清理后更明显）
            self._raise_if_provider_error(raw)
            raise GatewayClientError(f"模型返回的 JSON 无法解析：{raw[:240]}")

    @classmethod
    def _is_provider_error(cls, raw: str) -> bool:
        """检查响应内容是否为供应商返回的错误消息。"""
        return any(pattern in raw for pattern in cls._PROVIDER_ERROR_PATTERNS)

    @classmethod
    def _raise_if_provider_error(cls, raw: str) -> None:
        """检查响应内容是否为供应商返回的错误消息，若是则抛出明确提示。"""
        for pattern in cls._PROVIDER_ERROR_PATTERNS:
            if pattern in raw:
                raise GatewayClientError(
                    f"模型供应商返回了错误消息（匹配关键词：{pattern}）：{raw[:200]}"
                )

    @staticmethod
    def _repair_truncated_json(text: str) -> dict[str, Any] | None:
        """尝试修复被截断的 JSON：找到最后一个完整的键值对，补全缺失的括号。"""
        # 找到第一个 { 的位置
        start = text.find("{")
        if start < 0:
            return None
        fragment = text[start:]

        # 找到最后一个完整的字符串值或数值/布尔值的位置
        # 策略：逐字符追踪括号深度和字符串状态，找到截断点
        depth = 0
        in_string = False
        escaping = False
        last_good_pos = start  # 最后一个可能完整的位置

        i = 0
        while i < len(fragment):
            char = fragment[i]
            if in_string:
                if escaping:
                    escaping = False
                elif char == "\\":
                    escaping = True
                elif char == '"':
                    in_string = False
                    # 字符串结束，检查后面是否有逗号或冒号
                    j = i + 1
                    while j < len(fragment) and fragment[j] in " \t\n\r":
                        j += 1
                    if j < len(fragment) and fragment[j] in ",:}":
                        last_good_pos = j + 1
                i += 1
                continue

            if char == '"':
                in_string = True
                i += 1
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    # 已经是完整 JSON
                    try:
                        return json.loads(fragment[:i + 1])
                    except json.JSONDecodeError:
                        pass
            elif char == ",":
                last_good_pos = i
            i += 1

        # 在 last_good_pos 处截断，补全括号
        candidate = fragment[:last_good_pos].rstrip(",")
        if candidate.endswith(":"):
            # 有一个键没有值，移除这个不完整的键
            idx = candidate.rfind('"')
            if idx > 0:
                # 找到前一个逗号
                comma = candidate[:idx].rfind(",")
                if comma > 0:
                    candidate = candidate[:comma]
                else:
                    candidate = candidate[:idx].rstrip(":{ \t\n")

        # 补全缺失的右括号
        open_braces = candidate.count("{") - candidate.count("}")
        open_brackets = candidate.count("[") - candidate.count("]")
        candidate += "]" * max(0, open_brackets) + "}" * max(0, open_braces)

        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        return None

    # ── LLM 调用 + JSON 解析 + 重试 ────────────

    def _call_llm_json(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        max_retries: int = 1,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stage: str = "",
        unit_id: str = "",
    ) -> dict[str, Any]:
        """
        流式调用 LLM 并解析 JSON，解析失败时自动重试。

        重试时在原始消息后追加重试提示词。
        """
        attempt_messages = list(messages)
        for attempt in range(max_retries + 1):
            full_content = self._call_llm_stream(
                attempt_messages,
                model,
                progress_callback=progress_callback,
                stage=stage,
                unit_id=unit_id,
            )
            try:
                return self._strip_and_parse_json(full_content)
            except (GatewayClientError, json.JSONDecodeError):
                if attempt >= max_retries:
                    raise
                # 在当前尝试的消息基础上追加重试提示
                attempt_messages = [dict(item) for item in attempt_messages] + [
                    {"role": "user", "content": _RETRY_JSON_PROMPT}
                ]
        # 理论上不可达
        raise GatewayClientError("LLM 调用重试后仍无法解析 JSON。")
