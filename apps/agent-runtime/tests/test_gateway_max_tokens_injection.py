import unittest

from app.llm.gateway_client import GatewayClientError, OpenAICompatibleGatewayClient
from app.llm.protocols import AnthropicAdapter, OpenAIAdapter


class TestGatewayMaxTokensInjection(unittest.TestCase):
    def _client(self):
        return OpenAICompatibleGatewayClient(
            base_url="http://test",
            api_key="test-key",
            model="",
        )

    def _response(self, payload):
        class Response:
            status_code = 200
            content = b"{}"
            text = "{}"

            def json(self):
                return payload

        return Response()

    def test_complete_uses_current_provider_output_limit(self):
        client = self._client()
        calls = []

        def request(method, path, json=None, protocol="openai"):
            calls.append({"method": method, "path": path, "json": json, "protocol": protocol})
            if path == "/models":
                return self._response(
                    {
                        "data": [
                            {
                                "id": "provider-text-model",
                                "context_length": 120000,
                                "max_tokens": 6000,
                            }
                        ]
                    }
                )
            return self._response(
                {
                    "model": "provider-text-model",
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                }
            )

        client._request = request

        client.ensure_model_available("provider-text-model", force_refresh=True)
        self.assertEqual(client.complete([{"role": "user", "content": "hello"}], model="provider-text-model"), "ok")
        completion_request = next(item for item in calls if item["path"] == "/chat/completions")
        self.assertEqual(completion_request["json"]["max_tokens"], 6000)

    def test_complete_rejects_model_missing_from_current_provider_directory(self):
        client = self._client()
        calls = []

        def request(method, path, json=None, protocol="openai"):
            calls.append({"method": method, "path": path, "json": json, "protocol": protocol})
            return self._response({"data": [{"id": "another-provider-model"}]})

        client._request = request

        with self.assertRaisesRegex(GatewayClientError, "当前供应商模型目录"):
            client.ensure_model_available("removed-provider-model", force_refresh=True)
        self.assertEqual([item["path"] for item in calls], ["/models"])

    def test_complete_rejects_constructor_model_when_request_model_is_missing(self):
        client = OpenAICompatibleGatewayClient(
            base_url="http://test",
            api_key="test-key",
            model="constructor-model",
        )
        calls = []

        def request(method, path, json=None, protocol="openai"):
            calls.append({"method": method, "path": path, "json": json, "protocol": protocol})
            return self._response(
                {
                    "choices": [{"message": {"content": "不应调用"}, "finish_reason": "stop"}],
                }
            )

        client._request = request

        with self.assertRaisesRegex(GatewayClientError, "未显式选择模型"):
            client.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(calls, [])

    def test_inject_max_tokens_preserves_explicit(self):
        client = self._client()
        kwargs = {"max_tokens": 512}
        result = client._inject_max_tokens("provider-text-model", kwargs)
        self.assertEqual(result["max_tokens"], 512)

    def test_anthropic_adapter_uses_injected_max_tokens(self):
        """验证 AnthropicAdapter 会正确使用 GatewayClient 注入的 max_tokens。"""
        adapter = AnthropicAdapter()
        messages = [{"role": "user", "content": "hello"}]
        payload = adapter.build_payload(
            messages=messages,
            model="provider-text-model",
            stream=False,
            max_tokens=32768,
        )
        self.assertEqual(payload["max_tokens"], 32768)

    def test_openai_adapter_uses_injected_max_tokens(self):
        """验证 OpenAIAdapter 也会接受并使用注入的 max_tokens。"""
        adapter = OpenAIAdapter()
        messages = [{"role": "user", "content": "hello"}]
        payload = adapter.build_payload(
            messages=messages,
            model="provider-text-model",
            stream=False,
            max_tokens=16000,
        )
        self.assertEqual(payload["max_tokens"], 16000)

    def test_anthropic_adapter_does_not_inject_static_max_tokens_when_not_provided(self):
        """输出上限必须由网关目录或调用方提供，适配器本身不能注入固定值。"""
        adapter = AnthropicAdapter()
        messages = [{"role": "user", "content": "hello"}]
        payload = adapter.build_payload(
            messages=messages,
            model="claude-3-5-sonnet",
            stream=False,
        )
        self.assertNotIn("max_tokens", payload)

    def test_anthropic_adapter_explicit_max_tokens(self):
        """kwargs 传 max_tokens=32768 时，应使用传入值。"""
        adapter = AnthropicAdapter()
        messages = [{"role": "user", "content": "hello"}]
        payload = adapter.build_payload(
            messages=messages,
            model="claude-3-5-sonnet",
            stream=False,
            max_tokens=32768,
        )
        self.assertEqual(payload["max_tokens"], 32768)

    def test_anthropic_adapter_max_tokens_none(self):
        """kwargs 传 max_tokens=None 时，不应在 payload 中出现 max_tokens。"""
        adapter = AnthropicAdapter()
        messages = [{"role": "user", "content": "hello"}]
        payload = adapter.build_payload(
            messages=messages,
            model="claude-3-5-sonnet",
            stream=False,
            max_tokens=None,
        )
        self.assertNotIn("max_tokens", payload)


if __name__ == "__main__":
    unittest.main()
