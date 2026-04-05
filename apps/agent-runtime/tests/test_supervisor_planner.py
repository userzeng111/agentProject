import unittest

from app.domain.models import TaskCreateRequest, TaskMode
from app.graph.supervisor_graph import build_initial_supervisor_plan


class SupervisorPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = TaskCreateRequest(
            mode=TaskMode.SHORT_STORY,
            prompt="写一个潮湿海港中的冷峻悬疑短篇",
            genre="悬疑",
            style="冷静克制",
            target_words=1800,
            model_id="gpt-5.4",
        )

    def test_build_initial_supervisor_plan_returns_ordered_story_subtasks(self) -> None:
        plan = build_initial_supervisor_plan(self.payload)

        self.assertEqual(
            [item.kind for item in plan.subtasks],
            [
                "reference_analysis",
                "outline_planning",
                "chapter_writing",
                "chapter_review",
                "full_verification",
                "result_assembly",
            ],
        )

    def test_build_initial_supervisor_plan_sets_only_first_subtask_ready(self) -> None:
        plan = build_initial_supervisor_plan(self.payload)

        self.assertEqual(
            [item.status.value for item in plan.subtasks],
            ["ready", "blocked", "blocked", "blocked", "blocked", "blocked"],
        )

    def test_build_initial_supervisor_plan_builds_unique_ids_and_linear_dependencies(self) -> None:
        plan = build_initial_supervisor_plan(self.payload)

        self.assertEqual(len({item.id for item in plan.subtasks}), len(plan.subtasks))
        self.assertEqual(len(plan.dependencies), len(plan.subtasks) - 1)
        self.assertTrue(all(edge.kind == "finish_to_start" for edge in plan.dependencies))


if __name__ == "__main__":
    unittest.main()
