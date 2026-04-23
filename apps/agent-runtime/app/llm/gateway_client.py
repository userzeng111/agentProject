from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncGenerator, Generator
from time import sleep
from typing import Any

import httpx

from app.observability.metrics import record_llm_call

logger = logging.getLogger(__name__)


class GatewayClientError(Exception):
    pass


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
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def list_models(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/models")
        self._ensure_success(response, "读取模型列表失败")
        payload = response.json()
        return payload.get("data", [])

    def complete(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        resolved_model = model or self.model
        payload = {
            "model": resolved_model,
            "messages": messages,
        }
        start = time.perf_counter()
        try:
            response = self._request("POST", "/chat/completions", json=payload)
            self._ensure_success(response, "调用聊天补全失败")
            body = response.json()
            result = body["choices"][0]["message"]["content"]
            duration_ms = (time.perf_counter() - start) * 1000
            record_llm_call(resolved_model, duration_ms, success=True)
            logger.info("llm_complete model=%s messages=%d duration_ms=%.2f", resolved_model, len(messages), duration_ms)
            return result
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            record_llm_call(resolved_model, duration_ms, success=False)
            logger.exception("llm_complete_failed model=%s messages=%d", resolved_model, len(messages))
            raise

    def complete_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> Any:
        raw = self.complete(messages=messages, model=model)
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

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(connect=30.0, read=240.0, write=60.0, pool=60.0),
                    trust_env=False,
                ) as client:
                    response = client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=self.headers,
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
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式调用 /chat/completions，逐 chunk yield StreamChunk。"""
        resolved_model = model or self.model
        payload = {
            "model": resolved_model,
            "messages": messages,
            "stream": True,
        }
        timeout_cfg = httpx.Timeout(connect=30.0, read=240.0, write=60.0, pool=60.0)
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_cfg, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
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
                            logger.info("llm_stream model=%s messages=%d duration_ms=%.2f", resolved_model, len(messages), duration_ms)
                            return
                        try:
                            chunk_data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk_data.get("choices") or []
                        if not choices:
                            # 最后一个 usage chunk 可能 choices 为空
                            usage = chunk_data.get("usage")
                            if usage:
                                yield StreamChunk(usage=usage)
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content") or ""
                        reasoning = delta.get("reasoning_content") or ""
                        finish_reason = choice.get("finish_reason")
                        chunk_model = chunk_data.get("model", "")
                        yield StreamChunk(
                            content=content,
                            reasoning_content=reasoning,
                            finish_reason=finish_reason,
                            model=chunk_model,
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
    ) -> Generator[StreamChunk, None, None]:
        """同步流式调用 /chat/completions，逐 chunk yield StreamChunk。5xx 和网络错误自动重试。"""
        resolved_model = model or self.model
        payload = {
            "model": resolved_model,
            "messages": messages,
            "stream": True,
        }
        timeout_cfg = httpx.Timeout(connect=30.0, read=240.0, write=60.0, pool=60.0)
        start = time.perf_counter()

        last_stream_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=timeout_cfg, trust_env=False) as client:
                    with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers=self.headers,
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
                                logger.info("llm_stream_sync model=%s messages=%d duration_ms=%.2f", resolved_model, len(messages), duration_ms)
                                return
                            try:
                                chunk_data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            choices = chunk_data.get("choices") or []
                            if not choices:
                                usage = chunk_data.get("usage")
                                if usage:
                                    yield StreamChunk(usage=usage)
                                continue
                            choice = choices[0]
                            delta = choice.get("delta") or {}
                            content = delta.get("content") or ""
                            reasoning = delta.get("reasoning_content") or ""
                            finish_reason = choice.get("finish_reason")
                            chunk_model = chunk_data.get("model", "")
                            yield StreamChunk(
                                content=content,
                                reasoning_content=reasoning,
                                finish_reason=finish_reason,
                                model=chunk_model,
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
