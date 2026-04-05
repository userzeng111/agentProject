import unittest

from app.domain.models import TaskCreateRequest, TaskMode
from app.graph.supervisor_graph import build_supervisor_graph


class SupervisorGraphTests(unittest.TestCase):
    def test_supervisor_graph_invocation_returns_supervisor_plan(self) -> None:
        graph = build_supervisor_graph()
        payload = TaskCreateRequest(
            mode=TaskMode.SHORT_STORY,
            prompt="写一个沿海小城中的悬疑故事",
            genre="悬疑",
            style="克制",
            target_words=1800,
            model_id="gpt-5.4",
        )

        result = graph.invoke(
            {
                "task_id": "task-supervisor-1",
                "input_payload": payload.model_dump(mode="json"),
            }
        )

        self.assertIn("supervisor_plan", result)
        self.assertEqual(result["supervisor_plan"]["planner_version"], "v1")
        self.assertEqual(len(result["supervisor_plan"]["subtasks"]), 6)


if __name__ == "__main__":
    unittest.main()
