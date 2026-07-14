import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.domain.models import (
    AgentRunRecord,
    ContinueDraftRequest,
    RecoveryPreview,
    RecoveryRequest,
    ResumeRequest,
    TaskActionRequest,
    TaskCreateRequest,
    TaskMode,
    TaskStatus,
    TaskSummary,
)
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

    def test_store_migrates_legacy_default_model_field_in_core_tasklog_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_dir = Path(tmp_dir) / "tasklog"
            task_id = "task_legacy_model001"
            task_dir = root_dir / "runs" / task_id
            state_dir = task_dir / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            legacy_task = {
                "id": task_id,
                "mode": "short_story",
                "default_model_id": "retired-text-model",
                "input": {
                    "prompt": "旧任务模型字段迁移",
                    "genre": "",
                    "style": "",
                    "target_words": 1800,
                    "audience": "",
                    "banned": "",
                    "title_hint": "",
                },
            }
            legacy_meta = {
                "task_id": task_id,
                "default_model_id": "retired-text-model",
            }
            legacy_request = {
                "task_id": task_id,
                "default_model_id": "retired-text-model",
                "input": legacy_task["input"],
            }
            for path, payload in (
                (task_dir / "task.json", legacy_task),
                (state_dir / "task.json", legacy_task),
                (task_dir / "meta.json", legacy_meta),
                (task_dir / "request.json", legacy_request),
            ):
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            reloaded_store = TaskLogStore(root_dir=str(root_dir))

            self.assertEqual(reloaded_store.get(task_id).model_id, "retired-text-model")
            task_payload = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
            state_payload = json.loads((state_dir / "task.json").read_text(encoding="utf-8"))
            meta_payload = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
            request_payload = json.loads((task_dir / "request.json").read_text(encoding="utf-8"))
            for payload in (task_payload, state_payload, meta_payload, request_payload):
                self.assertNotIn("default_model_id", payload)
                self.assertEqual(payload["model_id"], "retired-text-model")
            self.assertEqual(meta_payload["creative_model_id"], "retired-text-model")
            self.assertEqual(request_payload["creative_model_id"], "retired-text-model")

    def test_display_dtos_accept_legacy_default_model_id_without_serializing_it(self) -> None:
        recovery_preview = RecoveryPreview.model_validate({"default_model_id": "legacy-model"})
        summary = TaskSummary.model_validate(
            {
                "task_id": "task_legacy_model002",
                "title": "旧任务",
                "mode": TaskMode.SHORT_STORY,
                "model_id": "legacy-model",
                "default_model_id": "legacy-model",
                "status": TaskStatus.CREATED,
                "current_stage": "created",
                "progress": 0,
                "updated_at": datetime.now(timezone.utc),
                "summary": "",
                "storage_state": "runs",
            }
        )

        self.assertEqual(recovery_preview.creative_model_id, "legacy-model")
        self.assertNotIn("default_model_id", recovery_preview.model_dump())
        self.assertEqual(summary.creative_model_id, "legacy-model")
        self.assertNotIn("default_model_id", summary.model_dump())

    def test_action_request_dtos_accept_legacy_default_model_id_without_serializing_it(self) -> None:
        create_request = TaskCreateRequest.model_validate(
            {
                "mode": TaskMode.SHORT_STORY,
                "prompt": "兼容旧动作请求模型字段",
                "default_model_id": "legacy-model",
            }
        )
        requests = [
            create_request,
            ResumeRequest.model_validate({"approved": True, "default_model_id": "legacy-model"}),
            ContinueDraftRequest.model_validate(
                {
                    "requested_chapter_count": 2,
                    "continue_request_id": "continue_legacy_model",
                    "default_model_id": "legacy-model",
                }
            ),
            TaskActionRequest.model_validate({"default_model_id": "legacy-model"}),
            RecoveryRequest.model_validate({"default_model_id": "legacy-model"}),
        ]

        for request in requests:
            self.assertEqual(request.model_id, "legacy-model")
            self.assertNotIn("default_model_id", request.model_dump())


if __name__ == "__main__":
    unittest.main()
