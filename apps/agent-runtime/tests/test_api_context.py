import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import build_router
from app.application.task_service import TaskService
from app.domain.models import DraftResult, ReviewPayload, StoryPlan, TaskCreateRequest, TaskMode
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore


class ApiContextIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        settings = Settings(
            LLM_API_KEY="",
            DEFAULT_CHAT_MODEL="gpt-5.4",
            tasklog_root=str(Path(self.tmp_dir.name) / "tasklog"),
        )
        store = TaskLogStore(root_dir=str(Path(self.tmp_dir.name) / "tasklog"))
        engine = StoryEngine(settings)
        model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
        task_service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

        app = FastAPI()
        app.include_router(build_router(task_service), prefix="/api")
        self.client = TestClient(app)
        self.store = store
        self.task_service = task_service

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_models_endpoint_returns_capabilities_payload(self) -> None:
        response = self.client.get("/api/models")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["default_model"], "gpt-5.4")
        self.assertIn("capabilities", payload["data"][0])
        self.assertIn("context_window", payload["data"][0]["capabilities"])

    def test_workspace_endpoint_returns_context_status(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇港口悬疑小说",
                model_id="gpt-5.4",
            )
        )
        self.store.write_context_snapshot(
            task.id,
            stage="planning",
            snapshot_name="outline-context",
            payload={
                "task_id": task.id,
                "stage": "planning",
                "cache_hit": True,
                "cache_key": "context:api-test",
                "budget": {"max_input_tokens": 256000},
                "packet": {"estimated_input_tokens": 4096},
                "compressed_references": [
                    {"was_compressed": True, "original_chars": 6000, "compressed_chars": 2000}
                ],
            },
        )

        response = self.client.get(f"/api/tasks/{task.id}/workspace")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["model_capabilities"]["context_window"]["max_input_tokens"], 256000)
        self.assertEqual(payload["context_status"]["stage"], "planning")
        self.assertTrue(payload["context_status"]["cache_hit"])
        self.assertTrue(payload["context_status"]["compression_applied"])
        self.assertEqual(payload["context_status"]["cache_scope"], "runtime_context")
        self.assertEqual(payload["response_cache_status"], {})

    def test_workspace_endpoint_returns_response_cache_status_separately(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇港口悬疑小说",
                model_id="gpt-5.4",
            )
        )
        self.store.append_event(
            task.id,
            stage="planning",
            message="planning 阶段已命中模型响应缓存：outline",
            event_type="cache.hit",
            unit_id="outline",
            payload={
                "cache_hit": True,
                "cache_key": "response:test",
                "model": "gpt-5.4",
                "history_count": 3,
                "exchange_label": "outline",
            },
        )

        response = self.client.get(f"/api/tasks/{task.id}/workspace")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["context_status"], {})
        self.assertTrue(payload["response_cache_status"]["cache_hit"])
        self.assertEqual(payload["response_cache_status"]["cache_scope"], "response_cache")
        self.assertEqual(payload["response_cache_status"]["history_count"], 3)

    def test_review_endpoint_returns_outline_revision_count(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇港口悬疑小说",
                model_id="gpt-5.4",
            )
        )
        story_plan = StoryPlan(
            working_title="港口谜案",
            logline="档案员调查夜航失踪案。",
            world_notes=["潮湿港口"],
            character_notes=["女档案员"],
            chapter_plan=[{"number": 1, "title": "起始", "goal": "发现异常"}],
        )
        review = ReviewPayload(
            type="outline_review",
            version="v1",
            summary="请审核大纲。",
            story_plan=story_plan,
            revision_count=2,
        )
        self.store.set_waiting_review(task.id, review, story_plan)

        response = self.client.get(f"/api/tasks/{task.id}/review")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["review_type"], "outline_review")
        self.assertEqual(payload["revision_count"], 2)

    def test_result_and_archive_endpoints_expose_json_refs_and_sources(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇港口悬疑小说",
                model_id="gpt-5.4",
            )
        )
        self.task_service.add_source(task.id, "notes.txt", "text/plain", "港口资料")
        story_plan = StoryPlan(
            working_title="港口谜案",
            logline="档案员调查夜航失踪案。",
            world_notes=["潮湿港口"],
            character_notes=["女档案员"],
            chapter_plan=[{"number": 1, "title": "起始", "goal": "发现异常"}],
        )
        draft_result = DraftResult(
            title="港口谜案",
            summary="调查开始。",
            body="正文内容",
            chapters=[{"number": 1, "title": "起始", "summary": "发现异常", "content": "章节正文"}],
        )
        artifacts = self.task_service._build_artifacts(story_plan, draft_result)
        self.store.set_completed(task.id, story_plan, draft_result, artifacts)

        result_response = self.client.get(f"/api/tasks/{task.id}/result")
        archive_list_response = self.client.get("/api/archive")
        archive_detail_response = self.client.get(f"/api/archive/{task.id}")

        self.assertEqual(result_response.status_code, 200)
        self.assertEqual(archive_list_response.status_code, 200)
        self.assertEqual(archive_detail_response.status_code, 200)

        result_payload = result_response.json()
        archive_list_payload = archive_list_response.json()
        archive_detail_payload = archive_detail_response.json()

        self.assertTrue(any(item.get("json_ref") for item in result_payload["artifact_index"]))
        self.assertIn("entry_refs", archive_list_payload["items"][0])
        self.assertEqual(len(archive_detail_payload["sources"]), 1)


if __name__ == "__main__":
    unittest.main()
