import json
import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.llm.gateway_client import GatewayClientError, OpenAICompatibleGatewayClient


class MockResponse:
    def __init__(self, status_code: int, content: bytes | None = None, text: str = "") -> None:
        self.status_code = status_code
        self.content = content or text.encode("utf-8")
        self.text = text

    def json(self):
        return json.loads(self.text)


class GatewayEmptyResponseRetryTests(unittest.TestCase):
    def _make_client(self) -> OpenAICompatibleGatewayClient:
        return OpenAICompatibleGatewayClient(
            base_url="http://example.com", api_key="test-key", model="test-model"
        )

    def test_empty_response_retries_then_succeeds(self) -> None:
        """第一次空响应，第二次成功，应返回结果且只调用2次。"""
        client = self._make_client()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockResponse(status_code=200, content=b"  ")
            return MockResponse(
                status_code=200,
                text=json.dumps({"choices": [{"message": {"content": "成功结果"}}]}),
            )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request = MagicMock(side_effect=side_effect)
            mock_client_cls.return_value = mock_client

            result = client.complete([{"role": "user", "content": "test"}], model="test-model")
            self.assertEqual(result, "成功结果")
            self.assertEqual(call_count, 2)

    def test_complete_json_with_metadata_returns_usage(self) -> None:
        """非流式 JSON 补全应保留 OpenAI 兼容 usage 元数据。"""
        client = self._make_client()
        response = MockResponse(
            status_code=200,
            text=json.dumps(
                {
                    "model": "test-model",
                    "choices": [
                        {
                            "message": {"content": "{\"ok\": true}"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 4,
                        "total_tokens": 15,
                    },
                }
            ),
        )

        with patch.object(client, "_request", return_value=response):
            result = client.complete_json_with_metadata([{"role": "user", "content": "test"}], model="test-model")

        self.assertEqual(result["payload"], {"ok": True})
        self.assertEqual(result["usage"]["prompt_tokens"], 11)
        self.assertEqual(result["usage"]["completion_tokens"], 4)
        self.assertEqual(result["usage"]["total_tokens"], 15)
        self.assertEqual(result["usage"]["usage_source_path"], "usage")
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(result["finish_reason"], "stop")

    def test_three_empty_responses_raises_gateway_error(self) -> None:
        """连续3次空响应，应抛出 GatewayClientError。"""
        client = self._make_client()

        def side_effect(*args, **kwargs):
            return MockResponse(status_code=200, content=b"")

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request = MagicMock(side_effect=side_effect)
            mock_client_cls.return_value = mock_client

            with self.assertRaises(GatewayClientError) as ctx:
                client.complete([{"role": "user", "content": "test"}], model="test-model")
            self.assertIn("已重试3次", str(ctx.exception))
            self.assertIn("内容为空", str(ctx.exception))

    def test_json_decode_error_retries_then_succeeds(self) -> None:
        """第一次返回非法JSON，第二次成功，应返回结果。"""
        client = self._make_client()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockResponse(status_code=200, text="not json")
            return MockResponse(
                status_code=200,
                text=json.dumps({"choices": [{"message": {"content": "成功结果"}}]}),
            )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request = MagicMock(side_effect=side_effect)
            mock_client_cls.return_value = mock_client

            result = client.complete([{"role": "user", "content": "test"}], model="test-model")
            self.assertEqual(result, "成功结果")
            self.assertEqual(call_count, 2)

    def test_three_json_decode_errors_raises_gateway_error(self) -> None:
        """连续3次非法JSON，应抛出 GatewayClientError。"""
        client = self._make_client()

        def side_effect(*args, **kwargs):
            return MockResponse(status_code=200, text="invalid json")

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request = MagicMock(side_effect=side_effect)
            mock_client_cls.return_value = mock_client

            with self.assertRaises(GatewayClientError) as ctx:
                client.complete([{"role": "user", "content": "test"}], model="test-model")
            self.assertIn("已重试3次", str(ctx.exception))
            self.assertIn("JSON解析失败", str(ctx.exception))

    def test_500_error_retries_then_succeeds(self) -> None:
        """_request 已处理 5xx 重试，但 complete 也应兜底。"""
        client = self._make_client()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockResponse(status_code=500, text="server error")
            return MockResponse(
                status_code=200,
                text=json.dumps({"choices": [{"message": {"content": "成功结果"}}]}),
            )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request = MagicMock(side_effect=side_effect)
            mock_client_cls.return_value = mock_client

            result = client.complete([{"role": "user", "content": "test"}], model="test-model")
            self.assertEqual(result, "成功结果")
            self.assertEqual(call_count, 2)

    def test_network_failure_raises_gateway_error_not_unbound_local_error(self) -> None:
        """网络层失败时 complete 应保留 GatewayClientError，而不是读取未赋值 response。"""
        client = self._make_client()

        with patch.object(
            client,
            "_request",
            side_effect=GatewayClientError("网关请求失败：连接失败"),
        ):
            with self.assertRaises(GatewayClientError) as ctx:
                client.complete([{"role": "user", "content": "test"}], model="test-model")

        self.assertIn("网关请求失败", str(ctx.exception))

    def test_request_network_failure_raises_gateway_error(self) -> None:
        client = self._make_client()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.request = MagicMock(side_effect=httpx.ConnectError("连接失败"))
            mock_client_cls.return_value = mock_client

            with self.assertRaises(GatewayClientError) as ctx:
                client._request("POST", "/chat/completions", json={})

        self.assertIn("网关请求失败", str(ctx.exception))
