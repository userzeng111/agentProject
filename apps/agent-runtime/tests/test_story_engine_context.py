import datetime
import tempfile
import unittest
from pathlib import Path

if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc

from app.llm.story_engine import StoryEngine
from app.settings.config import Settings


class FakeGatewayClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, messages, model=None):
        self.calls.append(
            {
                "messages": [dict(item) for item in messages],
                "model": model,
            }
        )
        return self.responses[len(self.calls) - 1]

    def list_models(self):
        return []


class StoryEngineContextTests(unittest.TestCase):
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
                    "prompt": "写一篇学院流玄幻故事",
                    "genre": "玄幻",
                    "style": "保留热血成长感",
                    "style_profile_id": "douluo",
                    "style_profile_name": "唐家三少风格实例",
                    "style_guidance": "实例：唐家三少风格实例\n语言规则：术语密集\n情节规则：力量升级驱动",
                    "model_id": "gpt-5.4",
                    "target_words": 2600,
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
            self.assertNotIn("保留冷静克制的中文叙事风格", rendered_prompt)

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
            self.assertIn("请重新输出一个完整、可解析的 JSON 对象", fake_gateway.calls[1]["messages"][-1]["content"])

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
            self.assertIn("请重新输出一个完整、可解析的 JSON 对象", fake_gateway.calls[1]["messages"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
