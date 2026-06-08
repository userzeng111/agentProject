import json
import re
import threading
import time

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

import tempfile
import unittest
from pathlib import Path

from app.llm.gateway_client import GatewayClientError, StreamChunk
from app.llm.story_engine import StoryEngine
from app.settings.config import Settings


from tests.fakes import FakeGatewayClient


class StreamGatewayBase:
    def _strip_markdown_fences(self, raw: str) -> str:
        return raw.strip()

    def _extract_first_json_value(self, text: str):
        return None


class StreamStartedThenFailsGateway(StreamGatewayBase):
    def __init__(self) -> None:
        self.stream_calls: list[dict] = []
        self.complete_json_calls = 0

    def complete_stream_sync(self, messages, model=None, **kwargs):
        self.stream_calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
        yield StreamChunk(reasoning_content="正在思考")
        raise GatewayClientError("同步流式调用失败，状态码 504")

    def complete_json(self, messages, model=None, **kwargs):
        self.complete_json_calls += 1
        return {
            "number": 1,
            "title": "不应回退",
            "summary": "不应回退",
            "content": "不应回退",
        }


class StreamFailsBeforeChunkGateway(StreamGatewayBase):
    def __init__(self) -> None:
        self.stream_calls: list[dict] = []
        self.complete_json_calls = 0

    def complete_stream_sync(self, messages, model=None, **kwargs):
        self.stream_calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
        if False:
            yield StreamChunk()
        raise GatewayClientError("同步流式调用启动失败，状态码 504")

    def complete_json(self, messages, model=None, **kwargs):
        self.complete_json_calls += 1
        return {
            "number": 1,
            "title": "启动前回退",
            "summary": "启动前回退成功",
            "content": "正文",
        }


class StreamSuccessGateway(StreamGatewayBase):
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.stream_calls: list[dict] = []

    def complete_stream_sync(self, messages, model=None, **kwargs):
        self.stream_calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
        import json

        yield StreamChunk(content=json.dumps(self.payload, ensure_ascii=False))


class StreamSuccessWithUsageGateway(StreamGatewayBase):
    def __init__(self, payload: dict, usage: dict) -> None:
        self.payload = payload
        self.usage = usage

    def complete_stream_sync(self, messages, model=None, **kwargs):
        yield StreamChunk(usage=dict(self.usage), model=model or "")
        yield StreamChunk(content=json.dumps(self.payload, ensure_ascii=False), model=model or "")


class StreamInvalidJsonGateway(StreamGatewayBase):
    def __init__(self, raw_response: str, finish_reason: str | None = None) -> None:
        self.raw_response = raw_response
        self.finish_reason = finish_reason

    def complete_stream_sync(self, messages, model=None, **kwargs):
        yield StreamChunk(content=self.raw_response, model=model or "")
        if self.finish_reason:
            yield StreamChunk(finish_reason=self.finish_reason, model=model or "")


class StreamInvalidThenRepairGateway(StreamGatewayBase):
    def __init__(self, repaired_payload: dict) -> None:
        self.repaired_payload = repaired_payload
        self.calls: list[dict] = []

    def complete_stream_sync(self, messages, model=None, **kwargs):
        self.calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
        if len(self.calls) == 1:
            yield StreamChunk(content="not-json", model=model or "")
            yield StreamChunk(finish_reason="length", model=model or "")
            return
        yield StreamChunk(content=json.dumps(self.repaired_payload, ensure_ascii=False), model=model or "")
        yield StreamChunk(finish_reason="stop", model=model or "")


class StreamReasoningOnlyLengthThenSuccessGateway(StreamGatewayBase):
    def __init__(self, repaired_payload: dict) -> None:
        self.repaired_payload = repaired_payload
        self.calls: list[dict] = []

    def complete_stream_sync(self, messages, model=None, **kwargs):
        self.calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
        if len(self.calls) == 1:
            yield StreamChunk(reasoning_content="先详细分析一致性问题", model=model or "")
            yield StreamChunk(finish_reason="length", model=model or "")
            return
        yield StreamChunk(content=json.dumps(self.repaired_payload, ensure_ascii=False), model=model or "")
        yield StreamChunk(finish_reason="stop", model=model or "")


class StreamInvalidThenInvalidRepairGateway(StreamGatewayBase):
    def __init__(self, first_raw: str, repair_raw: str) -> None:
        self.first_raw = first_raw
        self.repair_raw = repair_raw
        self.calls: list[dict] = []

    def complete_stream_sync(self, messages, model=None, **kwargs):
        self.calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
        if len(self.calls) == 1:
            yield StreamChunk(content=self.first_raw, model=model or "")
            yield StreamChunk(finish_reason="stop", model=model or "")
            return
        yield StreamChunk(content=self.repair_raw, model=model or "")
        yield StreamChunk(finish_reason="stop", model=model or "")


class BoundaryChapterGateway(StreamGatewayBase):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_stream_sync(self, messages, model=None, **kwargs):
        self.calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
        prompt = messages[-1]["content"]
        match = re.search(r"---CHAPTER_META_JSON_BOUNDARY_([a-f0-9]{12})---", prompt)
        if match is None:
            yield StreamChunk(
                content='{"number":3,"title":"初次改写","summary":"摘要","content":"最终写下一行简洁的字："钥匙出现在玄关托盘里。"."}',
                model=model or "",
            )
            return
        suffix = match.group(1)
        yield StreamChunk(
            content=(
                f"---CHAPTER_META_JSON_BOUNDARY_{suffix}---\n"
                '{"number":3,"title":"初次改写","summary":"主角测试账簿改写一件小事。"}\n'
                f"---CHAPTER_CONTENT_BOUNDARY_{suffix}---\n"
                '最终写下一行简洁的字："钥匙出现在玄关托盘里。"\n\n'
                '页面多了一行字："代价：一段记忆。"\n'
                "```text\n账簿仍保持沉默。\n```\n"
                f"---CHAPTER_END_BOUNDARY_{suffix}---"
            ),
            model=model or "",
        )
        yield StreamChunk(finish_reason="stop", model=model or "")


class BoundaryWithoutEndChapterGateway(StreamGatewayBase):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_stream_sync(self, messages, model=None, **kwargs):
        self.calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
        prompt = messages[-1]["content"]
        match = re.search(r"---CHAPTER_META_JSON_BOUNDARY_([a-f0-9]{12})---", prompt)
        if match is None:
            yield StreamChunk(content="{}", model=model or "")
            yield StreamChunk(finish_reason="stop", model=model or "")
            return
        suffix = match.group(1)
        yield StreamChunk(
            content=(
                f"---CHAPTER_META_JSON_BOUNDARY_{suffix}---\n"
                '{"number":3,"title":"初次改写","summary":"主角测试账簿改写一件小事。"}\n'
                f"---CHAPTER_CONTENT_BOUNDARY_{suffix}---\n"
                '最终写下一行简洁的字："钥匙出现在玄关托盘里。"\n\n'
                '页面多了一行字："代价：一段记忆。"\n'
            ),
            model=model or "",
        )
        yield StreamChunk(finish_reason="stop", model=model or "")


class ConcurrentChapterGateway(StreamGatewayBase):
    def __init__(self, delay_seconds: float = 0.05) -> None:
        self.delay_seconds = delay_seconds
        self.active_calls = 0
        self.max_active_calls = 0
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def complete_stream_sync(self, messages, model=None, **kwargs):
        with self._lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
            self.calls.append({"messages": [dict(item) for item in messages], "model": model, "kwargs": dict(kwargs)})
        try:
            time.sleep(self.delay_seconds)
            prompt = messages[-1]["content"]
            match = re.search(r"当前章节序号：(\d+)", prompt)
            number = int(match.group(1)) if match else len(self.calls)
            payload = {
                "number": number,
                "title": f"第{number}章",
                "summary": f"第{number}章摘要",
                "content": f"第{number}章正文",
            }
            yield StreamChunk(content=json.dumps(payload, ensure_ascii=False), model=model or "")
        finally:
            with self._lock:
                self.active_calls -= 1


class StoryEngineContextTests(unittest.TestCase):
    def test_story_engine_validates_planned_chapter_count_within_target_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )

            self.assertTrue(hasattr(engine, "validate_story_plan"))
            validate_story_plan = getattr(engine, "validate_story_plan", None)
            self.assertIsNotNone(validate_story_plan)
            with self.assertRaises(ValueError):
                validate_story_plan(
                    {
                        "working_title": "测试书名",
                        "logline": "测试梗概",
                        "planned_chapter_count": 120,
                        "chapter_plan": [
                            {"number": number, "title": f"第{number}章", "goal": "推进"}
                            for number in range(1, 101)
                        ],
                    },
                    chapter_count_min=90,
                    chapter_count_max=110,
                )

    def test_story_engine_validates_chapter_plan_length_matches_planned_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )

            self.assertTrue(hasattr(engine, "validate_story_plan"))
            validate_story_plan = getattr(engine, "validate_story_plan", None)
            self.assertIsNotNone(validate_story_plan)
            with self.assertRaises(ValueError):
                validate_story_plan(
                    {
                        "working_title": "测试书名",
                        "logline": "测试梗概",
                        "planned_chapter_count": 10,
                        "chapter_plan": [{"number": 1, "title": "第一章", "goal": "推进"}],
                    },
                    chapter_count_min=8,
                    chapter_count_max=12,
                )

    def test_generate_chapter_pair_injects_compiled_style_profile_into_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            fake_gateway = FakeGatewayClient(
                [
                    {
                        "number": 1,
                        "title": "第一章",
                        "summary": "主角完成首次觉醒",
                        "content": "第一章内容",
                    }
                ]
            )
            engine.gateway_client = fake_gateway

            engine.generate_chapter_pair(
                spec={
                    "mode": "style_remix",
                    "creative_mode": "style_remix",
                    "novel_size": "long",
                    "prompt": "写一篇学院流玄幻故事",
                    "genre": "玄幻",
                    "style": "保留热血成长感",
                    "style_profile_id": "douluo",
                    "style_profile_name": "唐家三少风格实例",
                    "style_guidance": "实例：唐家三少风格实例\n语言规则：术语密集\n情节规则：力量升级驱动",
                    "model_id": "gpt-5.4",
                    "chapter_word_min": 2600,
                    "chapter_word_max": 3380,
                },
                story_plan={
                    "working_title": "魂环初现",
                    "logline": "少年踏入魂师学院",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "觉醒武魂"},
                    ],
                },
                batch_index=0,
                completed_chapters=[],
                reference_text="学院、武魂、魂环。",
                context_packet={
                    "memory_text": "保持少年热血。",
                    "references_text": "学院、武魂、魂环。",
                },
                model="gpt-5.4",
            )

            first_call_messages = fake_gateway.calls[0]["messages"]
            rendered_prompt = first_call_messages[-1]["content"]
            self.assertIn("唐家三少风格实例", rendered_prompt)
            self.assertIn("力量升级驱动", rendered_prompt)
            self.assertIn("2600 到 3380", rendered_prompt)
            self.assertNotIn("保留冷静克制的中文叙事风格", rendered_prompt)

    def test_generate_chapter_pair_saved_event_includes_conversation_history_for_chapter_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            engine.gateway_client = StreamSuccessGateway(
                {
                    "number": 1,
                    "title": "第一章",
                    "summary": "主角发现线索。",
                    "content": "第一章正文",
                }
            )
            events: list[dict] = []

            engine.generate_chapter_pair(
                spec={
                    "mode": "short_story",
                    "creative_mode": "original",
                    "novel_size": "short",
                    "prompt": "写一篇测试短篇",
                    "genre": "",
                    "style": "",
                    "chapter_word_min": 800,
                    "chapter_word_max": 1200,
                    "model_id": "gpt-5.4",
                },
                story_plan={
                    "working_title": "测试短篇",
                    "logline": "主角发现线索。",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "发现线索"},
                    ],
                },
                batch_index=0,
                completed_chapters=[],
                reference_text="",
                progress_callback=events.append,
                requested_batch_size=1,
            )

            saved_events = [event for event in events if event.get("event_type") == "chapter.saved"]
            self.assertEqual(len(saved_events), 1)
            conversation_history = saved_events[0].get("conversation_history")
            self.assertIsInstance(conversation_history, list)
            assert isinstance(conversation_history, list)
            assistant_messages = [item for item in conversation_history if item.get("role") == "assistant"]
            self.assertTrue(assistant_messages)
            self.assertIn("第一章正文", assistant_messages[-1]["content"])

    def test_generate_chapter_pair_does_not_fallback_after_stream_started_then_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="K2.6",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamStartedThenFailsGateway()
            engine.gateway_client = gateway

            with self.assertRaises(GatewayClientError):
                engine.generate_chapter_pair(
                    spec={
                        "mode": "long_story",
                        "creative_mode": "original",
                        "novel_size": "long",
                        "prompt": "玄幻大陆废材逆袭",
                        "genre": "玄幻",
                        "style": "热血逆袭",
                        "chapter_word_min": 2600,
                        "chapter_word_max": 3380,
                        "model_id": "K2.6",
                    },
                    story_plan={
                        "working_title": "玄脉逆天",
                        "logline": "废材少年重开玄脉。",
                        "chapter_plan": [
                            {"number": 1, "title": "第一章", "goal": "开篇"},
                        ],
                    },
                    batch_index=0,
                    completed_chapters=[],
                    reference_text="",
                    model="K2.6",
                )

            self.assertEqual(gateway.complete_json_calls, 0)

    def test_generate_chapter_pair_fallbacks_when_stream_fails_before_any_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="K2.6",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamFailsBeforeChunkGateway()
            engine.gateway_client = gateway

            drafts = engine.generate_chapter_pair(
                spec={
                    "mode": "long_story",
                    "creative_mode": "original",
                    "novel_size": "long",
                    "prompt": "玄幻大陆废材逆袭",
                    "genre": "玄幻",
                    "style": "热血逆袭",
                    "chapter_word_min": 2600,
                    "chapter_word_max": 3380,
                    "model_id": "K2.6",
                },
                story_plan={
                    "working_title": "玄脉逆天",
                    "logline": "废材少年重开玄脉。",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "开篇"},
                    ],
                },
                batch_index=0,
                completed_chapters=[],
                reference_text="",
                model="K2.6",
            )

            self.assertEqual(drafts[0].title, "启动前回退")
            self.assertEqual(gateway.complete_json_calls, 1)

    def test_generate_chapter_pair_uses_stage_max_tokens_below_k26_catalog_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="K2.6",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamSuccessGateway(
                {
                    "number": 1,
                    "title": "第一章",
                    "summary": "主角重开玄脉。",
                    "content": "第一章正文",
                }
            )
            engine.gateway_client = gateway

            engine.generate_chapter_pair(
                spec={
                    "mode": "long_story",
                    "creative_mode": "original",
                    "novel_size": "long",
                    "prompt": "玄幻大陆废材逆袭",
                    "genre": "玄幻",
                    "style": "热血逆袭",
                    "chapter_word_min": 2600,
                    "chapter_word_max": 3380,
                    "model_id": "K2.6",
                },
                story_plan={
                    "working_title": "玄脉逆天",
                    "logline": "废材少年重开玄脉。",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "开篇"},
                    ],
                },
                batch_index=0,
                completed_chapters=[],
                reference_text="",
                model="K2.6",
            )

            max_tokens = gateway.stream_calls[0]["kwargs"].get("max_tokens")
            self.assertIsNotNone(max_tokens)
            self.assertLess(max_tokens, 32768)
            self.assertGreaterEqual(max_tokens, 4096)

    def test_generate_chapter_pair_uses_configured_generation_max_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            capability_path = Path(tmp_dir) / "model_capabilities.json"
            capability_path.write_text(
                json.dumps(
                    {
                        "defaults": {
                            "max_input_tokens": 200000,
                            "max_output_tokens": 10000,
                        },
                        "models": {
                            "mimo-v2.5-pro": {
                                "max_input_tokens": 200000,
                                "max_output_tokens": 10000,
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    MODEL_CAPABILITIES_PATH=str(capability_path),
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamSuccessGateway(
                {
                    "number": 1,
                    "title": "第一章",
                    "summary": "主角重开玄脉。",
                    "content": "第一章正文",
                }
            )
            engine.gateway_client = gateway

            engine.generate_chapter_pair(
                spec={
                    "mode": "long_story",
                    "creative_mode": "original",
                    "novel_size": "long",
                    "prompt": "玄幻大陆废材逆袭",
                    "genre": "玄幻",
                    "style": "热血逆袭",
                    "chapter_word_min": 1800,
                    "chapter_word_max": 2340,
                    "model_id": "mimo-v2.5-pro",
                },
                story_plan={
                    "working_title": "玄脉逆天",
                    "logline": "废材少年重开玄脉。",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "开篇"},
                    ],
                },
                batch_index=0,
                completed_chapters=[],
                reference_text="",
                model="mimo-v2.5-pro",
            )

            self.assertEqual(gateway.stream_calls[0]["kwargs"].get("max_tokens"), 10000)

    def test_stream_json_parse_failure_emits_raw_response_diagnostic_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            raw_response = "not-json"
            engine.gateway_client = StreamInvalidJsonGateway(raw_response, finish_reason="length")
            events: list[dict] = []

            with self.assertRaisesRegex(GatewayClientError, "模型返回的 JSON 无法解析"):
                engine._complete_stream_json_with_cache(  # noqa: SLF001
                    request_messages=[
                        {"role": "system", "content": "你是章节起草助手。"},
                        {"role": "user", "content": "当前章节序号：5\n请输出 JSON。"},
                    ],
                    model="mimo-v2.5-pro",
                    stage="drafting",
                    exchange_label="chapter-05",
                    exchange_callback=events.append,
                    progress_callback=None,
                    max_tokens=10000,
                )

            self.assertEqual(len(events), 2)
            diagnostic = events[0]
            self.assertTrue(diagnostic["response_parse_failed"])
            self.assertEqual(diagnostic["raw_response"], raw_response)
            self.assertEqual(diagnostic["finish_reason"], "length")
            self.assertEqual(diagnostic["exchange_label"], "chapter-05")
            repair_diagnostic = events[1]
            self.assertTrue(repair_diagnostic["response_parse_failed"])
            self.assertEqual(repair_diagnostic["exchange_label"], "chapter-05-repair")

    def test_stream_json_parse_failure_repairs_with_second_complete_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            repaired = {
                "number": 5,
                "title": "大师之谬",
                "summary": "重新输出完整摘要。",
                "content": "完整正文。",
            }
            gateway = StreamInvalidThenRepairGateway(repaired)
            engine.gateway_client = gateway
            events: list[dict] = []

            payload, _ = engine._complete_stream_json_with_cache(  # noqa: SLF001
                request_messages=[
                    {"role": "system", "content": "你是章节起草助手。"},
                    {"role": "user", "content": "当前章节序号：5\n请输出 JSON。"},
                ],
                model="mimo-v2.5-pro",
                stage="drafting",
                exchange_label="chapter-05",
                exchange_callback=events.append,
                progress_callback=None,
                max_tokens=10000,
            )

            self.assertEqual(payload, repaired)
            self.assertEqual(len(gateway.calls), 2)
            self.assertIn("重新输出一个完整、可解析的 JSON 对象", gateway.calls[1]["messages"][-1]["content"])
            self.assertTrue(events[0]["response_parse_failed"])
            self.assertEqual(events[1]["response_payload"], repaired)

    def test_stream_json_parse_failure_emits_repair_raw_response_diagnostic_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamInvalidThenInvalidRepairGateway(
                first_raw="not-json",
                repair_raw="still-not-json",
            )
            engine.gateway_client = gateway
            events: list[dict] = []

            with self.assertRaisesRegex(GatewayClientError, "模型返回的 JSON 无法解析"):
                engine._complete_stream_json_with_cache(  # noqa: SLF001
                    request_messages=[
                        {"role": "system", "content": "你是章节起草助手。"},
                        {"role": "user", "content": "当前章节序号：5\n请输出 JSON。"},
                    ],
                    model="mimo-v2.5-pro",
                    stage="drafting",
                    exchange_label="chapter-05",
                    exchange_callback=events.append,
                    progress_callback=None,
                    max_tokens=10000,
                )

            failed_events = [event for event in events if event.get("response_parse_failed")]
            self.assertEqual([event["exchange_label"] for event in failed_events], ["chapter-05", "chapter-05-repair"])
            self.assertEqual(failed_events[0]["raw_response"], gateway.first_raw)
            self.assertEqual(failed_events[1]["raw_response"], gateway.repair_raw)

    def test_generate_chapter_pair_accepts_boundary_protocol_for_unescaped_quote_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = BoundaryChapterGateway()
            engine.gateway_client = gateway

            drafts = engine.generate_chapter_pair(
                spec={
                    "mode": "short_story",
                    "creative_mode": "original",
                    "novel_size": "short",
                    "prompt": "写一章悬疑短篇。",
                    "genre": "悬疑",
                    "style": "冷静克制",
                    "model_id": "mimo-v2.5-pro",
                    "chapter_word_min": 600,
                    "chapter_word_max": 780,
                    "chapter_word_range_text": "600 到 780",
                },
                story_plan={
                    "working_title": "账簿午夜",
                    "logline": "旧书店账簿改写现实。",
                    "planned_chapter_count": 3,
                    "chapter_plan": [
                        {"number": 3, "title": "初次改写", "goal": "主角测试账簿。"},
                    ],
                },
                batch_index=0,
                completed_chapters=[],
                reference_text="",
                model="mimo-v2.5-pro",
            )

            self.assertEqual(len(drafts), 1)
            self.assertEqual(drafts[0].number, 3)
            self.assertEqual(drafts[0].title, "初次改写")
            self.assertIn('"钥匙出现在玄关托盘里。"', drafts[0].content)
            self.assertIn('"代价：一段记忆。"', drafts[0].content)
            self.assertIn("```text", drafts[0].content)
            self.assertEqual(len(gateway.calls), 1)
            self.assertIn("---CHAPTER_META_JSON_BOUNDARY_", gateway.calls[0]["messages"][-1]["content"])

    def test_generate_chapter_pair_accepts_boundary_protocol_without_end_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = BoundaryWithoutEndChapterGateway()
            engine.gateway_client = gateway

            drafts = engine.generate_chapter_pair(
                spec={
                    "mode": "short_story",
                    "creative_mode": "original",
                    "novel_size": "short",
                    "prompt": "写一章悬疑短篇。",
                    "genre": "悬疑",
                    "style": "冷静克制",
                    "model_id": "mimo-v2.5-pro",
                    "chapter_word_min": 600,
                    "chapter_word_max": 780,
                    "chapter_word_range_text": "600 到 780",
                },
                story_plan={
                    "working_title": "账簿午夜",
                    "logline": "旧书店账簿改写现实。",
                    "planned_chapter_count": 3,
                    "chapter_plan": [
                        {"number": 3, "title": "初次改写", "goal": "主角测试账簿。"},
                    ],
                },
                batch_index=0,
                completed_chapters=[],
                reference_text="",
                model="mimo-v2.5-pro",
            )

            self.assertEqual(len(drafts), 1)
            self.assertEqual(drafts[0].number, 3)
            self.assertIn('"钥匙出现在玄关托盘里。"', drafts[0].content)
            self.assertIn('"代价：一段记忆。"', drafts[0].content)
            self.assertEqual(len(gateway.calls), 1)

    def test_stream_usage_emits_provider_prompt_cache_progress_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="K2.6",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            engine.gateway_client = StreamSuccessWithUsageGateway(
                payload={
                    "number": 1,
                    "title": "第一章",
                    "summary": "主角重开玄脉。",
                    "content": "第一章正文",
                },
                usage={
                    "input_tokens": 0,
                    "cache_read_input_tokens": 2856,
                    "cached_tokens": 2856,
                    "output_tokens": 7,
                },
            )
            events: list[dict] = []

            payload, _ = engine._complete_stream_json_with_cache(  # noqa: SLF001
                request_messages=[
                    {"role": "system", "content": "你是章节起草助手。"},
                    {"role": "user", "content": "当前章节序号：1\n请输出 JSON。"},
                ],
                model="K2.6",
                stage="drafting",
                exchange_label="chapter-01",
                exchange_callback=None,
                progress_callback=events.append,
                max_tokens=1024,
            )

            self.assertEqual(payload["number"], 1)
            usage_events = [event for event in events if event.get("event_type") == "model.usage"]
            self.assertEqual(len(usage_events), 1)
            self.assertEqual(usage_events[0]["payload"]["cached_tokens"], 2856)
            self.assertEqual(usage_events[0]["payload"]["cache_read_input_tokens"], 2856)

    def test_generate_chapter_pair_parallelizes_three_chapter_batch_with_configured_worker_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="K2.6",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                    CHAPTER_PARALLEL_DRAFT_ENABLED=True,
                    CHAPTER_PARALLEL_MAX_WORKERS=4,
                )
            )
            gateway = ConcurrentChapterGateway()
            engine.gateway_client = gateway

            drafts = engine.generate_chapter_pair(
                spec={
                    "mode": "long_story",
                    "creative_mode": "original",
                    "novel_size": "long",
                    "prompt": "玄幻大陆废材逆袭",
                    "genre": "玄幻",
                    "style": "热血逆袭",
                    "chapter_word_min": 2600,
                    "chapter_word_max": 3380,
                    "model_id": "K2.6",
                },
                story_plan={
                    "working_title": "玄脉逆天",
                    "logline": "废材少年重开玄脉。",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "开篇"},
                        {"number": 2, "title": "第二章", "goal": "遭遇"},
                        {"number": 3, "title": "第三章", "goal": "反击"},
                    ],
                },
                batch_index=0,
                completed_chapters=[],
                reference_text="",
                model="K2.6",
                requested_batch_size=3,
            )

            self.assertEqual([chapter.number for chapter in drafts], [1, 2, 3])
            self.assertEqual(len(gateway.calls), 3)
            self.assertGreater(gateway.max_active_calls, 1)

    def test_generate_chapter_pair_parallelizes_default_two_chapter_first_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="K2.6",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                    CHAPTER_PARALLEL_DRAFT_ENABLED=True,
                    CHAPTER_PARALLEL_MAX_WORKERS=4,
                )
            )
            gateway = ConcurrentChapterGateway()
            engine.gateway_client = gateway

            drafts = engine.generate_chapter_pair(
                spec={
                    "mode": "long_story",
                    "creative_mode": "original",
                    "novel_size": "long",
                    "prompt": "玄幻大陆废材逆袭",
                    "genre": "玄幻",
                    "style": "热血逆袭",
                    "chapter_word_min": 2600,
                    "chapter_word_max": 3380,
                    "model_id": "K2.6",
                },
                story_plan={
                    "working_title": "玄脉逆天",
                    "logline": "废材少年重开玄脉。",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "开篇"},
                        {"number": 2, "title": "第二章", "goal": "遭遇"},
                    ],
                },
                batch_index=0,
                completed_chapters=[],
                reference_text="",
                model="K2.6",
                requested_batch_size=2,
            )

            self.assertEqual([chapter.number for chapter in drafts], [1, 2])
            self.assertEqual(len(gateway.calls), 2)
            self.assertGreater(gateway.max_active_calls, 1)

    def test_chapter_parallel_worker_limit_caps_at_six(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="K2.6",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                    CHAPTER_PARALLEL_MAX_WORKERS=99,
                )
            )

            self.assertEqual(engine._chapter_parallel_worker_limit(), 6)  # noqa: SLF001

    def test_context_references_text_is_not_truncated_to_eighty_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            long_reference = "参考资料" + ("甲" * 120) + "尾部关键设定"

            reference_excerpt = engine._context_reference(  # noqa: SLF001
                "备用参考",
                {"references_text": long_reference},
            )

            self.assertIn("尾部关键设定", reference_excerpt)
            self.assertGreater(len(reference_excerpt), 80)

    def test_verify_full_story_uses_compact_excerpt_without_losing_tail_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            fake_gateway = FakeGatewayClient(
                [
                    {
                        "overall_score": 100,
                        "issues": [],
                        "summary": "验证通过",
                    }
                ]
            )
            engine.gateway_client = fake_gateway
            head_marker = "开头关键设定"
            middle_marker = "完整正文中段不应进入验证请求"
            tail_marker = "第九千字后的关键伏笔"
            long_content = head_marker + ("甲" * 4200) + middle_marker + ("乙" * 4200) + tail_marker

            engine.verify_full_story(
                completed_chapters=[
                    {
                        "number": 1,
                        "title": "第一章",
                        "summary": "第一章摘要包含关键人物关系",
                        "content": long_content,
                    }
                ],
                story_plan={
                    "working_title": "长文本验证",
                    "chapter_plan": [{"number": 1, "title": "第一章"}],
                },
                spec={"mode": "short_story", "model_id": "gpt-5.4"},
                model="gpt-5.4",
            )

            rendered_prompt = fake_gateway.calls[0]["messages"][-1]["content"]
            self.assertIn("第一章摘要包含关键人物关系", rendered_prompt)
            self.assertIn(head_marker, rendered_prompt)
            self.assertIn(tail_marker, rendered_prompt)
            self.assertNotIn(middle_marker, rendered_prompt)
            self.assertLess(len(rendered_prompt), len(long_content))

    def test_fix_verified_issues_accepts_patch_payload_and_keeps_unchanged_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            engine.gateway_client = FakeGatewayClient(
                [
                    {
                        "patches": [
                            {
                                "number": 2,
                                "title": "第二章",
                                "summary": "第二章修复后摘要",
                                "content": "第二章修复后正文",
                            }
                        ]
                    }
                ]
            )
            original_chapters = [
                {"number": 1, "title": "第一章", "summary": "第一章摘要", "content": "第一章原文"},
                {"number": 2, "title": "第二章", "summary": "第二章摘要", "content": "第二章原文"},
            ]

            fixed = engine.fix_verified_issues(
                completed_chapters=original_chapters,
                verification_report={
                    "issues": [
                        {
                            "severity": "warning",
                            "location": "第二章",
                            "description": "人物动机前后矛盾",
                            "suggestion": "只修复第二章相关段落",
                        }
                    ]
                },
                review_comment="只修复第二章的人物动机。",
                story_plan={
                    "working_title": "补丁修复",
                    "logline": "测试修复补丁。",
                },
                spec={"mode": "short_story", "model_id": "gpt-5.4"},
                model="gpt-5.4",
            )

            self.assertEqual(len(fixed), 2)
            self.assertEqual(fixed[0], original_chapters[0])
            self.assertEqual(fixed[1]["summary"], "第二章修复后摘要")
            self.assertEqual(fixed[1]["content"], "第二章修复后正文")

    def test_verify_full_story_uses_independent_verification_max_tokens_and_tight_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            capability_path = Path(tmp_dir) / "model_capabilities.json"
            capability_path.write_text(
                json.dumps(
                    {
                        "defaults": {
                            "max_input_tokens": 200000,
                            "max_output_tokens": 10000,
                        },
                        "models": {
                            "mimo-v2.5-pro": {
                                "max_input_tokens": 200000,
                                "max_output_tokens": 10000,
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    MODEL_CAPABILITIES_PATH=str(capability_path),
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamSuccessGateway(
                {
                    "overall_score": 96,
                    "issues": [],
                    "summary": "验证通过",
                }
            )
            engine.gateway_client = gateway

            engine.verify_full_story(
                completed_chapters=[
                    {"number": 1, "title": "第一章", "content": "第一章正文"},
                    {"number": 2, "title": "第二章", "content": "第二章正文"},
                ],
                story_plan={
                    "working_title": "独立预算验证",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章"},
                        {"number": 2, "title": "第二章"},
                    ],
                },
                spec={"mode": "long_story", "model_id": "mimo-v2.5-pro"},
                model="mimo-v2.5-pro",
            )

            call = gateway.stream_calls[0]
            self.assertEqual(call["kwargs"].get("max_tokens"), 4096)
            self.assertNotEqual(call["kwargs"].get("max_tokens"), 10000)
            rendered_prompt = call["messages"][-1]["content"]
            self.assertIn("最多 5 个问题", rendered_prompt)
            self.assertIn("description 不超过 60 个字", rendered_prompt)
            self.assertIn("suggestion 不超过 60 个字", rendered_prompt)
            self.assertIn("summary 不超过 80 个字", rendered_prompt)
            self.assertIn("只报告影响主线理解的问题", rendered_prompt)
            self.assertIn("不要逐章复述", rendered_prompt)
            self.assertIn("不要输出分析过程", rendered_prompt)

    def test_verify_full_story_uses_configured_verification_max_tokens_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    VERIFICATION_MAX_TOKENS=1600,
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamSuccessGateway(
                {
                    "overall_score": 98,
                    "issues": [],
                    "summary": "验证通过",
                }
            )
            engine.gateway_client = gateway

            engine.verify_full_story(
                completed_chapters=[
                    {"number": 1, "title": "第一章", "content": "第一章正文"},
                ],
                story_plan={
                    "working_title": "覆盖预算验证",
                    "chapter_plan": [{"number": 1, "title": "第一章"}],
                },
                spec={"mode": "short_story", "model_id": "mimo-v2.5-pro"},
                model="mimo-v2.5-pro",
            )

            self.assertEqual(gateway.stream_calls[0]["kwargs"].get("max_tokens"), 1600)

    def test_verify_full_story_uses_short_budget_for_single_chapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    VERIFICATION_MAX_TOKENS=4096,
                    VERIFICATION_SHORT_MAX_TOKENS=1200,
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamSuccessGateway(
                {
                    "overall_score": 98,
                    "issues": [],
                    "summary": "验证通过",
                }
            )
            engine.gateway_client = gateway

            engine.verify_full_story(
                completed_chapters=[
                    {"number": 1, "title": "第一章", "content": "第一章正文"},
                ],
                story_plan={
                    "working_title": "短验证预算",
                    "chapter_plan": [{"number": 1, "title": "第一章"}],
                },
                spec={"mode": "short_story", "model_id": "mimo-v2.5-pro"},
                model="mimo-v2.5-pro",
            )

            self.assertEqual(gateway.stream_calls[0]["kwargs"].get("max_tokens"), 1200)

    def test_verify_chapter_window_uses_recent_one_fulltext_and_last_ten_summaries_without_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    CHAPTER_GATE_RECENT_FULLTEXT_COUNT=1,
                    CHAPTER_GATE_SUMMARY_WINDOW_SIZE=10,
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamSuccessGateway(
                {
                    "overall_score": 88,
                    "issues": [],
                    "summary": "门禁通过",
                }
            )
            engine.gateway_client = gateway

            completed_chapters = [
                {
                    "number": number,
                    "title": f"第{number}章",
                    "summary": f"摘要标记-{number}",
                    "content": f"正文标记-{number}",
                }
                for number in range(1, 20)
            ]
            current_pair = [
                {
                    "number": 20,
                    "title": "第20章",
                    "summary": "摘要标记-20",
                    "content": "正文标记-20",
                }
            ]

            engine.verify_chapter_window(
                current_chapter_pair=current_pair,
                completed_chapters=completed_chapters,
                story_plan={
                    "working_title": "章节门禁窗口",
                    "chapter_plan": [{"number": number, "title": f"第{number}章"} for number in range(1, 21)],
                },
                spec={"mode": "long_story", "model_id": "mimo-v2.5-pro"},
                model="mimo-v2.5-pro",
            )

            rendered_prompt = gateway.stream_calls[0]["messages"][-1]["content"]
            self.assertIn("摘要标记-9", rendered_prompt)
            self.assertIn("摘要标记-18", rendered_prompt)
            self.assertNotIn("摘要标记-8", rendered_prompt)
            self.assertNotIn("摘要标记-19", rendered_prompt)
            self.assertIn("正文标记-19", rendered_prompt)
            self.assertIn("正文标记-20", rendered_prompt)

    def test_verify_full_story_passes_low_reasoning_effort_to_verification_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    VERIFICATION_REASONING_EFFORT="low",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            gateway = StreamSuccessGateway(
                {
                    "overall_score": 98,
                    "issues": [],
                    "summary": "验证通过",
                }
            )
            engine.gateway_client = gateway

            engine.verify_full_story(
                completed_chapters=[
                    {"number": 1, "title": "第一章", "content": "第一章正文"},
                ],
                story_plan={
                    "working_title": "验证推理控制",
                    "chapter_plan": [{"number": 1, "title": "第一章"}],
                },
                spec={"mode": "short_story", "model_id": "mimo-v2.5-pro"},
                model="mimo-v2.5-pro",
            )

            self.assertEqual(gateway.stream_calls[0]["kwargs"].get("reasoning_effort"), "low")

    def test_verify_full_story_retries_reasoning_only_length_without_generic_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            capability_path = Path(tmp_dir) / "model_capabilities.json"
            capability_path.write_text(
                json.dumps(
                    {
                        "defaults": {
                            "max_input_tokens": 200000,
                            "max_output_tokens": 10000,
                        },
                        "models": {
                            "mimo-v2.5-pro": {
                                "max_input_tokens": 200000,
                                "max_output_tokens": 10000,
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="mimo-v2.5-pro",
                    MODEL_CAPABILITIES_PATH=str(capability_path),
                    VERIFICATION_SHORT_CHAPTER_THRESHOLD=0,
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            payload = {
                "overall_score": 95,
                "issues": [],
                "summary": "验证通过",
            }
            gateway = StreamReasoningOnlyLengthThenSuccessGateway(payload)
            engine.gateway_client = gateway

            result = engine.verify_full_story(
                completed_chapters=[
                    {"number": 1, "title": "第一章", "content": "第一章正文"},
                ],
                story_plan={
                    "working_title": "验证重试",
                    "chapter_plan": [{"number": 1, "title": "第一章"}],
                },
                spec={"mode": "short_story", "model_id": "mimo-v2.5-pro"},
                model="mimo-v2.5-pro",
            )

            self.assertEqual(result, payload)
            self.assertEqual(len(gateway.calls), 2)
            self.assertEqual(gateway.calls[0]["kwargs"].get("max_tokens"), 4096)
            self.assertEqual(gateway.calls[1]["kwargs"].get("max_tokens"), 8192)
            self.assertNotIn("重新输出一个完整、可解析的 JSON 对象", gateway.calls[1]["messages"][-1]["content"])
            self.assertIn("不要输出分析过程", gateway.calls[1]["messages"][-1]["content"])

    def test_generate_draft_reuses_previous_turns_as_message_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            fake_gateway = FakeGatewayClient(
                [
                    {
                        "number": 1,
                        "title": "第一章",
                        "summary": "主角发现异样",
                        "content": "第一章内容",
                    },
                    {
                        "number": 2,
                        "title": "第二章",
                        "summary": "主角继续追查",
                        "content": "第二章内容",
                    },
                ]
            )
            engine.gateway_client = fake_gateway

            draft = engine.generate_draft(
                spec={
                    "mode": "long_story",
                    "creative_mode": "original",
                    "novel_size": "long",
                    "prompt": "写一篇追查夜航记录的悬疑故事",
                    "genre": "悬疑",
                    "style": "冷静克制",
                    "chapter_word_min": 2200,
                    "chapter_word_max": 2860,
                    "model_id": "gpt-5.4",
                },
                story_plan={
                    "working_title": "夜航记录",
                    "logline": "档案员追查被改动的记录",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "发现问题"},
                        {"number": 2, "title": "第二章", "goal": "继续追查"},
                    ],
                },
                reference_text="港口、潮汐、夜航记录。",
                context_packet={
                    "memory_text": "保持冷静克制，记录职业细节。",
                    "references_text": "港口、潮汐、夜航记录。",
                },
                model="gpt-5.4",
            )

            self.assertEqual(len(draft.chapters), 2)
            self.assertEqual(len(fake_gateway.calls), 2)
            self.assertEqual(len(fake_gateway.calls[0]["messages"]), 2)
            second_call_messages = fake_gateway.calls[1]["messages"]
            self.assertGreaterEqual(len(second_call_messages), 4)
            self.assertTrue(any(message["role"] == "assistant" for message in second_call_messages))
            self.assertIn("第一章", second_call_messages[-2]["content"])

    def test_generate_draft_can_start_from_existing_question_answer_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            fake_gateway = FakeGatewayClient(
                [
                    {
                        "number": 1,
                        "title": "第一章",
                        "summary": "主角根据审核意见继续推进",
                        "content": "第一章内容",
                    }
                ]
            )
            engine.gateway_client = fake_gateway

            engine.generate_draft(
                spec={
                    "mode": "short_story",
                    "creative_mode": "original",
                    "novel_size": "short",
                    "prompt": "写一篇追查夜航记录的悬疑故事",
                    "genre": "悬疑",
                    "style": "冷静克制",
                    "chapter_word_min": 1500,
                    "chapter_word_max": 1950,
                    "model_id": "gpt-5.4",
                },
                story_plan={
                    "working_title": "夜航记录",
                    "logline": "档案员追查被改动的记录",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "发现问题"},
                    ],
                },
                reference_text="港口、潮汐、夜航记录。",
                context_packet={
                    "memory_text": "保持冷静克制，记录职业细节。",
                    "references_text": "港口、潮汐、夜航记录。",
                },
                model="gpt-5.4",
                initial_conversation_history=[
                    {"role": "system", "content": "你是小说策划助手。"},
                    {"role": "user", "content": "q1: 请先生成大纲。"},
                    {"role": "assistant", "content": "a1: 这是大纲 JSON。"},
                    {"role": "user", "content": "q2: 根据我补充的修改意见继续写正文。"},
                ],
            )

            first_call_messages = fake_gateway.calls[0]["messages"]
            self.assertGreaterEqual(len(first_call_messages), 5)
            self.assertEqual(first_call_messages[0]["role"], "system")
            self.assertEqual(first_call_messages[1]["role"], "user")
            self.assertEqual(first_call_messages[2]["role"], "assistant")
            self.assertIn("q2:", first_call_messages[3]["content"])

    def test_generate_draft_uses_current_stage_system_prompt_when_history_contains_previous_stage_system_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            fake_gateway = FakeGatewayClient(
                [
                    {
                        "number": 1,
                        "title": "第一章",
                        "summary": "主角根据审核意见继续推进",
                        "content": "第一章内容",
                    }
                ]
            )
            engine.gateway_client = fake_gateway

            engine.generate_draft(
                spec={
                    "mode": "short_story",
                    "prompt": "写一篇追查夜航记录的悬疑故事",
                    "genre": "悬疑",
                    "style": "冷静克制",
                    "model_id": "gpt-5.4",
                },
                story_plan={
                    "working_title": "夜航记录",
                    "logline": "档案员追查被改动的记录",
                    "chapter_plan": [
                        {"number": 1, "title": "第一章", "goal": "发现问题"},
                    ],
                },
                reference_text="港口、潮汐、夜航记录。",
                context_packet={
                    "memory_text": "保持冷静克制，记录职业细节。",
                    "references_text": "港口、潮汐、夜航记录。",
                },
                model="gpt-5.4",
                initial_conversation_history=[
                    {"role": "system", "content": "你是小说策划助手。"},
                    {"role": "user", "content": "请先生成大纲。"},
                    {"role": "assistant", "content": "这是大纲 JSON。"},
                ],
            )

            first_call_messages = fake_gateway.calls[0]["messages"]
            self.assertEqual(first_call_messages[0]["role"], "system")
            self.assertIn("中文小说章节起草助手", first_call_messages[0]["content"])
            self.assertNotEqual(first_call_messages[0]["content"], "你是小说策划助手。")

    def test_generate_chapter_pair_includes_previous_fulltext_uses_recent_twenty_summaries_and_existing_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="gpt-5.4",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            fake_gateway = FakeGatewayClient(
                [
                    {
                        "number": 22,
                        "title": "第二十二章",
                        "summary": "主角进入最终调查。",
                        "content": "第二十二章内容",
                    }
                ]
            )
            engine.gateway_client = fake_gateway

            completed = [
                {
                    "number": number,
                    "title": f"第{number}章",
                    "summary": f"摘要{number}",
                    "content": f"第{number}章正文",
                }
                for number in range(1, 22)
            ]

            engine.generate_chapter_pair(
                spec={
                    "mode": "long_story",
                    "creative_mode": "original",
                    "novel_size": "long",
                    "prompt": "写一篇校园悬疑长篇",
                    "genre": "悬疑",
                    "style": "冷静克制",
                    "chapter_word_min": 2200,
                    "chapter_word_max": 2860,
                    "model_id": "gpt-5.4",
                },
                story_plan={
                    "working_title": "旧校钟声",
                    "logline": "学生在深夜追查教学楼异响来源。",
                    "chapter_plan": [
                        {"number": number, "title": f"第{number}章", "goal": f"推进{number}"}
                        for number in range(1, 23)
                    ],
                },
                batch_index=21,
                completed_chapters=completed,
                reference_text="旧教学楼、巡夜钟声。",
                model="gpt-5.4",
                draft_seeds={22: "这是第二十二章的历史草稿片段。"},
            )

            prompt = fake_gateway.calls[0]["messages"][-1]["content"]
            self.assertIn("上一章全文：第21章正文", prompt)
            self.assertIn("当前章节历史草稿：这是第二十二章的历史草稿片段。", prompt)
            self.assertIn("第2章:摘要2", prompt)
            self.assertIn("第21章:摘要21", prompt)
            self.assertNotIn("第1章:摘要1", prompt)

    def test_build_story_plan_uses_persistent_response_cache_across_engine_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                openai_api_key="test-key",
                default_chat_model="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            first_gateway = FakeGatewayClient(
                [
                    {
                        "working_title": "潮汐档案",
                        "logline": "档案员发现夜航记录被篡改。",
                        "world_notes": ["港口潮湿，档案室逼仄。"],
                        "character_notes": ["主角是细致的档案员。"],
                        "chapter_plan": [
                            {"number": 1, "title": "引子", "goal": "发现问题"},
                            {"number": 2, "title": "推进", "goal": "继续追查"},
                        ],
                    }
                ]
            )
            second_gateway = FakeGatewayClient(
                [
                    {
                        "working_title": "不应被调用",
                        "logline": "不应被调用",
                        "world_notes": [],
                        "character_notes": [],
                        "chapter_plan": [],
                    }
                ]
            )

            first_engine = StoryEngine(settings)
            first_engine.gateway_client = first_gateway
            second_engine = StoryEngine(settings)
            second_engine.gateway_client = second_gateway

            spec = {
                "mode": "short_story",
                "prompt": "写一个港口档案员追查旧案的悬疑短篇",
                "genre": "悬疑",
                "style": "冷静克制",
                "target_words": 1800,
                "model_id": "gpt-5.4",
            }
            context_packet = {
                "memory_text": "保留职业细节。",
                "references_text": "港口、灯塔、夜航日志。",
            }

            first_plan = first_engine.build_story_plan(
                spec=spec,
                reference_text="港口、灯塔、夜航日志。",
                context_packet=context_packet,
                model="gpt-5.4",
            )
            second_plan = second_engine.build_story_plan(
                spec=spec,
                reference_text="港口、灯塔、夜航日志。",
                context_packet=context_packet,
                model="gpt-5.4",
            )

            self.assertEqual(first_plan.working_title, second_plan.working_title)
            self.assertEqual(len(first_gateway.calls), 1)
            self.assertEqual(len(second_gateway.calls), 0)

    def test_build_story_plan_retries_once_when_first_structured_response_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="MiniMax-M2.7-highspeed",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            fake_gateway = FakeGatewayClient(
                [
                    "```json\n{\"working_title\":\"雨夜监控室\",\"world_notes\":[\"服务区位于山区\"]\n```",
                    {
                        "working_title": "雨夜监控室",
                        "logline": "监控员发现异常监控画面并追查真相。",
                        "world_notes": ["服务区位于山区。"],
                        "character_notes": ["主角是值班监控员。"],
                        "chapter_plan": [
                            {"number": 1, "title": "引子", "goal": "发现异常"},
                            {"number": 2, "title": "推进", "goal": "继续追查"},
                        ],
                    },
                ]
            )
            engine.gateway_client = fake_gateway

            plan = engine.build_story_plan(
                spec={
                    "mode": "short_story",
                    "prompt": "写一个高速服务区悬疑短篇",
                    "genre": "悬疑",
                    "style": "克制冷静",
                    "target_words": 1200,
                    "model_id": "MiniMax-M2.7-highspeed",
                },
                reference_text="",
                context_packet=None,
                model="MiniMax-M2.7-highspeed",
            )

            self.assertEqual(plan.working_title, "雨夜监控室")
            self.assertEqual(len(fake_gateway.calls), 2)
            self.assertIn("更精简且完整的 JSON 对象", fake_gateway.calls[1]["messages"][-1]["content"])
            self.assertIn("planned_chapter_count", fake_gateway.calls[1]["messages"][-1]["content"])

    def test_build_story_plan_retry_requests_compact_outline_json_after_truncated_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="MiniMax-M2.7-highspeed",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            fake_gateway = FakeGatewayClient(
                [
                    "```json\n{\"working_title\":\"神级武魂：混沌龙主\",\"logline\":\"过长输出被截断\",\"world_notes\":[\"斗罗大陆魂师体系极其复杂\"",
                    {
                        "working_title": "神级武魂：混沌龙主",
                        "logline": "凌天觉醒神级武魂，在斗罗大陆崛起。",
                        "world_notes": ["斗罗大陆以魂师与魂兽体系为核心。"],
                        "character_notes": ["凌天拥有混沌龙魂武魂。"],
                        "planned_chapter_count": 12,
                        "chapter_plan": [
                            {"number": 1, "title": "武魂觉醒", "goal": "主角初登场"},
                            {"number": 2, "title": "学院入学", "goal": "进入主线"},
                        ],
                    },
                ]
            )
            engine.gateway_client = fake_gateway

            plan = engine.build_story_plan(
                spec={
                    "mode": "fanfic",
                    "creative_mode": "fanfic",
                    "novel_size": "short",
                    "prompt": "主角拥有神级武魂，在斗罗开后宫。",
                    "genre": "玄幻",
                    "style": "",
                    "chapter_word_min": 3000,
                    "chapter_word_max": 3900,
                    "chapter_count_range_text": "8 到 80 章",
                    "model_id": "MiniMax-M2.7-highspeed",
                },
                reference_text="",
                context_packet=None,
                model="MiniMax-M2.7-highspeed",
            )

            self.assertEqual(plan.working_title, "神级武魂：混沌龙主")
            self.assertEqual(len(fake_gateway.calls), 2)
            retry_prompt = fake_gateway.calls[1]["messages"][-1]["content"]
            self.assertIn("压缩 world_notes", retry_prompt)
            self.assertIn("planned_chapter_count", retry_prompt)
            self.assertIn("只返回最终 JSON 对象", retry_prompt)

    def test_build_story_plan_revision_retries_once_when_first_revision_response_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            engine = StoryEngine(
                Settings(
                    openai_api_key="test-key",
                    default_chat_model="MiniMax-M2.7-highspeed",
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                )
            )
            fake_gateway = FakeGatewayClient(
                [
                    "结果如下：{\"working_title\":\"修订后标题\",\"chapter_plan\":[{\"number\":1,\"title\":\"引子\"}]}",
                    {
                        "working_title": "修订后标题",
                        "logline": "修订后的梗概。",
                        "world_notes": ["修订后的世界观。"],
                        "character_notes": ["修订后的人物。"],
                        "chapter_plan": [
                            {"number": 1, "title": "引子", "goal": "发现异常"},
                            {"number": 2, "title": "推进", "goal": "继续追查"},
                        ],
                    },
                ]
            )
            engine.gateway_client = fake_gateway

            plan = engine.build_story_plan(
                spec={
                    "mode": "short_story",
                    "prompt": "写一个高速服务区悬疑短篇",
                    "genre": "悬疑",
                    "style": "克制冷静",
                    "target_words": 1200,
                    "model_id": "MiniMax-M2.7-highspeed",
                },
                reference_text="",
                context_packet=None,
                model="MiniMax-M2.7-highspeed",
                revision_comment="请加强反转。",
                original_plan={
                    "working_title": "原始标题",
                    "logline": "原始梗概。",
                    "world_notes": ["原始世界观。"],
                    "character_notes": ["原始人物。"],
                    "chapter_plan": [
                        {"number": 1, "title": "引子", "goal": "发现异常"},
                    ],
                },
            )

            self.assertEqual(plan.working_title, "修订后标题")
            self.assertEqual(len(fake_gateway.calls), 2)
            self.assertIn("更精简且完整的 JSON 对象", fake_gateway.calls[1]["messages"][-1]["content"])
            self.assertIn("planned_chapter_count", fake_gateway.calls[1]["messages"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
