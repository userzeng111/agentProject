import datetime
import unittest

from langgraph.types import Command

if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc

from app.domain.models import ChapterDraft, ChapterPlan, StoryPlan
from app.graph.main_graph import build_graph


class FakePacket:
    def __init__(self, stage: str) -> None:
        self.stage = stage

    def model_dump(self, mode: str = "json") -> dict:
        return {"stage": self.stage, "mode": mode}


class FakeSnapshot:
    def __init__(self, stage: str) -> None:
        self.packet = FakePacket(stage)
        self.stage = stage

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "stage": self.stage,
            "mode": mode,
            "packet": self.packet.model_dump(mode=mode),
        }


class FakeContextManager:
    def build_snapshot(self, task_id, stage, instruction, model_profile, references, memory_items):
        return FakeSnapshot(stage)


class FakeEngine:
    def __init__(self) -> None:
        self.generated_batch_indexes: list[int] = []
        self.generated_batch_sizes: list[int] = []

    def build_story_plan(self, spec, reference_text, context_packet=None, model=None, revision_comment="", original_plan=None):
        return StoryPlan(
            working_title="夜半回廊",
            logline="测试梗概",
            world_notes=["世界观"],
            character_notes=["人物"],
            chapter_plan=[
                ChapterPlan(number=1, title="第1章", goal="目标1"),
                ChapterPlan(number=2, title="第2章", goal="目标2"),
                ChapterPlan(number=3, title="第3章", goal="目标3"),
                ChapterPlan(number=4, title="第4章", goal="目标4"),
                ChapterPlan(number=5, title="第5章", goal="目标5"),
            ],
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
        self.generated_batch_indexes.append(batch_index)
        chapter_plan = story_plan.get("chapter_plan") or []
        if spec.get("mode") == "style_remix":
            batch_size = 2 if len(completed_chapters) == 0 else 1
        else:
            batch_size = 2
        self.generated_batch_sizes.append(batch_size)
        pair = []
        for chapter in chapter_plan[batch_index : batch_index + batch_size]:
            pair.append(
                ChapterDraft(
                    number=chapter["number"],
                    title=chapter["title"],
                    summary=f"{chapter['title']} 摘要",
                    content=f"{chapter['title']} 正文",
                )
            )
        return pair

    def revise_chapter_pair(
        self,
        current_pair,
        revision_comment,
        spec,
        story_plan,
        completed_chapters,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return [ChapterDraft.model_validate(item) for item in current_pair]

    def verify_full_story(
        self,
        completed_chapters,
        story_plan,
        spec,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return {"overall_score": 100, "issues": []}

    def fix_verified_issues(
        self,
        completed_chapters,
        verification_report,
        review_comment,
        story_plan,
        spec,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return completed_chapters


class GraphChapterPairLoopTests(unittest.TestCase):
    def test_five_chapters_must_finish_all_pairs_before_verification(self) -> None:
        engine = FakeEngine()
        graph = build_graph(
            engine,
            context_manager=FakeContextManager(),
        )
        config = {"configurable": {"thread_id": "task-five-chapters"}}
        initial_state = {
            "task_id": "task-five-chapters",
            "input_payload": {
                "mode": "short_story",
                "prompt": "写一个五章恐怖故事",
                "genre": "恐怖",
                "style": "冷静克制",
                "target_words": 1800,
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
        engine = FakeEngine()
        graph = build_graph(
            engine,
            context_manager=FakeContextManager(),
        )
        config = {"configurable": {"thread_id": "task-style-remix-batches"}}
        initial_state = {
            "task_id": "task-style-remix-batches",
            "input_payload": {
                "mode": "style_remix",
                "prompt": "写一个五章学院流玄幻故事",
                "genre": "玄幻",
                "style": "热血成长",
                "style_profile_id": "douluodalu",
                "target_words": 2600,
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

        final_result = graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertNotIn("__interrupt__", final_result)
        self.assertEqual(engine.generated_batch_indexes, [0, 2, 3, 4])
        self.assertEqual(engine.generated_batch_sizes, [2, 1, 1, 1])


if __name__ == "__main__":
    unittest.main()
