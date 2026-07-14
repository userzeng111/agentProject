from __future__ import annotations

import json
from copy import deepcopy
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
from app.observability.context import request_id_var
from app.observability.performance import log_performance

logger = get_logger("backend.gateway")


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


class CompletionResult:
    """非流式响应文本与模型用量元数据。"""

    __slots__ = ("content", "usage", "model", "finish_reason")

    def __init__(
        self,
        *,
        content: str = "",
        usage: dict[str, Any] | None = None,
        model: str = "",
        finish_reason: str | None = None,
    ) -> None:
        self.content = content
        self.usage = usage or {}
        self.model = model
        self.finish_reason = finish_reason


class OpenAICompatibleGatewayClient:
    @staticmethod
    def _pop_observability_kwargs(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        request_kwargs = dict(kwargs)
        observability = {
            "stage": str(request_kwargs.pop("_obs_stage", "") or ""),
            "exchange_label": str(request_kwargs.pop("_obs_exchange_label", "") or ""),
        }
        return request_kwargs, observability

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "",
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
        self._model_directory_lock = threading.Lock()
        self._model_directory: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _normalize_protocol(protocol: str | None) -> str:
        value = (protocol or "openai").strip().lower()
        if value not in {"openai", "anthropic"}:
            return "openai"
        return value

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """规范化基址：去除尾部斜杠，保留用户显式配置的完整路径。"""
        stripped = base_url.rstrip("/")
        parts = urlsplit(stripped)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))

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
        try:
            request_id = request_id_var.get()
        except LookupError:
            request_id = ""
        if request_id:
            headers["X-Request-ID"] = request_id
        return headers

    def _resolve_protocol(self, model: str | None = None) -> str:
        resolved = str(model or "").strip()
        overrides = dict(self.protocol_overrides)
        if self.protocol_overrides_resolver is not None:
            try:
                dynamic_overrides = self.protocol_overrides_resolver() or {}
            except Exception as exc:
                logger.warning("读取动态模型协议覆盖失败，使用静态协议配置降级: error=%s", exc)
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
        except Exception as exc:
            logger.warning("读取 provider prompt cache 设置失败: %s", exc)
            return {}
        if not getattr(settings, "provider_prompt_cache", True):
            return {}
        return {
            "provider_prompt_cache": True,
            "prompt_cache_min_chars": max(int(getattr(settings, "provider_prompt_cache_min_chars", 1024) or 1024), 1),
            "prompt_cache_ttl": str(getattr(settings, "provider_prompt_cache_ttl", "") or "").strip() or None,
        }

    @staticmethod
    def _usage_payload(parsed: dict[str, Any]) -> dict[str, Any]:
        usage = parsed.get("usage")
        if not isinstance(usage, dict):
            return {}
        payload = dict(usage)
        usage_source_path = parsed.get("usage_source_path")
        if usage_source_path:
            payload.setdefault("usage_source_path", str(usage_source_path))
        return payload

    @staticmethod
    def _usage_log_fields(usage: dict[str, Any]) -> dict[str, Any]:
        return {
            "usage_source_path": usage.get("usage_source_path"),
            "prompt_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
            "completion_tokens": usage.get("completion_tokens") or usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cached_tokens": usage.get("cached_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "reasoning_tokens": usage.get("reasoning_tokens"),
        }

    @staticmethod
    def _resolve_request_model(model: str | None) -> str:
        resolved_model = str(model or "").strip()
        if not resolved_model:
            raise GatewayClientError("未显式选择模型，调用已拒绝。")
        return resolved_model

    def _resolve_max_tokens(self, model: str, raw_model: dict[str, Any] | None = None) -> int | None:
        """优先使用当前供应商目录返回的输出上限，缺失时使用通用配置默认值。"""
        from app.llm.model_capabilities_config import extract_provider_model_limits, resolve_generation_max_tokens

        if isinstance(raw_model, dict):
            provider_limits, _ = extract_provider_model_limits(raw_model)
            max_tokens = provider_limits.get("max_output_tokens")
            if max_tokens is not None:
                return int(max_tokens)
        with self._model_directory_lock:
            cached = deepcopy(self._model_directory.get(model, {}))
        if cached:
            provider_limits, _ = extract_provider_model_limits(cached)
            max_tokens = provider_limits.get("max_output_tokens")
            if max_tokens is not None:
                return int(max_tokens)
        max_tokens = resolve_generation_max_tokens(None, settings=self.model_capabilities_settings)
        if max_tokens is not None:
            return int(max_tokens)
        return None

    def _inject_max_tokens(
        self,
        model: str,
        kwargs: dict[str, Any],
        raw_model: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """若调用方未给输出上限，按当前目录或通用配置默认值注入。"""
        if "max_tokens" not in kwargs:
            max_tokens = self._resolve_max_tokens(model, raw_model)
            if max_tokens is not None:
                kwargs = {**kwargs, "max_tokens": max_tokens}
        return kwargs

    def list_models(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/models", protocol=self.default_protocol)
        self._ensure_success(response, "读取模型列表失败")
        payload = response.json()
        raw_models = payload.get("data", [])
        if not isinstance(raw_models, list):
            raise GatewayClientError("读取模型列表失败：响应 data 字段不是数组。")
        models = [item for item in raw_models if isinstance(item, dict) and str(item.get("id") or "").strip()]
        with self._model_directory_lock:
            self._model_directory = {
                str(item["id"]).strip(): deepcopy(item)
                for item in models
            }
        return deepcopy(models)

    def ensure_model_available(self, model: str | None, *, force_refresh: bool = False) -> dict[str, Any]:
        """确认模型仍属于当前供应商目录，并返回原始模型项。"""
        model_id = self._resolve_request_model(model)
        with self._model_directory_lock:
            raw_model = deepcopy(self._model_directory.get(model_id, {}))
        if force_refresh or not raw_model:
            self.list_models()
            with self._model_directory_lock:
                raw_model = deepcopy(self._model_directory.get(model_id, {}))
        if not raw_model:
            raise GatewayClientError(
                f"模型 {model_id} 不在当前供应商模型目录中，请刷新目录后显式重新选择。"
            )
        return raw_model

    def get_model_max_output_tokens(self, model: str | None, *, force_refresh: bool = False) -> int | None:
        model_id = self._resolve_request_model(model)
        if force_refresh:
            raw_model = self.ensure_model_available(model_id, force_refresh=True)
            return self._resolve_max_tokens(model_id, raw_model)
        with self._model_directory_lock:
            raw_model = deepcopy(self._model_directory.get(model_id, {}))
        return self._resolve_max_tokens(model_id, raw_model)

    def complete(self, messages: list[dict[str, str]], model: str | None = None, **kwargs: Any) -> str:
        return self.complete_with_metadata(messages=messages, model=model, **kwargs).content

    def complete_with_metadata(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> CompletionResult:
        resolved_model = self._resolve_request_model(model)
        with self._model_directory_lock:
            raw_model = deepcopy(self._model_directory.get(resolved_model, {}))
        kwargs = self._inject_max_tokens(resolved_model, kwargs, raw_model)
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
                usage = adapter.parse_completion_usage(body)
                duration_ms = (time.perf_counter() - start) * 1000
                record_llm_call(resolved_model, duration_ms, success=True)
                log_performance(
                    logger,
                    "llm_complete_usage",
                    model=resolved_model,
                    messages=len(messages),
                    usage_present=bool(usage),
                    **self._usage_log_fields(usage),
                )
                logger.info("llm_complete model=%s messages=%d duration_ms=%.2f", resolved_model, len(messages), duration_ms)
                return CompletionResult(
                    content=result,
                    usage=usage,
                    model=str(body.get("model") or resolved_model),
                    finish_reason=self._completion_finish_reason(body),
                )
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
        return self._parse_json_content(raw)

    def complete_json_with_metadata(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = self.complete_with_metadata(messages=messages, model=model, **kwargs)
        return {
            "payload": self._parse_json_content(result.content),
            "usage": result.usage,
            "model": result.model,
            "finish_reason": result.finish_reason,
        }

    def _parse_json_content(self, raw: str) -> Any:
        cleaned = self._strip_markdown_fences(raw)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            extracted = self._extract_first_json_value(cleaned)
            if extracted is not None:
                return extracted
            raise GatewayClientError(f"模型返回的 JSON 无法解析：{raw[:240]}") from exc

    @staticmethod
    def _completion_finish_reason(body: dict[str, Any]) -> str | None:
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                finish_reason = choice.get("finish_reason")
                return str(finish_reason) if finish_reason else None
        stop_reason = body.get("stop_reason")
        return str(stop_reason) if stop_reason else None

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
        resolved_model = self._resolve_request_model(model)
        with self._model_directory_lock:
            raw_model = deepcopy(self._model_directory.get(resolved_model, {}))
        kwargs = self._inject_max_tokens(resolved_model, kwargs, raw_model)
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
                    if "error" in chunk_data:
                        error_obj = chunk_data["error"]
                        error_msg = error_obj.get("message", str(error_obj)) if isinstance(error_obj, dict) else str(error_obj)
                        error_type = error_obj.get("type", "") if isinstance(error_obj, dict) else ""
                        error_code = error_obj.get("code", error_obj.get("status", "")) if isinstance(error_obj, dict) else ""
                        logger.error(
                            "gateway_stream_error model=%s error_type=%s error_code=%s error_message=%s",
                            resolved_model,
                            error_type,
                            error_code,
                            error_msg,
                        )
                        raise GatewayClientError(f"模型返回错误：{error_msg}")
                    parsed = adapter.parse_stream_chunk(chunk_data)
                    if parsed is None:
                        continue
                    usage_payload = self._usage_payload(parsed)
                    if usage_payload:
                        usage_chunk_count += 1
                        log_performance(
                            logger,
                            "llm_stream_usage",
                            model=resolved_model,
                            messages=len(messages),
                            **self._usage_log_fields(usage_payload),
                        )
                    if usage_payload and not parsed.get("content") and not parsed.get("finish_reason") and not parsed.get("reasoning_content"):
                        yield StreamChunk(usage=usage_payload)
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
                        usage=usage_payload,
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
        resolved_model = self._resolve_request_model(model)
        kwargs, observability = self._pop_observability_kwargs(kwargs)
        with self._model_directory_lock:
            raw_model = deepcopy(self._model_directory.get(resolved_model, {}))
        kwargs = self._inject_max_tokens(resolved_model, kwargs, raw_model)
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
                                **observability,
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
                        usage_payload = self._usage_payload(parsed)
                        if usage_payload:
                            usage_chunk_count += 1
                            log_performance(
                                logger,
                                "llm_stream_sync_usage",
                                model=resolved_model,
                                messages=len(messages),
                                attempt=attempt + 1,
                                **observability,
                                **self._usage_log_fields(usage_payload),
                            )
                        if usage_payload and not parsed.get("content") and not parsed.get("finish_reason") and not parsed.get("reasoning_content"):
                            yield StreamChunk(usage=usage_payload)
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
                                    **observability,
                                )
                        if parsed.get("finish_reason"):
                            finish_reason = str(parsed.get("finish_reason") or "")
                        yield StreamChunk(
                            content=content,
                            reasoning_content=reasoning_content,
                            finish_reason=parsed.get("finish_reason"),
                            model=chunk_data.get("model", ""),
                            usage=usage_payload,
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
