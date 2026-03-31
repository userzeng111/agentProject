import unittest

from langgraph.types import Command

from app.context.manager import ContextManager
from app.domain.models import ChapterDraft, ChapterPlan, DraftResult, StoryPlan
from app.graph.main_graph import build_graph


class FakeEngine:
    def __init__(self) -> None:
        self.outline_contexts = []
        self.draft_contexts = []

    def build_story_plan(self, spec, reference_text, context_packet=None, model=None):
        self.outline_contexts.append(context_packet)
        return StoryPlan(
            working_title="测试标题",
            logline="测试梗概",
            world_notes=["世界观"],
            character_notes=["人物"],
            chapter_plan=[ChapterPlan(number=1, title="第一章", goal="建立冲突")],
        )

    def generate_draft(self, spec, story_plan, reference_text, context_packet=None, model=None, progress_callback=None):
        self.draft_contexts.append(context_packet)
        return DraftResult(
            title="测试标题",
            summary="测试梗概",
            body="测试正文",
            chapters=[
                ChapterDraft(
                    number=1,
                    title="第一章",
                    summary="建立冲突",
                    content="测试正文",
                )
            ],
        )


class FakeModelCatalog:
    def get_model_profile(self, model_id):
        return {
            "id": model_id or "gpt-5.4",
            "provider": "openai_compatible",
            "capabilities": {
                "context_window": {
                    "max_input_tokens": 256000,
                    "max_output_tokens": 16000,
                }
            },
        }


class GraphContextIntegrationTests(unittest.TestCase):
    def test_graph_builds_outline_and_draft_context_snapshots(self) -> None:
        engine = FakeEngine()
        graph = build_graph(
            engine,
            context_manager=ContextManager(),
            model_catalog=FakeModelCatalog(),
        )
        config = {"configurable": {"thread_id": "task-graph-1"}}
        initial_state = {
            "task_id": "task-graph-1",
            "input_payload": {
                "mode": "short_story",
                "prompt": "写一篇临海城市的悬疑故事",
                "genre": "悬疑",
                "style": "冷静克制",
                "target_words": 1800,
                "audience": "",
                "banned": "",
                "title_hint": "潮汐谜案",
                "model_id": "gpt-5.4",
            },
            "reference_text": "港口、潮水、旧案卷宗。",
        }

        first_result = graph.invoke(initial_state, config=config)

        self.assertIn("__interrupt__", first_result)
        first_snapshot = graph.get_state(config).values
        self.assertIn("outline_context_snapshot", first_snapshot)
        self.assertTrue(engine.outline_contexts)
        self.assertIsNotNone(engine.outline_contexts[0])

        graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)

        final_snapshot = graph.get_state(config).values
        self.assertIn("draft_context_snapshot", final_snapshot)
        self.assertTrue(engine.draft_contexts)
        self.assertIsNotNone(engine.draft_contexts[0])


if __name__ == "__main__":
    unittest.main()
