import tempfile
import unittest
from pathlib import Path

from app.domain.models import TaskCreateRequest, TaskMode
from app.storage.task_store import TaskLogStore


class TaskStoreContextTests(unittest.TestCase):
    def test_write_context_snapshot_persists_json_under_stage_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            task = store.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一个潮湿港口的悬疑短篇",
                    model_id="gpt-5.4",
                )
            )

            relative_path = store.write_context_snapshot(
                task.id,
                stage="planning",
                snapshot_name="outline-context",
                payload={"stage": "planning", "summary": "已压缩参考素材"},
            )

            self.assertEqual(relative_path, "context/planning/outline-context.json")
            snapshot = store.read_json(task.id, relative_path)
            self.assertEqual(snapshot["summary"], "已压缩参考素材")

    def test_write_message_history_persists_messages_under_stage_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            task = store.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="写一个潮湿港口的悬疑短篇",
                    model_id="gpt-5.4",
                )
            )

            relative_path = store.write_message_history(
                task.id,
                stage="drafting",
                history=[
                    {"role": "user", "content": "q1"},
                    {"role": "assistant", "content": "a1"},
                    {"role": "user", "content": "q2"},
                ],
                filename="chapter-02-history",
            )

            self.assertEqual(relative_path, "context/drafting/chapter-02-history.json")
            payload = store.read_json(task.id, relative_path)
            self.assertEqual(len(payload["messages"]), 3)
            self.assertEqual(payload["messages"][1]["content"], "a1")


if __name__ == "__main__":
    unittest.main()
