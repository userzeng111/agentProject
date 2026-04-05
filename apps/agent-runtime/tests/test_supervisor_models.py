import unittest

from app.domain.models import TaskCreateRequest, TaskMode, TaskRecord


class SupervisorModelTests(unittest.TestCase):
    def test_task_record_defaults_supervisor_plan_to_none(self) -> None:
        task = TaskRecord(
            mode=TaskMode.SHORT_STORY,
            model_id="gpt-5.4",
            input=TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一个关于雨夜码头的悬疑故事",
                model_id="gpt-5.4",
            ),
        )

        self.assertIsNone(task.supervisor_plan)
        self.assertEqual(task.agent_runs, [])

    def test_task_record_accepts_legacy_snapshot_without_supervisor_fields(self) -> None:
        task = TaskRecord.model_validate(
            {
                "id": "task_legacy001",
                "mode": "short_story",
                "model_id": "gpt-5.4",
                "input": {
                    "prompt": "旧任务",
                    "genre": "",
                    "style": "",
                    "target_words": 1800,
                    "audience": "",
                    "banned": "",
                    "title_hint": "",
                },
            }
        )

        self.assertIsNone(task.supervisor_plan)
        self.assertEqual(task.agent_runs, [])


if __name__ == "__main__":
    unittest.main()
