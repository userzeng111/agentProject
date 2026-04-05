import json
import tempfile
import unittest
from pathlib import Path

from app.domain.models import AgentRunRecord, TaskCreateRequest, TaskMode
from app.graph.supervisor_graph import build_initial_supervisor_plan
from app.storage.task_store import TaskLogStore


class TaskStoreSupervisorTests(unittest.TestCase):
    def test_store_persists_supervisor_plan_and_agent_runs_across_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_dir = Path(tmp_dir) / "tasklog"
            store = TaskLogStore(root_dir=str(root_dir))
            payload = TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一个旧城密档悬疑故事",
                model_id="gpt-5.4",
            )
            task = store.create_task(payload)
            task.supervisor_plan = build_initial_supervisor_plan(payload)
            store.save(task)
            store.append_agent_run(
                task.id,
                AgentRunRecord(
                    subtask_id=task.supervisor_plan.subtasks[0].id,
                    agent_name="planner_agent",
                    role="planner",
                ),
            )

            reloaded_store = TaskLogStore(root_dir=str(root_dir))
            reloaded_task = reloaded_store.get(task.id)

            self.assertIsNotNone(reloaded_task.supervisor_plan)
            self.assertEqual(len(reloaded_task.agent_runs), 1)

    def test_store_loads_legacy_task_snapshot_without_supervisor_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_dir = Path(tmp_dir) / "tasklog"
            task_id = "task_legacy001"
            snapshot_dir = root_dir / "runs" / task_id / "state"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (root_dir / "archive").mkdir(parents=True, exist_ok=True)
            (root_dir / "specs").mkdir(parents=True, exist_ok=True)
            snapshot_dir.joinpath("task.json").write_text(
                json.dumps(
                    {
                        "id": task_id,
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
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            reloaded_store = TaskLogStore(root_dir=str(root_dir))
            task = reloaded_store.get(task_id)

            self.assertIsNone(task.supervisor_plan)
            self.assertEqual(task.agent_runs, [])


if __name__ == "__main__":
    unittest.main()
