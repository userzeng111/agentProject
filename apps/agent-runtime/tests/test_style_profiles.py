import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import build_router
from app.application.task_service import TaskService
from app.llm.story_engine import StoryEngine
from app.settings.config import Settings
from app.storage.task_store import TaskLogStore
from app.style_profiles.service import StyleProfileService
from tests.fakes import build_verified_gateway_model_catalog


class StyleProfileServiceTests(unittest.TestCase):
    def test_list_profiles_filters_missing_instance_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "bisheng-style"
            instances_root = root / "instances"
            instances_root.mkdir(parents=True, exist_ok=True)
            (instances_root / "registry.yaml").write_text(
                """
instances:
  - instance_id: good
    name: "可用实例"
    source_novel: "示例小说"
    source_author: "示例作者"
    genre: "玄幻"
    path: "instances/good/"
    status: active
    fidelity_score: 88
    description: "可用"
  - instance_id: broken
    name: "缺失实例"
    source_novel: "缺失小说"
    source_author: "缺失作者"
    genre: "悬疑"
    path: "instances/broken/"
    status: active
    fidelity_score: 30
    description: "缺失"
                """.strip(),
                encoding="utf-8",
            )
            good_root = instances_root / "good" / "rules"
            good_root.mkdir(parents=True, exist_ok=True)
            (instances_root / "good" / "manifest.yaml").write_text("name: good", encoding="utf-8")
            (good_root / "language.md").write_text("# 语言\n短句推进\n", encoding="utf-8")

            service = StyleProfileService(style_root=root)
            profiles = service.list_profiles()

            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0]["id"], "good")

    def test_build_runtime_profile_compiles_rule_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "bisheng-style"
            rules_root = root / "instances" / "douluo" / "rules"
            rules_root.mkdir(parents=True, exist_ok=True)
            (root / "instances" / "registry.yaml").write_text(
                """
instances:
  - instance_id: douluo
    name: "唐家三少风格实例"
    source_novel: "斗罗大陆"
    source_author: "唐家三少"
    genre: "玄幻"
    path: "instances/douluo/"
    status: active
    fidelity_score: 90
    description: "术语流"
                """.strip(),
                encoding="utf-8",
            )
            (root / "instances" / "douluo" / "manifest.yaml").write_text(
                'name: "唐家三少风格实例"\nsource_novel: "斗罗大陆"\nsource_author: "唐家三少"\n',
                encoding="utf-8",
            )
            (rules_root / "language.md").write_text("# 语言\n术语密集\n", encoding="utf-8")
            (rules_root / "plot.md").write_text("# 情节\n力量升级驱动\n", encoding="utf-8")

            service = StyleProfileService(style_root=root)
            profile = service.build_runtime_profile("douluo", "保留少年热血感")

            assert profile is not None
            self.assertEqual(profile["id"], "douluo")
            self.assertIn("唐家三少风格实例", profile["compiled_summary"])
            self.assertIn("补充要求：保留少年热血感", profile["compiled_summary"])

    def test_style_profile_route_returns_available_items(self) -> None:
        class FakeStyleProfileService:
            def list_profiles(self):
                return [{"id": "douluo", "name": "唐家三少风格实例"}]

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                LLM_API_KEY="",
                DEFAULT_CHAT_MODEL="",
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
            store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
            engine = StoryEngine(settings)
            model_catalog = build_verified_gateway_model_catalog(settings, engine.gateway_client)
            task_service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

            app = FastAPI()
            app.include_router(
                build_router(task_service, style_profile_service=FakeStyleProfileService()),
                prefix="/api",
            )
            client = TestClient(app)

            response = client.get("/api/style-profiles")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"][0]["id"], "douluo")

    def test_load_manifest_supports_front_matter_style_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "bisheng-style"
            manifest_path = root / "instances" / "douluo" / "manifest.yaml"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                """
---
instance_id: douluo
name: "唐家三少风格实例"
source_novel: "斗罗大陆"
---
                """.strip(),
                encoding="utf-8",
            )
            service = StyleProfileService(style_root=root)

            manifest = service._load_manifest(manifest_path)

            self.assertEqual(manifest["instance_id"], "douluo")
            self.assertEqual(manifest["name"], "唐家三少风格实例")
