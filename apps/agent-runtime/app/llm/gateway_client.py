from __future__ import annotations

import json
from app.observability import get_logger
import re
import threading
import time
from collections.abc import AsyncGenerator, Generator
from time import sleep
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.observability.metrics import record_llm_call
from app.observability.performance import log_performance

logger = get_logger(__name__)


class GatewayClientError(Exception):
    pass


class StreamInterruptedAfterStartError(GatewayClientError):
    """流式响应已经开始输出后中断，不能安全重放同一个请求。"""


class StreamChunk:
    """流式响应的单个 chunk。"""

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


class OpenAICompatibleGatewayClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: httpx.Timeout | dict[str, float] | None = None,
        default_protocol: str = "openai",
        protocol_overrides: dict[str, str] | None = None,
        protocol_overrides_resolver: Any | None = None,
        anthropic_base_url: str | None = None,
        anthropic_version: str = "2023-06-01",
        model_capabilities_settings: Any | None = None,
    ) -> None:
        self.raw_base_url = base_url.rstrip("/")
        self.anthropic_raw_base_url = anthropic_base_url.rstrip("/") if anthropic_base_url else None
        self.api_key = api_key
        self.model = model
        self.default_protocol = self._normalize_protocol(default_protocol)
        self.protocol_overrides = {
            str(key): self._normalize_protocol(value)
            for key, value in (protocol_overrides or {}).items()
        }
        self.protocol_overrides_resolver = protocol_overrides_resolver
        self.anthropic_version = anthropic_version
        self.model_capabilities_settings = model_capabilities_settings
        self.base_url = self._base_url_for_protocol(self.default_protocol)
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if timeout is None:
            self._timeout = httpx.Timeout(connect=30.0, read=240.0, write=60.0, pool=60.0)
        elif isinstance(timeout, httpx.Timeout):
            self._timeout = timeout
        else:
            self._timeout = httpx.Timeout(
                connect=timeout.get("connect", 30.0),
                read=timeout.get("read", 240.0),
                write=timeout.get("write", 60.0),
                pool=timeout.get("pool", 60.0),
            )
        self._client_lock = threading.Lock()
        self._client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    @staticmethod
    def _normalize_protocol(protocol: str | None) -> str:
        value = (protocol or "openai").strip().lower()
        if value not in {"openai", "anthropic"}:
            return "openai"
        return value

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """将根域名规范化为标准 `/v1` 基址；已有路径时保持用户显式配置。"""
        stripped = base_url.rstrip("/")
        parts = urlsplit(stripped)
        path = parts.path.rstrip("/")
        if path in {"", "/"}:
            path = "/v1"
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))

    def _base_url_for_protocol(self, protocol: str) -> str:
        raw_base = self.anthropic_raw_base_url if protocol == "anthropic" and self.anthropic_raw_base_url else self.raw_base_url
        return self._normalize_base_url(raw_base)

    def _build_url(self, path: str, protocol: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{self._base_url_for_protocol(self._normalize_protocol(protocol))}{normalized_path}"

    def _headers_for_protocol(self, protocol: str) -> dict[str, str]:
        headers = dict(self.headers)
        if self._normalize_protocol(protocol) == "anthropic":
            headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = self.anthropic_version
        return headers

    def _resolve_protocol(self, model: str | None = None) -> str:
        resolved = model or self.model
        overrides = dict(self.protocol_overrides)
        if self.protocol_overrides_resolver is not None:
            try:
                dynamic_overrides = self.protocol_overrides_resolver() or {}
            except Exception:
                dynamic_overrides = {}
            if isinstance(dynamic_overrides, dict):
                overrides.update({
                    str(key): self._normalize_protocol(value)
                    for key, value in dynamic_overrides.items()
                })
        return self._normalize_protocol(overrides.get(resolved, self.default_protocol))

    def _get_client(self) -> httpx.Client:
        with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.Client(timeout=self._timeout, trust_env=False)
            return self._client

    def _get_async_client(self) -> httpx.AsyncClient:
        with self._client_lock:
            if self._async_client is None or self._async_client.is_closed:
                self._async_client = httpx.AsyncClient(timeout=self._timeout, trust_env=False)
            return self._async_client

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None and not self._client.is_closed:
                self._client.close()
            self._client = None

    async def aclose(self) -> None:
        self.close()
        if self._async_client is not None and not self._async_client.is_closed:
            await self._async_client.aclose()
        self._async_client = None

    def _get_adapter(self, model: str | None = None):
        """根据模型选择对应的协议适配器。"""
        from app.llm.protocols import AnthropicAdapter, OpenAIAdapter

        protocol = self._resolve_protocol(model)
        if protocol == "anthropic":
            return AnthropicAdapter()
        return OpenAIAdapter()

    def _provider_prompt_cache_kwargs(self, adapter: Any) -> dict[str, Any]:
        from app.llm.protocols import AnthropicAdapter
        from app.settings.config import get_settings

        if not isinstance(adapter, AnthropicAdapter):
            return {}
        try:
            settings = get_settings()
        except Exception:
            return {}
        if not getattr(settings, "provider_prompt_cache", True):
            return {}
        return {
            "provider_prompt_cache": True,
            "prompt_cache_min_chars": max(int(getattr(settings, "provider_prompt_cache_min_chars", 1024) or 1024), 1),
            "prompt_cache_ttl": str(getattr(settings, "provider_prompt_cache_ttl", "") or "").strip() or None,
        }

    def _resolve_max_tokens(self, model: str) -> int:
        """根据模型 catalog 返回该模型支持的最大输出 token 数。"""
        from app.llm.model_catalog import get_model_max_output_tokens
        max_tokens = get_model_max_output_tokens(model, settings=self.model_capabilities_settings)
        if max_tokens is not None:
            return int(max_tokens)
        return 4096

    def _inject_max_tokens(self, model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """若 kwargs 未显式指定 max_tokens，则从 model catalog 自动注入。"""
        if "max_tokens" not in kwargs:
            kwargs = {**kwargs, "max_tokens": self._resolve_max_tokens(model)}
        return kwargs

    def list_models(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/models", protocol=self.default_protocol)
        self._ensure_success(response, "读取模型列表失败")
        payload = response.json()
        return payload.get("data", [])

    def complete(self, messages: list[dict[str, str]], model: str | None = None, **kwargs: Any) -> str:
        resolved_model = model or self.model
        kwargs = self._inject_max_tokens(resolved_model, kwargs)
        protocol = self._resolve_protocol(resolved_model)
        adapter = self._get_adapter(resolved_model)
        kwargs = {**self._provider_prompt_cache_kwargs(adapter), **kwargs}
        payload = adapter.build_payload(messages=messages, model=resolved_model, stream=False, **kwargs)
        endpoint = adapter.get_endpoint()
        start = time.perf_counter()
        last_error_info = ""
        for attempt in range(3):
            response: httpx.Response | None = None
            try:
                response = self._request("POST", endpoint, json=payload, protocol=protocol)
                self._ensure_success(response, "调用聊天补全失败")
                # 检测空响应
                if not response.content or not response.content.strip():
                    last_error_info = f"响应状态{response.status_code}，内容为空"
                    logger.warning(
                        "llm_complete_retry model=%s attempt=%d status=%d content_length=%d",
                        resolved_model, attempt + 1, response.status_code, len(response.content or b""),
                    )
                    if attempt < 2:
                        sleep(1 * (attempt + 1))
                        continue
                    raise GatewayClientError(f"调用聊天补全失败（已重试3次）：{last_error_info}")
                body = response.json()
                result = adapter.parse_completion_response(body)
                duration_ms = (time.perf_counter() - start) * 1000
                record_llm_call(resolved_model, duration_ms, success=True)
                logger.info("llm_complete model=%s messages=%d duration_ms=%.2f", resolved_model, len(messages), duration_ms)
                return result
            except json.JSONDecodeError as exc:
                last_error_info = f"响应状态{response.status_code}，JSON解析失败"
                logger.warning(
                    "llm_complete_retry model=%s attempt=%d status=%d content_length=%d",
                    resolved_model, attempt + 1, response.status_code, len(response.content or b""),
                )
                if attempt < 2:
                    sleep(1 * (attempt + 1))
                    continue
                duration_ms = (time.perf_counter() - start) * 1000
                record_llm_call(resolved_model, duration_ms, success=False)
                logger.exception("llm_complete_failed model=%s messages=%d", resolved_model, len(messages))
                raise GatewayClientError(f"调用聊天补全失败（已重试3次）：{last_error_info}") from exc
            except GatewayClientError as exc:
                # 由 _ensure_success 或上方空响应/5xx逻辑抛出的业务异常，继续外层重试
                if response is None:
                    last_error_info = str(exc)
                    status = 0
                    content_length = 0
                else:
                    last_error_info = f"响应状态{response.status_code}，网关错误"
                    status = response.status_code
                    content_length = len(response.content or b"")
                logger.warning(
                    "llm_complete_retry model=%s attempt=%d status=%d content_length=%d",
                    resolved_model, attempt + 1, status, content_length,
                )
                if attempt < 2:
                    sleep(1 * (attempt + 1))
                    continue
                duration_ms = (time.perf_counter() - start) * 1000
                record_llm_call(resolved_model, duration_ms, success=False)
                logger.exception("llm_complete_failed model=%s messages=%d", resolved_model, len(messages))
                raise
            except Exception:
                duration_ms = (time.perf_counter() - start) * 1000
                record_llm_call(resolved_model, duration_ms, success=False)
                logger.exception("llm_complete_failed model=%s messages=%d", resolved_model, len(messages))
                raise
        # 理论上不可达，但兜底
        duration_ms = (time.perf_counter() - start) * 1000
        record_llm_call(resolved_model, duration_ms, success=False)
        raise GatewayClientError(f"调用聊天补全失败（已重试3次）：{last_error_info}")

    def complete_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> Any:
        raw = self.complete(messages=messages, model=model, **kwargs)
        cleaned = self._strip_markdown_fences(raw)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            extracted = self._extract_first_json_value(cleaned)
            if extracted is not None:
                return extracted
            raise GatewayClientError(f"模型返回的 JSON 无法解析：{raw[:240]}") from exc

    def _strip_markdown_fences(self, raw: str) -> str:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned, count=1)
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        return cleaned.strip()

    def _extract_first_json_value(self, text: str) -> Any | None:
        start = -1
        opening = ""
        for index, char in enumerate(text):
            if char in "{[":
                start = index
                opening = char
                break
        if start < 0:
            return None

        closing = "}" if opening == "{" else "]"
        depth = 0
        in_string = False
        escaping = False

        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaping:
                    escaping = False
                    continue
                if char == "\\":
                    escaping = True
                    continue
                if char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue
            if char == opening:
                depth += 1
                continue
            if char == closing:
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        return None
        return None

    def _ensure_success(self, response: httpx.Response, message: str) -> None:
        if response.status_code >= 400:
            raise GatewayClientError(f"{message}，状态码 {response.status_code}，响应：{response.text[:240]}")

    def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        protocol: str = "openai",
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._get_client().request(
                    method,
                    self._build_url(path, protocol),
                    headers=self._headers_for_protocol(protocol),
                    json=json,
                )
                # 5xx 服务端错误也触发重试
                if response.status_code >= 500 and attempt < 2:
                    last_error = GatewayClientError(
                        f"服务端错误，状态码 {response.status_code}，响应：{response.text[:240]}"
                    )
                    sleep(1.5 * (attempt + 1))
                    continue
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < 2:
                    sleep(1.5 * (attempt + 1))
        raise GatewayClientError(f"网关请求失败：{last_error}") from last_error

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式调用聊天补全，逐 chunk yield StreamChunk。"""
        resolved_model = model or self.model
        kwargs = self._inject_max_tokens(resolved_model, kwargs)
        protocol = self._resolve_protocol(resolved_model)
        adapter = self._get_adapter(resolved_model)
        kwargs = {**self._provider_prompt_cache_kwargs(adapter), **kwargs}
        payload = adapter.build_payload(messages=messages, model=resolved_model, stream=True, **kwargs)
        endpoint = adapter.get_endpoint()
        start = time.perf_counter()
        first_token_logged = False
        chunk_count = 0
        usage_chunk_count = 0
        content_chars = 0
        reasoning_chars = 0
        finish_reason = ""
        try:
            async with self._get_async_client().stream(
                "POST",
                self._build_url(endpoint, protocol),
                headers=self._headers_for_protocol(protocol),
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise GatewayClientError(
                        f"流式调用失败，状态码 {response.status_code}，响应：{body.decode('utf-8', errors='replace')[:240]}"
                    )
                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        duration_ms = (time.perf_counter() - start) * 1000
                        record_llm_call(resolved_model, duration_ms, success=True)
                        log_performance(
                            logger,
                            "llm_stream_metrics",
                            model=resolved_model,
                            messages=len(messages),
                            duration_ms=f"{duration_ms:.2f}",
                            chunk_count=chunk_count,
                            usage_chunk_count=usage_chunk_count,
                            content_chars=content_chars,
                            reasoning_chars=reasoning_chars,
                            finish_reason=finish_reason,
                        )
                        logger.info("llm_stream model=%s messages=%d duration_ms=%.2f", resolved_model, len(messages), duration_ms)
                        return
                    try:
                        chunk_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    parsed = adapter.parse_stream_chunk(chunk_data)
                    if parsed is None:
                        continue
                    if parsed.get("usage") is not None and not parsed.get("content") and not parsed.get("finish_reason") and not parsed.get("reasoning_content"):
                        usage_chunk_count += 1
                        yield StreamChunk(usage=parsed["usage"])
                        continue
                    content = parsed.get("content", "") or ""
                    reasoning_content = parsed.get("reasoning_content", "") or ""
                    if content or reasoning_content:
                        chunk_count += 1
                        content_chars += len(content)
                        reasoning_chars += len(reasoning_content)
                        if not first_token_logged:
                            first_token_logged = True
                            first_token_ms = (time.perf_counter() - start) * 1000
                            log_performance(
                                logger,
                                "llm_stream_first_token",
                                model=resolved_model,
                                messages=len(messages),
                                first_token_ms=f"{first_token_ms:.2f}",
                            )
                    if parsed.get("finish_reason"):
                        finish_reason = str(parsed.get("finish_reason") or "")
                    yield StreamChunk(
                        content=content,
                        reasoning_content=reasoning_content,
                        finish_reason=parsed.get("finish_reason"),
                        model=chunk_data.get("model", ""),
                        usage=parsed.get("usage"),
                    )
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            record_llm_call(resolved_model, duration_ms, success=False)
            logger.exception("llm_stream_failed model=%s messages=%d", resolved_model, len(messages))
            raise

    def complete_stream_sync(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> Generator[StreamChunk, None, None]:
        """同步流式调用聊天补全，逐 chunk yield StreamChunk。5xx 和网络错误自动重试。"""
        resolved_model = model or self.model
        kwargs = self._inject_max_tokens(resolved_model, kwargs)
        protocol = self._resolve_protocol(resolved_model)
        adapter = self._get_adapter(resolved_model)
        kwargs = {**self._provider_prompt_cache_kwargs(adapter), **kwargs}
        payload = adapter.build_payload(messages=messages, model=resolved_model, stream=True, **kwargs)
        endpoint = adapter.get_endpoint()
        start = time.perf_counter()

        last_stream_error: Exception | None = None
        for attempt in range(3):
            first_token_logged = False
            chunk_count = 0
            usage_chunk_count = 0
            content_chars = 0
            reasoning_chars = 0
            finish_reason = ""
            try:
                with self._get_client().stream(
                    "POST",
                    self._build_url(endpoint, protocol),
                    headers=self._headers_for_protocol(protocol),
                    json=payload,
                ) as response:
                    if response.status_code >= 500:
                        body = response.read()
                        if attempt < 2:
                            logger.warning("llm_stream_sync_retry model=%s attempt=%d status=%d", resolved_model, attempt + 1, response.status_code)
                            sleep(1.5 * (attempt + 1))
                            continue
                        raise GatewayClientError(
                            f"同步流式调用失败（已重试 {attempt + 1} 次），状态码 {response.status_code}，"
                            f"响应：{body.decode('utf-8', errors='replace')[:240]}"
                        )
                    if response.status_code >= 400:
                        body = response.read()
                        raise GatewayClientError(
                            f"同步流式调用失败，状态码 {response.status_code}，"
                            f"响应：{body.decode('utf-8', errors='replace')[:240]}"
                        )
                    for raw_line in response.iter_lines():
                        line = raw_line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            duration_ms = (time.perf_counter() - start) * 1000
                            record_llm_call(resolved_model, duration_ms, success=True)
                            log_performance(
                                logger,
                                "llm_stream_sync_metrics",
                                model=resolved_model,
                                messages=len(messages),
                                duration_ms=f"{duration_ms:.2f}",
                                chunk_count=chunk_count,
                                usage_chunk_count=usage_chunk_count,
                                content_chars=content_chars,
                                reasoning_chars=reasoning_chars,
                                finish_reason=finish_reason,
                                attempt=attempt + 1,
                            )
                            logger.info("llm_stream_sync model=%s messages=%d duration_ms=%.2f", resolved_model, len(messages), duration_ms)
                            return
                        try:
                            chunk_data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        parsed = adapter.parse_stream_chunk(chunk_data)
                        if parsed is None:
                            continue
                        if parsed.get("usage") is not None and not parsed.get("content") and not parsed.get("finish_reason") and not parsed.get("reasoning_content"):
                            usage_chunk_count += 1
                            yield StreamChunk(usage=parsed["usage"])
                            continue
                        content = parsed.get("content", "") or ""
                        reasoning_content = parsed.get("reasoning_content", "") or ""
                        if content or reasoning_content:
                            chunk_count += 1
                            content_chars += len(content)
                            reasoning_chars += len(reasoning_content)
                            if not first_token_logged:
                                first_token_logged = True
                                first_token_ms = (time.perf_counter() - start) * 1000
                                log_performance(
                                    logger,
                                    "llm_stream_sync_first_token",
                                    model=resolved_model,
                                    messages=len(messages),
                                    first_token_ms=f"{first_token_ms:.2f}",
                                    attempt=attempt + 1,
                                )
                        if parsed.get("finish_reason"):
                            finish_reason = str(parsed.get("finish_reason") or "")
                        yield StreamChunk(
                            content=content,
                            reasoning_content=reasoning_content,
                            finish_reason=parsed.get("finish_reason"),
                            model=chunk_data.get("model", ""),
                            usage=parsed.get("usage"),
                        )
                    return  # 成功完成，退出重试循环
            except httpx.HTTPError as exc:
                last_stream_error = exc
                if attempt < 2:
                    logger.warning("llm_stream_sync_retry model=%s attempt=%d error=%s", resolved_model, attempt + 1, exc)
                    sleep(1.5 * (attempt + 1))
                    continue
                duration_ms = (time.perf_counter() - start) * 1000
                record_llm_call(resolved_model, duration_ms, success=False)
                logger.exception("llm_stream_sync_failed model=%s messages=%d", resolved_model, len(messages))
                raise GatewayClientError(
                    f"同步流式调用网络失败（已重试 {attempt + 1} 次）：{exc}"
                ) from exc
        # 理论上不可达
        duration_ms = (time.perf_counter() - start) * 1000
        record_llm_call(resolved_model, duration_ms, success=False)
        logger.error("llm_stream_sync_failed model=%s messages=%d error=%s", resolved_model, len(messages), last_stream_error)
        raise GatewayClientError(f"同步流式调用失败：{last_stream_error}")
