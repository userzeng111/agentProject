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

    def test_verify_full_story_sends_complete_text_without_silent_eight_thousand_char_truncation(self) -> None:
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
            tail_marker = "第九千字后的关键伏笔"

            engine.verify_full_story(
                completed_chapters=[
                    {
                        "number": 1,
                        "title": "第一章",
                        "content": ("甲" * 8500) + tail_marker,
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
            self.assertIn(tail_marker, rendered_prompt)

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
