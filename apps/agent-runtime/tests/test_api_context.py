import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import build_router
from app.application.task_service import TaskService
from app.domain.models import CreativeMode, DraftResult, NovelSize, ReviewPayload, StoryPlan, TaskCreateRequest, TaskMode
from app.llm.model_catalog import ModelCatalogService
from app.llm.gateway_client import StreamChunk
from app.llm.story_engine import StoryEngine
from app.rag.service import RagHit
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore
from tests.fakes import FakeRagService


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

    def test_create_task_returns_400_for_unverified_novel_model(self) -> None:
        response = self.client.post(
            "/api/tasks",
            json={
                "prompt": "写一个修罗场都市医生故事",
                "creative_mode": "style_remix",
                "novel_size": "long",
                "chapter_word_min": 2200,
                "genre": "都市",
                "style": "保留原文风格，但有新东西",
                "style_profile_id": "wozhenmeixiangchongshengya",
                "title_hint": "文艺",
                "model_id": "K2.6",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("未完成兼容性验证", response.json()["detail"])

    def test_workspace_endpoint_returns_context_status(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                prompt="写一篇港口悬疑小说",
                creative_mode=CreativeMode.ORIGINAL,
                novel_size=NovelSize.SHORT,
                chapter_word_min=1800,
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
        self.assertEqual(payload["meta"]["creative_mode"], "original")
        self.assertEqual(payload["meta"]["novel_size"], "short")
        self.assertEqual(payload["meta"]["chapter_word_min"], 1800)
        self.assertEqual(payload["context_status"]["stage"], "planning")
        self.assertTrue(payload["context_status"]["cache_hit"])
        self.assertTrue(payload["context_status"]["compression_applied"])
        self.assertEqual(payload["context_status"]["cache_scope"], "runtime_context")
        self.assertEqual(payload["response_cache_status"], {})
        self.assertIn("supervisor_plan", payload)
        self.assertEqual(payload["supervisor_plan"]["planner_version"], "v1")
        self.assertEqual(payload["supervisor_plan"]["subtasks"][0]["kind"], "reference_analysis")

    def test_workspace_endpoint_returns_default_and_last_action_model_fields(self) -> None:
        self.task_service.model_catalog.ensure_novel_generation_model_supported = lambda _model_id: None
        self.task_service._start_background = lambda *args, **kwargs: None

        task = self.task_service.create_task(
            TaskCreateRequest(
                prompt="写一篇港口悬疑小说",
                creative_mode=CreativeMode.ORIGINAL,
                novel_size=NovelSize.SHORT,
                chapter_word_min=1800,
                model_id="gpt-5.4",
            )
        )
        self.task_service.run_task(task.id, model_id="glm-5.1")

        response = self.client.get(f"/api/tasks/{task.id}/workspace")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["model_id"], "gpt-5.4")
        self.assertEqual(payload["meta"]["default_model_id"], "gpt-5.4")
        self.assertEqual(payload["meta"]["last_action_model_id"], "glm-5.1")
        self.assertEqual(payload["meta"]["last_action_kind"], "run")
        self.assertEqual(payload["request_preview"]["default_model_id"], "gpt-5.4")
        self.assertEqual(payload["request_preview"]["last_action_model_id"], "glm-5.1")
        self.assertEqual(payload["allowed_actions"], [])
        self.assertEqual(payload["recommended_action"], "")
        self.assertEqual(payload["blocked_reason"], "")
        self.assertFalse(payload["state_reconciled"])
        self.assertEqual(payload["reconciliation_kind"], "")
        self.assertEqual(payload["reconciliation_summary"], "")
        self.assertEqual(len(payload["recovery_options"]), 2)
        self.assertFalse(payload["recovery_options"][0]["available"])
        self.assertFalse(payload["recovery_options"][1]["available"])

    def test_workspace_endpoint_returns_novel_progress_for_ready_batch_task(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                prompt="写一篇都市医生长篇",
                creative_mode=CreativeMode.ORIGINAL,
                novel_size=NovelSize.LONG,
                target_chapter_count=100,
                chapter_word_min=1800,
                model_id="gpt-5.4",
            )
        )
        story_plan = StoryPlan(
            working_title="白衣修罗场",
            logline="年轻医生在都市修罗场中崛起。",
            world_notes=["现代都市医院体系"],
            character_notes=["男主是年轻医生"],
            planned_chapter_count=96,
            chapter_plan=[
                {"number": 1, "title": "第一章", "goal": "入院风波"},
                {"number": 2, "title": "第二章", "goal": "夜班急诊"},
            ],
        )
        self.store.set_ready_for_batch(task.id, story_plan)

        response = self.client.get(f"/api/tasks/{task.id}/workspace")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["novel_progress"]["target_chapter_count"], 100)
        self.assertEqual(payload["novel_progress"]["planned_chapter_count"], 96)
        self.assertEqual(payload["novel_progress"]["next_chapter_number"], 1)
        self.assertEqual(payload["novel_progress"]["default_batch_size"], 3)

    def test_supervisor_endpoint_returns_supervisor_plan_and_agent_runs(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                prompt="写一篇港口悬疑小说",
                creative_mode=CreativeMode.ORIGINAL,
                novel_size=NovelSize.SHORT,
                chapter_word_min=1800,
                model_id="gpt-5.4",
            )
        )

        response = self.client.get(f"/api/tasks/{task.id}/supervisor")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["planner_version"], "v1")
        self.assertEqual(len(payload["subtasks"]), 6)
        self.assertEqual(payload["agent_runs"], [])

    def test_create_task_response_exposes_new_input_fields(self) -> None:
        response = self.client.post(
            "/api/tasks",
            json={
                "prompt": "写一个都市医生修罗场故事",
                "creative_mode": "style_remix",
                "novel_size": "long",
                "chapter_word_min": 2600,
                "style_profile_id": "wozhenmeixiangchongshengya",
                "model_id": "gpt-5.4",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["creative_mode"], "style_remix")
        self.assertEqual(payload["novel_size"], "long")
        self.assertEqual(payload["chapter_word_min"], 2600)
        self.assertEqual(payload["mode"], "style_remix")

    def test_create_task_response_exposes_target_chapter_count_and_range(self) -> None:
        response = self.client.post(
            "/api/tasks",
            json={
                "prompt": "写一个长篇都市医生修罗场故事",
                "creative_mode": "original",
                "novel_size": "long",
                "target_chapter_count": 100,
                "chapter_word_min": 2400,
                "model_id": "gpt-5.4",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["input"]["target_chapter_count"], 100)
        self.assertEqual(payload["target_chapter_count"], 100)
        self.assertEqual(payload["chapter_count_min"], 90)
        self.assertEqual(payload["chapter_count_max"], 110)

    def test_workspace_endpoint_returns_response_cache_status_separately(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                prompt="写一篇港口悬疑小说",
                creative_mode=CreativeMode.ORIGINAL,
                novel_size=NovelSize.SHORT,
                chapter_word_min=1800,
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
                prompt="写一篇港口悬疑小说",
                creative_mode=CreativeMode.ORIGINAL,
                novel_size=NovelSize.SHORT,
                chapter_word_min=1800,
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

    def test_continue_endpoint_generates_chapter_batch(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                prompt="写一篇都市医生长篇",
                creative_mode=CreativeMode.ORIGINAL,
                novel_size=NovelSize.LONG,
                target_chapter_count=100,
                chapter_word_min=1800,
                model_id="gpt-5.4",
            )
        )
        task = self.store.get(task.id)
        task.normalized_spec = {
            "mode": "long_story",
            "creative_mode": "original",
            "novel_size": "long",
            "prompt": "写一篇都市医生长篇",
            "genre": "都市",
            "style": "",
            "chapter_word_min": 1800,
            "chapter_word_max": 2340,
            "model_id": "gpt-5.4",
        }
        self.store.save(task)
        story_plan = StoryPlan(
            working_title="白衣修罗场",
            logline="年轻医生在都市修罗场中崛起。",
            world_notes=["现代都市医院体系"],
            character_notes=["男主是年轻医生"],
            planned_chapter_count=3,
            chapter_plan=[
                {"number": 1, "title": "第一章", "goal": "入院风波"},
                {"number": 2, "title": "第二章", "goal": "夜班急诊"},
                {"number": 3, "title": "第三章", "goal": "权贵病人"},
            ],
        )
        self.store.set_ready_for_batch(task.id, story_plan)
        self.task_service.engine.generate_chapter_pair = lambda **kwargs: [
            {
                "number": 1,
                "title": "第一章",
                "summary": "第一章摘要",
                "content": "第一章正文",
            },
            {
                "number": 2,
                "title": "第二章",
                "summary": "第二章摘要",
                "content": "第二章正文",
            },
        ]

        response = self.client.post(
            f"/api/tasks/{task.id}/continue",
            json={"requested_chapter_count": 2, "continue_request_id": "req-1"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "waiting_chapter_review")

    def test_recover_endpoint_restores_outline_review_from_history(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇港口悬疑小说",
                model_id="gpt-5.4",
            )
        )
        broken = self.store.get(task.id)
        broken.status = broken.status.PLANNING
        broken.current_stage = "planning"
        broken.current_unit = "outline-revision"
        broken.story_plan = None
        broken.pending_review = None
        self.store.save(broken)
        self.store.write_message_history(
            task.id,
            stage="planning",
            history=[
                {"role": "system", "content": "s"},
                {"role": "user", "content": "u"},
                {
                    "role": "assistant",
                    "content": __import__("json").dumps(
                        {
                            "working_title": "恢复标题",
                            "logline": "恢复梗概",
                            "world_notes": ["港口"],
                            "character_notes": ["档案员"],
                            "chapter_plan": [{"number": 1, "title": "起始", "goal": "发现异常"}],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            filename="outline-revision-history",
        )

        response = self.client.post(f"/api/tasks/{task.id}/recover")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "waiting_outline_review")
        self.assertEqual(payload["current_stage"], "waiting_outline_review")

    def test_recover_endpoint_forwards_action_model_override(self) -> None:
        task = self.task_service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一篇港口悬疑小说",
                model_id="gpt-5.4",
            )
        )
        broken = self.store.get(task.id)
        broken.status = broken.status.WAITING_MANUAL_ACTION
        broken.current_stage = "waiting_manual_action"
        broken.normalized_spec = {
            "mode": "short_story",
            "creative_mode": "original",
            "novel_size": "short",
            "prompt": "写一篇港口悬疑小说",
            "model_id": "gpt-5.4",
        }
        self.store.save(broken)

        captured: dict[str, object] = {}

        def fake_recover(
            task_id: str,
            force: bool = False,
            model_id: str | None = None,
            recovery_mode: str = "recover_to_stable",
        ):
            captured["task_id"] = task_id
            captured["force"] = force
            captured["model_id"] = model_id
            captured["recovery_mode"] = recovery_mode
            return self.store.get(task_id)

        self.task_service.recover_task = fake_recover  # type: ignore[assignment]

        response = self.client.post(
            f"/api/tasks/{task.id}/recover",
            json={"model_id": "gpt-5.4", "recovery_mode": "restart_from_input"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["task_id"], task.id)
        self.assertEqual(captured["force"], True)
        self.assertEqual(captured["model_id"], "gpt-5.4")
        self.assertEqual(captured["recovery_mode"], "restart_from_input")

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

    def test_chat_completions_injects_rag_context_before_gateway_call(self) -> None:
        class FakeStreamGateway:
            def __init__(self) -> None:
                self.calls = []

            async def complete_stream(self, messages, model=None):
                self.calls.append({"messages": [dict(item) for item in messages], "model": model})
                yield StreamChunk(content="这是回答")

        class FakeEngine:
            def __init__(self) -> None:
                self.gateway_client = FakeStreamGateway()

            def resolve_model(self, model):
                return model or "gpt-5.4"

        fake_rag = FakeRagService(
            hits=[
                RagHit(
                    doc_id="rag-chat-1",
                    content="港口档案记载夜航记录曾被改写。",
                    score=0.95,
                    metadata={},
                )
            ],
            selected_contexts=["港口档案记载夜航记录曾被改写。"],
        )

        from app.services import ChatService

        app = FastAPI()
        fake_engine = FakeEngine()
        chat_service = ChatService(
            gateway_client=fake_engine.gateway_client,
            rag_service=fake_rag,
        )
        app.include_router(build_router(self.task_service, chat_service=chat_service, rag_service=fake_rag), prefix="/api")
        client = TestClient(app)

        response = client.post(
            "/api/chat/completions",
            json={
                "messages": [{"role": "user", "content": "夜航记录怎么回事"}],
                "model": "gpt-5.4",
                "stream": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        call_messages = fake_engine.gateway_client.calls[0]["messages"]
        self.assertEqual(call_messages[0]["role"], "system")
        self.assertIn("港口档案", call_messages[0]["content"])

    def test_chat_completions_uses_updated_runtime_default_model_when_request_model_missing(self) -> None:
        class FakeGateway:
            def __init__(self) -> None:
                self.calls = []

            def list_models(self):
                return [
                    {"id": "gpt-5.4", "object": "model", "owned_by": "custom"},
                    {"id": "glm-5.1", "object": "model", "owned_by": "custom"},
                ]

            async def complete_stream(self, messages, model=None):
                self.calls.append({"messages": [dict(item) for item in messages], "model": model})
                yield StreamChunk(content="这是回答")

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                LLM_API_KEY="",
                DEFAULT_CHAT_MODEL="gpt-5.4",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            engine.gateway_client = FakeGateway()
            model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
            task_service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            from app.services import ChatService

            app = FastAPI()
            chat_service = ChatService(
                gateway_client=engine.gateway_client,
                rag_service=None,
                default_model_resolver=lambda: engine.resolve_model(None),
            )
            app.include_router(build_router(task_service, chat_service=chat_service), prefix="/api")
            client = TestClient(app)

            update_response = client.patch("/api/settings/default-model", json={"model_id": "glm-5.1"})
            self.assertEqual(update_response.status_code, 200)

            response = client.post(
                "/api/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "现在用默认模型回答"}],
                    "stream": False,
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(engine.gateway_client.calls[0]["model"], "glm-5.1")
            self.assertEqual(response.json()["model"], "glm-5.1")


if __name__ == "__main__":
    unittest.main()
