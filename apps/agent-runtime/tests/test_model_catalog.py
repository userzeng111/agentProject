import tempfile
import unittest
from pathlib import Path

from app.settings.config import Settings


class FakeGatewayClient:
    def __init__(self, models):
        self._models = models

    def list_models(self):
        return self._models


class ModelCatalogServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.llm.model_catalog import ModelCatalogService

        self.tmp_dir = tempfile.TemporaryDirectory()
        self.settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="gpt-5.4",
            tasklog_root=str(Path(self.tmp_dir.name) / "tasklog"),
        )
        self.catalog_cls = ModelCatalogService

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_list_models_merges_gateway_models_with_capability_profiles(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "gpt-5.4", "object": "model", "owned_by": "openai"},
                    {"id": "gpt-4.1-mini", "object": "model", "owned_by": "openai"},
                ]
            ),
        )

        payload = catalog.list_models_payload()

        self.assertEqual(payload["meta"]["default_model"], "gpt-5.4")
        self.assertEqual(payload["meta"]["capability_schema_version"], "v1")

        data = payload["data"]
        self.assertEqual([item["id"] for item in data[:2]], ["gpt-5.4", "gpt-4.1-mini"])

        gpt54 = next(item for item in data if item["id"] == "gpt-5.4")
        self.assertEqual(gpt54["provider"], "openai_compatible")
        self.assertEqual(gpt54["capabilities"]["context_window"]["max_input_tokens"], 256000)
        self.assertTrue(gpt54["capabilities"]["cache"]["runtime_context_cache"])
        self.assertEqual(gpt54["metadata"]["source"], "gateway+registry")

    def test_default_model_is_injected_when_gateway_does_not_return_it(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "gpt-4.1-mini", "object": "model", "owned_by": "openai"},
                ]
            ),
        )

        payload = catalog.list_models_payload()

        self.assertEqual(payload["data"][0]["id"], "gpt-5.4")
        self.assertIn(payload["data"][0]["metadata"]["source"], {"default+registry", "registry"})

    def test_current_gateway_model_families_all_get_context_window_profiles(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "MiniMax-M2.7-highspeed"},
                    {"id": "gpt-5.2-codex"},
                    {"id": "glm-5"},
                    {"id": "claude-haiku-4-5-20251001"},
                    {"id": "gpt-5.4"},
                    {"id": "glm-5.1"},
                    {"id": "claude-sonnet-4-6"},
                    {"id": "gpt-5.3-codex"},
                    {"id": "claude-opus-4-6"},
                    {"id": "gpt-5.1-codex-mini"},
                    {"id": "gpt-5.1-codex-max"},
                ]
            ),
        )

        payload = catalog.list_models_payload()

        gateway_ids = {
            "MiniMax-M2.7-highspeed",
            "gpt-5.2-codex",
            "glm-5",
            "claude-haiku-4-5-20251001",
            "gpt-5.4",
            "glm-5.1",
            "claude-sonnet-4-6",
            "gpt-5.3-codex",
            "claude-opus-4-6",
            "gpt-5.1-codex-mini",
            "gpt-5.1-codex-max",
        }
        for item in payload["data"]:
            if item["id"] not in gateway_ids:
                continue
            context_window = item["capabilities"]["context_window"]
            self.assertIsInstance(context_window["max_input_tokens"], int)
            self.assertGreater(context_window["max_input_tokens"], 0)

    def test_unknown_gateway_model_is_marked_unverified_for_novel_workflow(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "K2.6", "object": "model", "owned_by": "custom"},
                ]
            ),
        )

        payload = catalog.list_models_payload()
        model = next(item for item in payload["data"] if item["id"] == "K2.6")

        self.assertEqual(model["metadata"]["source"], "gateway")
        self.assertEqual(model["metadata"]["compatibility"], "unverified")
        self.assertFalse(model["capabilities"]["features"]["novel_task_supported"])


if __name__ == "__main__":
    unittest.main()
