from __future__ import annotations

import json
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
    ) -> dict[str, Any]:
        raw = self.complete(messages=messages, model=model)
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.removeprefix("```json").removesuffix("```").strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```").removesuffix("```").strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise GatewayClientError(f"模型返回的 JSON 无法解析：{raw[:240]}") from exc

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
