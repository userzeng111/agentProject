import asyncio
import json
import logging
import time
import tempfile
import unittest
from pathlib import Path

from app.llm.model_compatibility import (
    CHECK_IDS,
    ModelCompatibilityService,
    build_check,
)


class FakeChunk:
    def __init__(self, content="", reasoning_content="", finish_reason=None, usage=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.finish_reason = finish_reason
        self.usage = usage or {}


class FakeStreamingGateway:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    async def complete_stream(self, messages, model=None, **kwargs):
        self.calls.append({"messages": messages, "model": model, "kwargs": kwargs})
        for chunk in self.chunks:
            yield chunk


class RaisingStreamingGateway:
    async def complete_stream(self, messages, model=None, **kwargs):
        raise RuntimeError("stream interrupted")


def collect_async(async_iterable):
    async def _collect():
        return [item async for item in async_iterable]

    return asyncio.run(_collect())


class ModelCompatibilityServiceTests(unittest.TestCase):
    def test_save_and_load_verified_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ModelCompatibilityService(
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                gateway_client=None,
                model_catalog_resolver=lambda: [],
            )
            report = service.build_report(
                model_id="K2.7",
                status="verified",
                summary="验证通过",
                checks=[
                    build_check("gateway_visible", "passed", "模型来自网关"),
                    build_check("streaming", "passed", "收到 2 个 chunk", {"chunk_count": 2}),
                    build_check("content_output", "passed", "收到非空正文", {"content_chars": 20}),
                    build_check("reasoning_signal", "passed", "收到推理信号元数据", {"reasoning_chars": 12}),
                    build_check("context_echo", "passed", "已回显上下文哨兵", {"context_marker_seen": True}),
                    build_check("json_schema", "passed", "JSON 可解析"),
                    build_check("novel_minimum", "passed", "中文小说片段非空"),
                ],
                evidence={"chunk_count": 2, "reasoning_chars": 12, "content_chars": 20, "context_marker_seen": True},
            )

            service.save_report(report)

            loaded = service.get_report("K2.7")
            self.assertEqual(loaded["status"], "verified")
            self.assertEqual(loaded["model_id"], "K2.7")
            self.assertEqual([item["id"] for item in loaded["checks"]], CHECK_IDS)
            path = Path(tmp_dir) / "tasklog" / "model_compatibility.json"
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["models"]["K2.7"]["status"], "verified")

    def test_missing_report_returns_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ModelCompatibilityService(
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                gateway_client=None,
                model_catalog_resolver=lambda: [],
            )

            report = service.get_report("unknown")

            self.assertEqual(report["status"], "unverified")
            self.assertEqual(report["model_id"], "unknown")

    def test_clear_report_removes_only_target_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ModelCompatibilityService(
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                gateway_client=None,
                model_catalog_resolver=lambda: [],
            )
            service.save_report(service.build_report("A", "failed", "失败", [], failure_reason="x"))
            service.save_report(service.build_report("B", "verified", "通过", []))

            service.clear_report("A")

            self.assertEqual(service.get_report("A")["status"], "unverified")
            self.assertEqual(service.get_report("B")["status"], "verified")

    def test_run_validation_stream_persists_verified_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            gateway = FakeStreamingGateway(
                [
                    FakeChunk(
                        content='{"context_marker":"CTX-test","outline":[{"title":"雨夜","goal":"发现线索"}],"risk_flags":[]}',
                        reasoning_content="hidden",
                    ),
                    FakeChunk(finish_reason="stop", usage={"total_tokens": 80}),
                ]
            )
            service = ModelCompatibilityService(
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                gateway_client=gateway,
                model_catalog_resolver=lambda: [{"id": "K2.7", "metadata": {"source": "gateway"}}],
            )

            events = collect_async(service.run_validation_stream("K2.7", context_marker="CTX-test"))

            self.assertEqual(events[0]["event"], "validation.started")
            self.assertTrue(any(item["event"] == "validation.chat_chunk" for item in events))
            self.assertEqual(events[-1]["event"], "validation.done")
            report = service.get_report("K2.7")
            self.assertEqual(report["status"], "verified")
            self.assertTrue(report["evidence"]["context_marker_seen"])
            self.assertGreater(report["evidence"]["reasoning_chars"], 0)
            self.assertNotIn("hidden", json.dumps(report, ensure_ascii=False))
            sent_text = "\n".join(item["content"] for item in gateway.calls[0]["messages"])
            self.assertIn("CTX-test", sent_text)
            self.assertIn("context_marker", sent_text)
            self.assertIn("outline", sent_text)
            self.assertIn("risk_flags", sent_text)
            self.assertIn("中文小说", sent_text)

    def test_run_validation_stream_emits_reasoning_metadata_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            gateway = FakeStreamingGateway(
                [
                    FakeChunk(reasoning_content="hidden"),
                    FakeChunk(
                        content='{"context_marker":"CTX-test","outline":[{"title":"雨夜","goal":"发现线索"}],"risk_flags":[]}',
                    ),
                ]
            )
            service = ModelCompatibilityService(
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                gateway_client=gateway,
                model_catalog_resolver=lambda: [{"id": "K2.7", "metadata": {"source": "gateway"}}],
            )

            events = collect_async(service.run_validation_stream("K2.7", context_marker="CTX-test"))

            reasoning_events = [
                item
                for item in events
                if item["event"] == "validation.chat_chunk"
                and item["data"].get("reasoning_signal")
                and item["data"].get("reasoning_chars_delta", 0) > 0
            ]
            self.assertTrue(reasoning_events)
            self.assertEqual(events[-1]["event"], "validation.done")
            self.assertNotIn("hidden", json.dumps(events[-1]["data"]["report"], ensure_ascii=False))

    def test_run_validation_stream_fails_without_reasoning_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ModelCompatibilityService(
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                gateway_client=FakeStreamingGateway(
                    [
                        FakeChunk(content='{"context_marker":"CTX-test","outline":[{"title":"雨夜","goal":"发现线索"}],"risk_flags":[]}'),
                        FakeChunk(finish_reason="stop"),
                    ]
                ),
                model_catalog_resolver=lambda: [{"id": "K2.7", "metadata": {"source": "gateway"}}],
            )

            events = collect_async(service.run_validation_stream("K2.7", context_marker="CTX-test"))

            self.assertEqual(events[-1]["event"], "validation.error")
            self.assertEqual(events[-1]["data"]["check_id"], "reasoning_signal")
            report = service.get_report("K2.7")
            self.assertEqual(report["status"], "failed")
            self.assertIn("推理信号", report["failure_reason"])
            checks_by_id = {item["id"]: item for item in report["checks"]}
            self.assertEqual(checks_by_id["context_echo"]["status"], "passed")
            self.assertEqual(checks_by_id["json_schema"]["status"], "passed")
            self.assertEqual(checks_by_id["novel_minimum"]["status"], "passed")

    def test_run_validation_stream_fails_when_gateway_model_is_not_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ModelCompatibilityService(
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                gateway_client=FakeStreamingGateway([]),
                model_catalog_resolver=lambda: [{"id": "other-model", "metadata": {"source": "gateway"}}],
            )

            events = collect_async(service.run_validation_stream("K2.7", context_marker="CTX-test"))

            self.assertEqual(events[-1]["event"], "validation.error")
            self.assertEqual(events[-1]["data"]["check_id"], "gateway_visible")
            self.assertEqual(service.get_report("K2.7")["status"], "failed")

    def test_run_validation_stream_fails_for_required_gate_conditions(self) -> None:
        cases = [
            ("no_chunk", [], "streaming"),
            (
                "missing_context",
                [FakeChunk(content='{"context_marker":"wrong","outline":[{"title":"雨夜","goal":"发现线索"}],"risk_flags":[]}', reasoning_content="hidden")],
                "context_echo",
            ),
            ("invalid_json", [FakeChunk(content="CTX-test 不是 JSON", reasoning_content="hidden")], "json_schema"),
            ("empty_outline", [FakeChunk(content='{"context_marker":"CTX-test","outline":[],"risk_flags":[]}', reasoning_content="hidden")], "novel_minimum"),
        ]
        for _name, chunks, expected_check_id in cases:
            with self.subTest(_name), tempfile.TemporaryDirectory() as tmp_dir:
                service = ModelCompatibilityService(
                    tasklog_root=str(Path(tmp_dir) / "tasklog"),
                    gateway_client=FakeStreamingGateway(chunks),
                    model_catalog_resolver=lambda: [{"id": "K2.7", "metadata": {"source": "gateway"}}],
                )

                events = collect_async(service.run_validation_stream("K2.7", context_marker="CTX-test"))

                self.assertEqual(events[-1]["event"], "validation.error")
                self.assertEqual(events[-1]["data"]["check_id"], expected_check_id)
                self.assertEqual(service.get_report("K2.7")["status"], "failed")

    def test_run_validation_stream_fails_when_gateway_stream_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ModelCompatibilityService(
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
                gateway_client=RaisingStreamingGateway(),
                model_catalog_resolver=lambda: [{"id": "K2.7", "metadata": {"source": "gateway"}}],
            )

            events = collect_async(service.run_validation_stream("K2.7", context_marker="CTX-test"))

            self.assertEqual(events[-1]["event"], "validation.error")
            self.assertEqual(events[-1]["data"]["check_id"], "streaming")
            self.assertIn("stream interrupted", events[-1]["data"]["message"])


def test_get_report_warns_and_returns_unverified_when_store_json_is_corrupted(caplog) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tasklog_root = Path(tmp_dir) / "tasklog"
        tasklog_root.mkdir(parents=True)
        (tasklog_root / "model_compatibility.json").write_text("{ broken json", encoding="utf-8")
        service = ModelCompatibilityService(
            tasklog_root=str(tasklog_root),
            gateway_client=None,
            model_catalog_resolver=lambda: [],
        )

        with caplog.at_level(logging.WARNING):
            report = service.get_report("K2.7")

        assert report["status"] == "unverified"
        assert report["model_id"] == "K2.7"
        assert any("model_compatibility.json" in record.message for record in caplog.records)


def test_save_report_warns_when_model_catalog_cache_invalidation_fails(caplog) -> None:
    def raise_invalidator() -> None:
        raise RuntimeError("invalidate failed")

    with tempfile.TemporaryDirectory() as tmp_dir:
        service = ModelCompatibilityService(
            tasklog_root=str(Path(tmp_dir) / "tasklog"),
            gateway_client=None,
            model_catalog_resolver=lambda: [],
            model_catalog_invalidator=raise_invalidator,
        )

        report = service.build_report(
            model_id="K2.7",
            status="verified",
            summary="验证通过",
            checks=[],
        )

        with caplog.at_level(logging.WARNING):
            saved = service.save_report(report)

        assert saved["status"] == "verified"
        assert any("刷新模型目录缓存失败" in record.message for record in caplog.records)


def test_gateway_visible_warns_and_returns_false_when_catalog_resolver_fails(caplog) -> None:
    def raise_resolver():
        raise RuntimeError("catalog down")

    with tempfile.TemporaryDirectory() as tmp_dir:
        service = ModelCompatibilityService(
            tasklog_root=str(Path(tmp_dir) / "tasklog"),
            gateway_client=None,
            model_catalog_resolver=raise_resolver,
        )

        with caplog.at_level(logging.WARNING):
            visible = service._gateway_visible("K2.7")

        assert visible is False
        assert any("读取模型目录失败" in record.message for record in caplog.records)


def test_get_report_reloads_when_store_file_changes_externally() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tasklog_root = Path(tmp_dir) / "tasklog"
        tasklog_root.mkdir(parents=True)
        path = tasklog_root / "model_compatibility.json"
        path.write_text(
            json.dumps({"version": 1, "models": {"K2.7": {"status": "failed", "summary": "旧报告"}}}, ensure_ascii=False),
            encoding="utf-8",
        )
        service = ModelCompatibilityService(
            tasklog_root=str(tasklog_root),
            gateway_client=None,
            model_catalog_resolver=lambda: [],
        )

        assert service.get_report("K2.7")["status"] == "failed"

        time.sleep(0.001)
        path.write_text(
            json.dumps({"version": 1, "models": {"K2.7": {"status": "verified", "summary": "新报告"}}}, ensure_ascii=False),
            encoding="utf-8",
        )

        report = service.get_report("K2.7")

        assert report["status"] == "verified"
        assert report["summary"] == "新报告"


def test_clear_report_updates_store_cache_immediately() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = ModelCompatibilityService(
            tasklog_root=str(Path(tmp_dir) / "tasklog"),
            gateway_client=None,
            model_catalog_resolver=lambda: [],
        )
        service.save_report(service.build_report("K2.7", "verified", "验证通过", []))

        assert service.get_report("K2.7")["status"] == "verified"

        service.clear_report("K2.7")

        assert service.get_report("K2.7")["status"] == "unverified"


def test_corrupted_store_can_be_repaired_and_reloaded(caplog) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tasklog_root = Path(tmp_dir) / "tasklog"
        tasklog_root.mkdir(parents=True)
        path = tasklog_root / "model_compatibility.json"
        path.write_text("{ broken json", encoding="utf-8")
        service = ModelCompatibilityService(
            tasklog_root=str(tasklog_root),
            gateway_client=None,
            model_catalog_resolver=lambda: [],
        )

        with caplog.at_level(logging.WARNING):
            assert service.get_report("K2.7")["status"] == "unverified"

        time.sleep(0.001)
        path.write_text(
            json.dumps({"version": 1, "models": {"K2.7": {"status": "verified", "summary": "已修复"}}}, ensure_ascii=False),
            encoding="utf-8",
        )

        report = service.get_report("K2.7")

        assert report["status"] == "verified"
        assert report["summary"] == "已修复"


if __name__ == "__main__":
    unittest.main()
