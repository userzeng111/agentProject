try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

import unittest

from langgraph.types import Command

from app.domain.models import ChapterPlan, StoryPlan
from app.graph.main_graph import build_default_callbacks, build_graph, build_normalized_spec
from tests.fakes import FakeContextManager, FakeStoryEngine


class FakeMismatchedPlanEngine(FakeStoryEngine):
    def build_story_plan(self, spec, reference_text, context_packet=None, model=None, revision_comment="", original_plan=None):
        return StoryPlan(
            working_title="计划错位",
            logline="planned_chapter_count 与 chapter_plan 长度不一致",
            world_notes=["世界观"],
            character_notes=["人物"],
            planned_chapter_count=6,
            chapter_plan=[
                ChapterPlan(number=1, title="第1章", goal="目标1"),
                ChapterPlan(number=2, title="第2章", goal="目标2"),
                ChapterPlan(number=3, title="第3章", goal="目标3"),
            ],
        )


class GraphChapterPairLoopTests(unittest.TestCase):
    def test_long_novel_normalized_spec_uses_default_target_chapter_constraints(self) -> None:
        spec = build_normalized_spec(
            {
                "mode": "long_story",
                "creative_mode": "original",
                "novel_size": "long",
                "chapter_word_min": 3000,
                "prompt": "写一部长篇悬疑小说",
            }
        )

        self.assertEqual(spec["creative_mode"], "original")
        self.assertEqual(spec["novel_size"], "long")
        self.assertEqual(spec["chapter_word_min"], 3000)
        self.assertEqual(spec["chapter_word_max"], 3900)
        self.assertEqual(spec["target_chapter_count"], 400)
        self.assertEqual(spec["chapter_count_min"], 360)
        self.assertEqual(spec["chapter_count_max"], 440)
        self.assertEqual(spec["chapter_count_range"], {"min": 360, "max": 440})
        self.assertEqual(spec["chapter_count_range_text"], "360 到 440 章")

    def test_normalized_spec_preserves_requested_target_chapter_constraints(self) -> None:
        spec = build_normalized_spec(
            {
                "mode": "fanfic",
                "creative_mode": "fanfic",
                "novel_size": "medium",
                "chapter_word_min": 2600,
                "prompt": "写一个中篇同人故事",
                "target_chapter_count": 100,
                "chapter_count_min": 90,
                "chapter_count_max": 110,
            }
        )

        self.assertEqual(spec["target_chapter_count"], 100)
        self.assertEqual(spec["chapter_count_min"], 90)
        self.assertEqual(spec["chapter_count_max"], 110)
        self.assertEqual(spec["chapter_count_range"], {"min": 90, "max": 110})
        self.assertEqual(spec["chapter_count_range_text"], "90 到 110 章")

    def test_five_chapters_must_finish_all_pairs_before_verification(self) -> None:
        engine = FakeStoryEngine()
        callbacks = build_default_callbacks(
            engine,
            context_manager=FakeContextManager(),
        )
        graph = build_graph(callbacks=callbacks)
        config = {"configurable": {"thread_id": "task-five-chapters"}}
        initial_state = {
            "task_id": "task-five-chapters",
            "input_payload": {
                "mode": "short_story",
                "creative_mode": "original",
                "novel_size": "short",
                "prompt": "写一个五章恐怖故事",
                "genre": "恐怖",
                "style": "冷静克制",
                "chapter_word_min": 1800,
                "audience": "",
                "banned": "",
                "title_hint": "夜半回廊",
                "model_id": "gpt-5.4",
            },
            "reference_text": "",
        }

        first = graph.invoke(initial_state, config=config)
        self.assertEqual(first["__interrupt__"][0].value["type"], "outline_review")

        second = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(second["__interrupt__"][0].value["type"], "chapter_pair_review")
        self.assertEqual(second["__interrupt__"][0].value["batch_index"], 0)

        third = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(third["__interrupt__"][0].value["type"], "chapter_pair_review")
        self.assertEqual(third["__interrupt__"][0].value["batch_index"], 2)

        fourth = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(fourth["__interrupt__"][0].value["type"], "chapter_pair_review")
        self.assertEqual(fourth["__interrupt__"][0].value["batch_index"], 4)

        fifth = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(fifth["__interrupt__"][0].value["type"], "verification_review")

        final_result = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertNotIn("__interrupt__", final_result)
        self.assertEqual(engine.generated_batch_indexes, [0, 2, 4])
        self.assertEqual(len(final_result["draft_result"]["chapters"]), 5)

    def test_style_remix_long_story_can_switch_to_single_chapter_batches_after_first_pair(self) -> None:
        engine = FakeStoryEngine()
        callbacks = build_default_callbacks(
            engine,
            context_manager=FakeContextManager(),
        )
        graph = build_graph(callbacks=callbacks)
        config = {"configurable": {"thread_id": "task-style-remix-batches"}}
        initial_state = {
            "task_id": "task-style-remix-batches",
            "input_payload": {
                "mode": "style_remix",
                "creative_mode": "style_remix",
                "novel_size": "long",
                "prompt": "写一个五章学院流玄幻故事",
                "genre": "玄幻",
                "style": "热血成长",
                "style_profile_id": "douluodalu",
                "chapter_word_min": 2600,
                "audience": "",
                "banned": "",
                "title_hint": "星魂入学",
                "model_id": "gpt-5.4",
            },
            "reference_text": "",
        }

        first = graph.invoke(initial_state, config=config)
        self.assertEqual(first["__interrupt__"][0].value["type"], "outline_review")

        second = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(second["__interrupt__"][0].value["type"], "chapter_pair_review")
        self.assertEqual(len(second["__interrupt__"][0].value["chapter_pair"]), 2)

        third = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(third["__interrupt__"][0].value["type"], "chapter_pair_review")
        self.assertEqual(third["__interrupt__"][0].value["batch_index"], 2)
        self.assertEqual(len(third["__interrupt__"][0].value["chapter_pair"]), 1)

        fourth = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(fourth["__interrupt__"][0].value["batch_index"], 3)
        self.assertEqual(len(fourth["__interrupt__"][0].value["chapter_pair"]), 1)

        fifth = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(fifth["__interrupt__"][0].value["batch_index"], 4)
        self.assertEqual(len(fifth["__interrupt__"][0].value["chapter_pair"]), 1)

        sixth = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(sixth["__interrupt__"][0].value["type"], "verification_review")

    def test_graph_uses_actual_chapter_plan_length_when_planned_count_is_larger(self) -> None:
        engine = FakeMismatchedPlanEngine()
        callbacks = build_default_callbacks(
            engine,
            context_manager=FakeContextManager(),
        )
        graph = build_graph(callbacks=callbacks)
        config = {"configurable": {"thread_id": "task-mismatched-plan-count"}}
        initial_state = {
            "task_id": "task-mismatched-plan-count",
            "input_payload": {
                "mode": "short_story",
                "creative_mode": "original",
                "novel_size": "short",
                "prompt": "写一个三章故事",
                "genre": "悬疑",
                "style": "冷静克制",
                "chapter_word_min": 1800,
                "audience": "",
                "banned": "",
                "title_hint": "计划错位",
                "model_id": "gpt-5.4",
            },
            "reference_text": "",
        }

        first = graph.invoke(initial_state, config=config)
        self.assertEqual(first["__interrupt__"][0].value["type"], "outline_review")

        second = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(second["__interrupt__"][0].value["type"], "chapter_pair_review")
        self.assertEqual(second["__interrupt__"][0].value["batch_index"], 0)

        third = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(third["__interrupt__"][0].value["type"], "chapter_pair_review")
        self.assertEqual(third["__interrupt__"][0].value["batch_index"], 2)
        self.assertEqual(len(third["__interrupt__"][0].value["chapter_pair"]), 1)

        fourth = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertEqual(fourth["__interrupt__"][0].value["type"], "verification_review")

        final_result = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertNotIn("__interrupt__", final_result)
        self.assertEqual(engine.generated_batch_indexes, [0, 2])
        self.assertEqual(len(final_result["draft_result"]["chapters"]), 3)


if __name__ == "__main__":
    unittest.main()
