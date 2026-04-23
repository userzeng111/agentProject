import unittest

from app.context.manager import ContextManager
from app.domain.models import ChapterDraft, ChapterPlan, StoryPlan
from app.graph.main_graph import build_graph


class FakeEngine:
    def __init__(self) -> None:
        self.gateway_client = None

    def build_story_plan(self, spec, reference_text, context_packet=None, model=None):
        return StoryPlan(
            working_title="测试标题",
            logline="测试梗概",
            world_notes=["世界观"],
            character_notes=["人物"],
            chapter_plan=[ChapterPlan(number=1, title="第一章", goal="建立冲突")],
        )

    def generate_chapter_pair(
        self,
        spec,
        story_plan,
        batch_index,
        completed_chapters,
        reference_text,
        context_packet=None,
        model=None,
        progress_callback=None,
    ):
        return [ChapterDraft(number=1, title="第一章", summary="建立冲突", content="正文")]

    def verify_full_story(self, completed_chapters, story_plan, spec, reference_text, context_packet=None, model=None):
        return {"overall_score": 100, "issues": []}


class FakeModelCatalog:
    def get_model_profile(self, model_id):
        return {
            "id": model_id or "gpt-5.4",
            "provider": "openai_compatible",
            "capabilities": {
                "context_window": {"max_input_tokens": 256000, "max_output_tokens": 16000}
            },
        }


class FakeNovelSkillService:
    def build_runtime_context(self, *, mode: str, style_profile_id: str = "", custom_style: str = ""):
        canon_guidance = ""
        style_guidance = f"实例：唐家三少风格实例\n补充要求：{custom_style}"
        if mode == "fanfic":
            canon_guidance = f"原作《斗罗大陆》世界观约束\n补充要求：{custom_style}"
            style_guidance = custom_style
        return {
            "workflow_guidance": "workflow:/constitution -> /specify -> /write",
            "style_profile_id": style_profile_id,
            "style_profile_name": "唐家三少风格实例",
            "style_profile": {
                "id": style_profile_id,
                "name": "唐家三少风格实例",
            },
            "canon_guidance": canon_guidance,
            "style_guidance": style_guidance,
            "active_package_ids": ["novel-writer-workflow-guide", "bisheng-style"],
            "active_instance_id": style_profile_id,
            "custom_style": custom_style,
        }


class GraphStyleProfileTests(unittest.TestCase):
    def test_style_remix_request_is_compiled_into_normalized_spec(self) -> None:
        graph = build_graph(
            FakeEngine(),
            context_manager=ContextManager(),
            model_catalog=FakeModelCatalog(),
            novel_skill_service=FakeNovelSkillService(),
        )
        config = {"configurable": {"thread_id": "task-style-graph"}}
        initial_state = {
            "task_id": "task-style-graph",
            "input_payload": {
                "mode": "style_remix",
                "prompt": "写一篇学院流玄幻故事",
                "genre": "玄幻",
                "style": "保留热血成长感",
                "style_profile_id": "douluo",
                "target_words": 2400,
                "audience": "",
                "banned": "",
                "title_hint": "魂环初现",
                "model_id": "gpt-5.4",
            },
            "reference_text": "",
        }

        graph.invoke(initial_state, config=config)
        snapshot = graph.get_state(config).values

        self.assertEqual(snapshot["normalized_spec"]["style_profile_id"], "douluo")
        self.assertEqual(snapshot["normalized_spec"]["style_profile_name"], "唐家三少风格实例")
        self.assertIn("/constitution", snapshot["normalized_spec"]["workflow_guidance"])
        self.assertIn("补充要求：保留热血成长感", snapshot["normalized_spec"]["style_guidance"])

    def test_fanfic_request_compiles_profile_into_canon_guidance(self) -> None:
        graph = build_graph(
            FakeEngine(),
            context_manager=ContextManager(),
            model_catalog=FakeModelCatalog(),
            novel_skill_service=FakeNovelSkillService(),
        )
        config = {"configurable": {"thread_id": "task-fanfic-style-graph"}}
        initial_state = {
            "task_id": "task-fanfic-style-graph",
            "input_payload": {
                "mode": "fanfic",
                "creative_mode": "fanfic",
                "novel_size": "long",
                "prompt": "写一篇斗罗大陆同人故事",
                "genre": "玄幻",
                "style": "保留学院冲突",
                "style_profile_id": "douluo",
                "chapter_word_min": 2600,
                "audience": "",
                "banned": "",
                "title_hint": "史莱克新生",
                "model_id": "gpt-5.4",
            },
            "reference_text": "",
        }

        graph.invoke(initial_state, config=config)
        snapshot = graph.get_state(config).values

        self.assertEqual(snapshot["normalized_spec"]["creative_mode"], "fanfic")
        self.assertIn("世界观约束", snapshot["normalized_spec"]["canon_guidance"])
        self.assertEqual(snapshot["normalized_spec"]["style_guidance"], "保留学院冲突")
