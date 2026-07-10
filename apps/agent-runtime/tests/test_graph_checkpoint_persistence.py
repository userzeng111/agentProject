import tempfile
import unittest
from pathlib import Path

from app.context.manager import ContextManager
from app.domain.models import ChapterPlan, StoryPlan
from app.graph.main_graph import build_graph
from tests.fakes import FakeVerifiedGatewayModelCatalog


class FakeEngine:
    def __init__(self) -> None:
        self.gateway_client = None

    def build_story_plan(self, spec, reference_text, context_packet=None, model=None):
        return StoryPlan(
            working_title="持久化测试标题",
            logline="持久化测试梗概",
            world_notes=["世界观"],
            character_notes=["人物"],
            chapter_plan=[ChapterPlan(number=1, title="第一章", goal="建立冲突")],
        )


class GraphCheckpointPersistenceTests(unittest.TestCase):
    def test_checkpoint_db_path_must_survive_across_graph_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            checkpoint_db_path = Path(tmp_dir) / "checkpoints.db"
            config = {"configurable": {"thread_id": "task-checkpoint-persistence"}}
            initial_state = {
                "task_id": "task-checkpoint-persistence",
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

            first_graph = build_graph(
                FakeEngine(),
                context_manager=ContextManager(),
                model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
                checkpoint_db_path=checkpoint_db_path,
            )

            first_result = first_graph.invoke(initial_state, config=config)
            self.assertIn("__interrupt__", first_result)
            self.assertTrue(checkpoint_db_path.exists())

            second_graph = build_graph(
                FakeEngine(),
                context_manager=ContextManager(),
                model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
                checkpoint_db_path=checkpoint_db_path,
            )
            restored_values = second_graph.get_state(config).values

            self.assertIn("story_plan", restored_values)
            self.assertEqual(restored_values["story_plan"]["working_title"], "持久化测试标题")


if __name__ == "__main__":
    unittest.main()
