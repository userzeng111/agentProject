from __future__ import annotations

import json
import re
from time import sleep
from typing import Any

import httpx


class GatewayClientError(Exception):
    pass


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
        payload = {
            "model": model or self.model,
            "messages": messages,
        }
        response = self._request("POST", "/chat/completions", json=payload)
        self._ensure_success(response, "调用聊天补全失败")
        body = response.json()
        return body["choices"][0]["message"]["content"]

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
                    return client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=self.headers,
                        json=json,
                    )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < 2:
                    sleep(1.5 * (attempt + 1))
        raise GatewayClientError(f"网关请求失败：{last_error}") from last_error
