import unittest

from app.llm.gateway_client import OpenAICompatibleGatewayClient
from app.llm.protocols import AnthropicAdapter, OpenAIAdapter


class TestGatewayMaxTokensInjection(unittest.TestCase):
    def _client(self):
        return OpenAICompatibleGatewayClient(
            base_url="http://test",
            api_key="test-key",
            model="gpt-5.4",
        )

    def test_resolve_max_tokens_for_k26(self):
        client = self._client()
        self.assertEqual(client._resolve_max_tokens("K2.6"), 32768)

    def test_resolve_max_tokens_for_gpt54(self):
        client = self._client()
        self.assertEqual(client._resolve_max_tokens("gpt-5.4"), 16000)

    def test_resolve_max_tokens_fallback_for_unknown(self):
        client = self._client()
        self.assertEqual(client._resolve_max_tokens("unknown-model"), 4096)

    def test_inject_max_tokens_when_not_present(self):
        client = self._client()
        kwargs = {"stream": True}
        result = client._inject_max_tokens("K2.6", kwargs)
        self.assertEqual(result["max_tokens"], 32768)
        # 原始 kwargs 不应被修改
        self.assertNotIn("max_tokens", kwargs)

    def test_inject_max_tokens_preserves_explicit(self):
        client = self._client()
        kwargs = {"max_tokens": 512}
        result = client._inject_max_tokens("K2.6", kwargs)
        self.assertEqual(result["max_tokens"], 512)

    def test_anthropic_adapter_uses_injected_max_tokens(self):
        """验证 AnthropicAdapter 会正确使用 GatewayClient 注入的 max_tokens。"""
        adapter = AnthropicAdapter()
        messages = [{"role": "user", "content": "hello"}]
        payload = adapter.build_payload(
            messages=messages,
            model="K2.6",
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
            model="gpt-5.4",
            stream=False,
            max_tokens=16000,
        )
        self.assertEqual(payload["max_tokens"], 16000)

    def test_anthropic_adapter_default_max_tokens_when_not_provided(self):
        """kwargs 未传 max_tokens 时，AnthropicAdapter 应使用默认值 4096。"""
        adapter = AnthropicAdapter()
        messages = [{"role": "user", "content": "hello"}]
        payload = adapter.build_payload(
            messages=messages,
            model="claude-3-5-sonnet",
            stream=False,
        )
        self.assertEqual(payload["max_tokens"], 4096)

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
