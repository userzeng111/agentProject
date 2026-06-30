import json
import logging
import tempfile
import unittest
from pathlib import Path

from app.llm.model_compatibility import ModelCompatibilityService
from app.llm.model_catalog import ModelCatalogService
from app.settings.config import Settings


class FakeGatewayClient:
    def __init__(self, models):
        self._models = models

    def list_models(self):
        return self._models


class FailingGatewayClient:
    def list_models(self):
        raise RuntimeError("gateway down")


class FakeCompatibilityProvider:
    def __init__(self, reports):
        self.reports = reports

    def get_report(self, model_id):
        return self.reports.get(model_id, {"model_id": model_id, "status": "unverified", "summary": "尚未验证"})


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
                    {"id": "mimo-v2.5-pro"},
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
            "mimo-v2.5-pro",
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

    def test_mimo_v25_pro_is_verified_openai_model_for_novel_workflow(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "mimo-v2.5-pro", "object": "model", "owned_by": "mimo"},
                ]
            ),
        )

        profile = catalog.ensure_novel_generation_model_supported("mimo-v2.5-pro")

        self.assertEqual(profile["metadata"]["source"], "gateway+registry")
        self.assertEqual(profile["metadata"]["compatibility"], "verified")
        self.assertEqual(profile["metadata"]["protocol"], "openai")
        self.assertTrue(profile["capabilities"]["features"]["novel_task_supported"])

    def test_missing_runtime_default_is_persisted_from_verified_env_default(self) -> None:
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="mimo-v2.5-pro",
            tasklog_root=str(Path(self.tmp_dir.name) / "tasklog"),
        )
        catalog = self.catalog_cls(
            settings=settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "mimo-v2.5-pro", "object": "model", "owned_by": "mimo"},
                ]
            ),
        )

        payload = catalog.list_models_payload(force_refresh=True)

        self.assertEqual(payload["meta"]["default_model"], "mimo-v2.5-pro")
        settings_file = Path(settings.tasklog_root) / "settings.json"
        self.assertEqual(settings_file.read_text(encoding="utf-8").strip(), '{\n  "default_model": "mimo-v2.5-pro"\n}')

    def test_unavailable_runtime_default_is_replaced_by_verified_env_default_after_refresh(self) -> None:
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="mimo-v2.5-pro",
            tasklog_root=str(Path(self.tmp_dir.name) / "tasklog"),
        )
        settings_file = Path(settings.tasklog_root) / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text('{\n  "default_model": "old-model"\n}\n', encoding="utf-8")
        catalog = self.catalog_cls(
            settings=settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "mimo-v2.5-pro", "object": "model", "owned_by": "mimo"},
                ]
            ),
        )

        payload = catalog.list_models_payload(force_refresh=True)

        self.assertEqual(payload["meta"]["default_model"], "mimo-v2.5-pro")
        self.assertEqual(catalog._effective_default_model(), "mimo-v2.5-pro")
        self.assertIn('"default_model": "mimo-v2.5-pro"', settings_file.read_text(encoding="utf-8"))

    def test_unverified_runtime_default_is_replaced_by_verified_env_default_after_refresh(self) -> None:
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="mimo-v2.5-pro",
            tasklog_root=str(Path(self.tmp_dir.name) / "tasklog"),
        )
        settings_file = Path(settings.tasklog_root) / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text('{\n  "default_model": "unknown-model-xyz"\n}\n', encoding="utf-8")
        catalog = self.catalog_cls(
            settings=settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "unknown-model-xyz", "object": "model", "owned_by": "custom"},
                    {"id": "mimo-v2.5-pro", "object": "model", "owned_by": "mimo"},
                ]
            ),
        )

        payload = catalog.list_models_payload(force_refresh=True)

        self.assertEqual(payload["meta"]["default_model"], "mimo-v2.5-pro")
        self.assertIn('"default_model": "mimo-v2.5-pro"', settings_file.read_text(encoding="utf-8"))

    def test_verified_runtime_default_is_not_overwritten_by_env_default_after_refresh(self) -> None:
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="mimo-v2.5-pro",
            tasklog_root=str(Path(self.tmp_dir.name) / "tasklog"),
        )
        settings_file = Path(settings.tasklog_root) / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text('{\n  "default_model": "gpt-5.4"\n}\n', encoding="utf-8")
        catalog = self.catalog_cls(
            settings=settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "gpt-5.4", "object": "model", "owned_by": "openai"},
                    {"id": "mimo-v2.5-pro", "object": "model", "owned_by": "mimo"},
                ]
            ),
        )

        payload = catalog.list_models_payload(force_refresh=True)

        self.assertEqual(payload["meta"]["default_model"], "gpt-5.4")
        self.assertEqual(payload["data"][0]["id"], "gpt-5.4")
        self.assertIn('"default_model": "gpt-5.4"', settings_file.read_text(encoding="utf-8"))

    def test_unknown_gateway_model_is_marked_unverified_for_novel_workflow(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "unknown-model-xyz", "object": "model", "owned_by": "custom"},
                ]
            ),
        )

        payload = catalog.list_models_payload()
        model = next(item for item in payload["data"] if item["id"] == "unknown-model-xyz")

        self.assertEqual(model["metadata"]["source"], "gateway")
        self.assertEqual(model["metadata"]["compatibility"], "unverified")
        self.assertFalse(model["capabilities"]["features"]["novel_task_supported"])

    def test_model_capability_json_defaults_apply_to_gateway_only_models(self) -> None:
        config_path = Path(self.tmp_dir.name) / "model_capabilities.json"
        config_path.write_text(
            json.dumps(
                {
                    "defaults": {
                        "max_input_tokens": 200000,
                        "max_output_tokens": 10000,
                        "recommended_prompt_budget": 140000,
                        "compression_trigger_tokens": 100000,
                    },
                    "models": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="mimo-v2.5-pro",
            MODEL_CAPABILITIES_PATH=str(config_path),
            tasklog_root=str(Path(self.tmp_dir.name) / "tasklog"),
        )
        catalog = self.catalog_cls(
            settings=settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "new-gateway-model", "object": "model", "owned_by": "custom"},
                ]
            ),
        )

        payload = catalog.list_models_payload()
        model = next(item for item in payload["data"] if item["id"] == "new-gateway-model")
        context_window = model["capabilities"]["context_window"]

        self.assertEqual(context_window["max_input_tokens"], 200000)
        self.assertEqual(context_window["max_output_tokens"], 10000)
        self.assertEqual(context_window["max_total_tokens"], 210000)
        self.assertEqual(context_window["recommended_prompt_budget"], 140000)
        self.assertEqual(context_window["compression_trigger_tokens"], 100000)

    def test_registry_only_model_cannot_be_used_as_runtime_default(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "gpt-4.1-mini", "object": "model", "owned_by": "openai"},
                ]
            ),
        )

        with self.assertRaisesRegex(ValueError, "未接入网关"):
            catalog.update_default_model("gpt-5.4")

    def test_invalid_runtime_settings_logs_warning_and_uses_config_default(self) -> None:
        settings_file = Path(self.settings.tasklog_root) / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text("{", encoding="utf-8")

        with self.assertLogs("app.llm.model_catalog", level="WARNING") as logs:
            catalog = self.catalog_cls(
                settings=self.settings,
                gateway_client=FakeGatewayClient([{"id": "gpt-5.4"}]),
            )

        self.assertEqual(catalog._effective_default_model(), "gpt-5.4")
        self.assertTrue(any("读取运行时模型设置失败" in message for message in logs.output))

    def test_gateway_model_list_failure_logs_warning_and_returns_fallback_catalog(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FailingGatewayClient(),
        )

        with self.assertLogs("app.llm.model_catalog", level="WARNING") as logs:
            payload = catalog.list_models_payload(force_refresh=True)

        self.assertIn("gpt-5.4", {item["id"] for item in payload["data"]})
        self.assertTrue(any("读取网关模型列表失败" in message for message in logs.output))

    def test_gateway_only_model_can_be_verified_by_local_compatibility_report(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient([{"id": "K2.7", "object": "model", "owned_by": "moonshot"}]),
            compatibility_provider=FakeCompatibilityProvider(
                {
                    "K2.7": {
                        "model_id": "K2.7",
                        "status": "verified",
                        "validated_at": "2026-06-30T10:00:00Z",
                        "validator_version": "2026-06-30",
                        "summary": "验证通过",
                        "failure_reason": "",
                        "checks": [],
                        "evidence": {"chunk_count": 2},
                    }
                }
            ),
        )

        profile = catalog.ensure_novel_generation_model_supported("K2.7")

        self.assertEqual(profile["metadata"]["source"], "gateway")
        self.assertEqual(profile["metadata"]["compatibility"], "verified")
        self.assertEqual(profile["metadata"]["validation"]["status"], "verified")
        self.assertTrue(profile["capabilities"]["features"]["novel_task_supported"])

    def test_saved_compatibility_report_invalidates_cached_catalog(self) -> None:
        from app.llm.model_compatibility import ModelCompatibilityService

        catalog = None
        service = ModelCompatibilityService(
            tasklog_root=self.settings.tasklog_root,
            gateway_client=None,
            model_catalog_resolver=lambda: catalog.list_models(force_refresh=True),
            model_catalog_invalidator=lambda: catalog.invalidate_cache(),
        )
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient([{"id": "K2.7", "object": "model", "owned_by": "moonshot"}]),
            compatibility_provider=service,
        )

        cached_model = next(item for item in catalog.list_models_payload(force_refresh=True)["data"] if item["id"] == "K2.7")
        self.assertEqual(cached_model["metadata"]["compatibility"], "unverified")

        service.save_report(
            service.build_report(
                model_id="K2.7",
                status="verified",
                summary="验证通过",
                checks=[],
                evidence={"chunk_count": 1},
            )
        )

        profile = catalog.ensure_novel_generation_model_supported("K2.7")
        self.assertEqual(profile["metadata"]["compatibility"], "verified")
        self.assertTrue(profile["capabilities"]["features"]["novel_task_supported"])

    def test_failed_compatibility_report_does_not_enable_novel_workflow(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient([{"id": "K2.7", "object": "model", "owned_by": "moonshot"}]),
            compatibility_provider=FakeCompatibilityProvider(
                {
                    "K2.7": {
                        "model_id": "K2.7",
                        "status": "failed",
                        "validated_at": "2026-06-30T10:00:00Z",
                        "validator_version": "2026-06-30",
                        "summary": "验证失败",
                        "failure_reason": "未收到推理信号",
                        "checks": [],
                        "evidence": {},
                    }
                }
            ),
        )

        model = next(item for item in catalog.list_models_payload()["data"] if item["id"] == "K2.7")

        self.assertEqual(model["metadata"]["compatibility"], "unverified")
        self.assertEqual(model["metadata"]["validation"]["status"], "failed")
        self.assertFalse(model["capabilities"]["features"]["novel_task_supported"])
        with self.assertRaisesRegex(ValueError, "未完成兼容性验证"):
            catalog.ensure_novel_generation_model_supported("K2.7")

    def test_registry_only_model_is_not_enabled_by_verified_compatibility_report(self) -> None:
        catalog = self.catalog_cls(
            settings=self.settings,
            gateway_client=FakeGatewayClient([]),
            compatibility_provider=FakeCompatibilityProvider(
                {
                    "gpt-5.4": {
                        "model_id": "gpt-5.4",
                        "status": "verified",
                        "validated_at": "2026-06-30T10:00:00Z",
                        "validator_version": "2026-06-30",
                        "summary": "验证通过",
                        "failure_reason": "",
                        "checks": [],
                        "evidence": {},
                    }
                }
            ),
        )

        model = next(item for item in catalog.list_models_payload()["data"] if item["id"] == "gpt-5.4")

        self.assertEqual(model["metadata"]["source"], "registry")
        self.assertEqual(model["metadata"]["compatibility"], "verified")
        with self.assertRaisesRegex(ValueError, "未接入网关"):
            catalog.ensure_runtime_default_model_supported("gpt-5.4")


def test_corrupted_compatibility_store_logs_once_during_model_catalog_aggregation(caplog) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="gpt-5.4",
            tasklog_root=str(Path(tmp_dir) / "tasklog"),
        )
        compatibility_path = Path(settings.tasklog_root) / "model_compatibility.json"
        compatibility_path.parent.mkdir(parents=True, exist_ok=True)
        compatibility_path.write_text("{ broken json", encoding="utf-8")
        provider = ModelCompatibilityService(
            tasklog_root=settings.tasklog_root,
            gateway_client=None,
            model_catalog_resolver=lambda: [],
        )
        catalog = ModelCatalogService(
            settings=settings,
            gateway_client=FakeGatewayClient(
                [
                    {"id": "K2.7", "object": "model", "owned_by": "moonshot"},
                    {"id": "another-gateway-model", "object": "model", "owned_by": "custom"},
                ]
            ),
            compatibility_provider=provider,
        )

        with caplog.at_level(logging.WARNING, logger="app.llm.model_compatibility"):
            payload = catalog.list_models_payload(force_refresh=True)

        assert {item["id"] for item in payload["data"]} >= {"K2.7", "another-gateway-model"}
        warnings = [
            record
            for record in caplog.records
            if "读取模型兼容性报告失败" in record.message
        ]
        assert len(warnings) == 1


if __name__ == "__main__":
    unittest.main()
