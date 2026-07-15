import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from app.domain.models import TaskCreateRequest, TaskMode
from app.storage.database import init_db
from app.storage.task_store import TaskLogStore


class FailingQueue(asyncio.Queue[dict[str, Any]]):
    def put_nowait(self, item: dict[str, Any]) -> None:
        raise RuntimeError("订阅连接已关闭")


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

    def test_read_text_rejects_cross_task_tasklog_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            first = store.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="第一个任务",
                    model_id="gpt-5.4",
                )
            )
            second = store.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="第二个任务",
                    model_id="gpt-5.4",
                )
            )

            with self.assertRaises(FileNotFoundError):
                store.read_text(second.id, f"tasklog/runs/{first.id}/request.md")

    def test_broadcast_event_warns_and_removes_subscriber_when_queue_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            init_db(str(Path(tmp_dir) / "data.db"))
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            task = store.create_task(
                TaskCreateRequest(
                    mode=TaskMode.SHORT_STORY,
                    prompt="广播失败日志覆盖",
                    model_id="gpt-5.4",
                )
            )
            failing_queue = FailingQueue()
            store._subscribers.setdefault(task.id, []).append(failing_queue)

            with self.assertLogs("app.storage.task_store", level="WARNING") as logs:
                store.broadcast_event(
                    task.id,
                    stage="unit",
                    message="实时事件",
                    event_type="unit.event",
                )

            self.assertNotIn(task.id, store._subscribers)
            output = "\n".join(logs.output)
            self.assertIn("任务事件广播失败", output)
            self.assertIn(task.id, output)
            self.assertIn("unit.event", output)

    def test_background_thread_delivery_wakes_event_stream_loop(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as tmp_dir:
                store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
                task = store.create_task(
                    TaskCreateRequest(
                        mode=TaskMode.SHORT_STORY,
                        prompt="后台线程事件投递",
                        model_id="gpt-5.4",
                    )
                )
                queue = store.subscribe(task.id)
                worker = threading.Thread(
                    target=lambda: store.broadcast_event(
                        task.id,
                        stage="planning",
                        message="后台节点已开始。",
                        event_type="workflow.node.started",
                    ),
                )
                worker.start()
                event = await asyncio.wait_for(queue.get(), timeout=1)
                worker.join(timeout=1)
                store.unsubscribe(task.id, queue)

                self.assertEqual(event["event_type"], "workflow.node.started")
                self.assertEqual(event["message"], "后台节点已开始。")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
