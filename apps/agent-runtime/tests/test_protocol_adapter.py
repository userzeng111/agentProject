import unittest

from app.llm.protocols import AnthropicAdapter, OpenAIAdapter, _extract_system_message


class ExtractSystemMessageTests(unittest.TestCase):
    def test_extracts_single_system_message(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        system, filtered = _extract_system_message(messages)
        self.assertEqual(system, "You are a helpful assistant.")
        self.assertEqual(filtered, [{"role": "user", "content": "Hello"}])

    def test_returns_none_when_no_system(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        system, filtered = _extract_system_message(messages)
        self.assertIsNone(system)
        self.assertEqual(filtered, messages)

    def test_ignores_subsequent_system_messages(self):
        messages = [
            {"role": "system", "content": "First"},
            {"role": "system", "content": "Second"},
            {"role": "user", "content": "Hello"},
        ]
        system, filtered = _extract_system_message(messages)
        self.assertEqual(system, "First")
        self.assertEqual(filtered, [{"role": "user", "content": "Hello"}])


class OpenAIAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = OpenAIAdapter()

    def test_get_endpoint(self):
        self.assertEqual(self.adapter.get_endpoint(), "/chat/completions")

    def test_build_payload(self):
        payload = self.adapter.build_payload(
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5.4",
            stream=True,
        )
        self.assertEqual(payload["model"], "gpt-5.4")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hi"}])
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["stream_options"], {"include_usage": True})

    def test_build_payload_preserves_explicit_stream_usage_option(self):
        payload = self.adapter.build_payload(
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5.4",
            stream=True,
            stream_options={"include_usage": False, "extra": "keep"},
        )

        self.assertEqual(payload["stream_options"], {"include_usage": False, "extra": "keep"})

    def test_parse_completion_response(self):
        response = {
            "choices": [{"message": {"content": "Hello world"}}]
        }
        self.assertEqual(self.adapter.parse_completion_response(response), "Hello world")

    def test_parse_stream_chunk_with_content(self):
        chunk = {
            "choices": [
                {"delta": {"content": "Hello", "reasoning_content": "thinking"}, "finish_reason": None}
            ]
        }
        parsed = self.adapter.parse_stream_chunk(chunk)
        self.assertEqual(parsed["content"], "Hello")
        self.assertEqual(parsed["reasoning_content"], "thinking")
        self.assertIsNone(parsed["finish_reason"])

    def test_parse_stream_chunk_with_finish_reason_only(self):
        chunk = {
            "choices": [
                {"delta": {}, "finish_reason": "length"}
            ]
        }
        parsed = self.adapter.parse_stream_chunk(chunk)
        self.assertEqual(parsed["content"], "")
        self.assertEqual(parsed["finish_reason"], "length")

    def test_parse_stream_chunk_with_usage(self):
        chunk = {"usage": {"total_tokens": 42}}
        parsed = self.adapter.parse_stream_chunk(chunk)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["usage"], {"total_tokens": 42})

    def test_parse_stream_chunk_preserves_usage_with_choices(self):
        chunk = {
            "choices": [
                {"delta": {}, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

        parsed = self.adapter.parse_stream_chunk(chunk)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["finish_reason"], "stop")
        self.assertEqual(parsed["usage"]["total_tokens"], 15)

    def test_parse_stream_chunk_none_for_empty(self):
        self.assertIsNone(self.adapter.parse_stream_chunk({}))


class AnthropicAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = AnthropicAdapter()

    def test_get_endpoint(self):
        self.assertEqual(self.adapter.get_endpoint(), "/messages")

    def test_build_payload_extracts_system(self):
        payload = self.adapter.build_payload(
            messages=[
                {"role": "system", "content": "SYS"},
                {"role": "user", "content": "hi"},
            ],
            model="kimi-k2-6",
            stream=False,
        )
        self.assertEqual(payload["model"], "kimi-k2-6")
        self.assertEqual(payload["system"], "SYS")
        self.assertNotIn({"role": "system", "content": "SYS"}, payload["messages"])
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertFalse(payload["stream"])

    def test_build_payload_without_system(self):
        payload = self.adapter.build_payload(
            messages=[{"role": "user", "content": "hi"}],
            model="kimi-k2-6",
        )
        self.assertNotIn("system", payload)

    def test_build_payload_marks_system_block_for_prompt_cache(self):
        payload = self.adapter.build_payload(
            messages=[
                {"role": "system", "content": "稳定系统提示"},
                {"role": "user", "content": "hi"},
            ],
            model="kimi-k2-6",
            provider_prompt_cache=True,
            prompt_cache_min_chars=1,
        )

        self.assertIsInstance(payload["system"], list)
        self.assertEqual(payload["system"][0]["type"], "text")
        self.assertEqual(payload["system"][0]["text"], "稳定系统提示")
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("provider_prompt_cache", payload)
        self.assertNotIn("prompt_cache_min_chars", payload)

    def test_build_payload_splits_cacheable_user_prefix_before_dynamic_marker(self):
        stable_prefix = "作品标题：夜半回廊\n总章节规划：一 / 二\n风格约束：冷静克制"
        dynamic_tail = "当前章节序号：1\n当前章节标题：第一章"
        payload = self.adapter.build_payload(
            messages=[
                {"role": "user", "content": f"{stable_prefix}\n{dynamic_tail}"},
            ],
            model="kimi-k2-6",
            provider_prompt_cache=True,
            prompt_cache_min_chars=1,
        )

        content = payload["messages"][0]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["text"], stable_prefix + "\n")
        self.assertEqual(content[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(content[1]["text"], dynamic_tail)

    def test_parse_completion_response(self):
        response = {
            "content": [{"type": "text", "text": "Hello world"}],
            "stop_reason": "end_turn",
        }
        self.assertEqual(self.adapter.parse_completion_response(response), "Hello world")

    def test_parse_completion_response_empty_content(self):
        self.assertEqual(self.adapter.parse_completion_response({}), "")

    def test_parse_stream_chunk_content_delta(self):
        chunk = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}
        parsed = self.adapter.parse_stream_chunk(chunk)
        self.assertEqual(parsed["content"], "Hi")

    def test_parse_stream_chunk_thinking_delta(self):
        chunk = {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "让我思考一下..."},
        }
        parsed = self.adapter.parse_stream_chunk(chunk)
        self.assertEqual(parsed["content"], "")
        self.assertEqual(parsed["reasoning_content"], "让我思考一下...")
        self.assertIsNone(parsed["finish_reason"])

    def test_parse_stream_chunk_message_delta(self):
        chunk = {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
        parsed = self.adapter.parse_stream_chunk(chunk)
        self.assertEqual(parsed["finish_reason"], "end_turn")

    def test_parse_stream_chunk_message_delta_max_tokens(self):
        chunk = {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}}
        parsed = self.adapter.parse_stream_chunk(chunk)
        self.assertEqual(parsed["finish_reason"], "max_tokens")

    def test_parse_stream_chunk_message_delta_with_usage(self):
        chunk = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        parsed = self.adapter.parse_stream_chunk(chunk)
        self.assertEqual(parsed["finish_reason"], "end_turn")
        self.assertEqual(parsed["usage"], {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})

    def test_parse_stream_chunk_control_messages_return_none(self):
        for t in ("message_start", "content_block_start", "content_block_stop", "message_stop"):
            self.assertIsNone(self.adapter.parse_stream_chunk({"type": t}))


if __name__ == "__main__":
    unittest.main()
