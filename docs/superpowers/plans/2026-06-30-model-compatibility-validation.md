# Model Compatibility Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 AI 对话页增加单模型兼容性验证工作台，让网关新模型通过流式、上下文、推理信号、JSON 与小说最小能力验证后，可被标记为支持小说任务流。

**Architecture:** 后端新增 `ModelCompatibilityService` 管理 `tasklog/model_compatibility.json`、执行验证并输出 SSE；`ModelCatalogService` 应用验证覆盖，把通过验证的网关模型标记为 `verified`。前端在聊天页新增验证面板和验证 SSE 客户端，复用现有模型目录、聊天消息区域和 MUI 布局；模型切换失败处增加跳转到 `/chat?model=...&validate=1` 的引导。

**Tech Stack:** FastAPI, Pydantic, httpx/OpenAI-compatible SSE, Next.js 14 App Router, React 18 Client Components, MUI v5, Python pytest/unittest, Node.js built-in test runner

---

## 参考输入

- 设计规格：`docs/superpowers/specs/2026-06-30-model-compatibility-validation-design.md`
- 当前问题文档：`worklog/active/模型兼容性/20260629-01-模型兼容性验证功能规划.md`
- Context7 已确认：
  - Material UI：`/mui/material-ui`，可沿用当前项目的 `Drawer`、`Alert`、`Tabs`、`Card`、`Chip`、`Stack` 等布局与反馈组件。
  - Next.js：`/vercel/next.js`，聊天页是 Client Component，可继续用 `useEffect`、`useState` 和 `NEXT_PUBLIC_` 客户端环境变量模式。

## 执行边界

- 首批只做单模型、手动触发、单机本地覆盖。
- 不做批量验证、后台自动重验、模型评分榜、独立设置页模型实验室。
- 不展示完整隐藏思考链，不保存 `reasoning_content` 原文片段，不生成来自隐藏思考原文的摘要。
- `content_output` 只判定非空正文；`context_echo` 单独判定上下文哨兵回显。
- `/chat?model=...&validate=1` 中的 `model` 必须 URL 编码。
- `cancelled` 只作为前端临时会话态，不进入后端持久化 schema。

## 文件结构

- Create: `apps/agent-runtime/app/llm/model_compatibility.py`
  - 定义验证报告结构、覆盖文件读写、验证流程、SSE 事件生成。
- Modify: `apps/agent-runtime/app/llm/model_catalog.py`
  - 接受兼容性覆盖 provider，并在构建模型项时应用验证结果。
- Modify: `apps/agent-runtime/app/api/routes.py`
  - 新增 `GET /api/model-validation`、`POST /api/model-validation/stream`、`DELETE /api/model-validation`。
- Modify: `apps/agent-runtime/app/main.py`
  - 实例化 `ModelCompatibilityService`，注入 `ModelCatalogService` 与路由。
- Test: `apps/agent-runtime/tests/test_model_compatibility.py`
  - 覆盖验证服务、持久化、SSE、失败原因。
- Modify: `apps/agent-runtime/tests/test_model_catalog.py`
  - 覆盖 verified/failed 覆盖对模型目录与小说任务门禁的影响。
- Modify: `apps/agent-runtime/tests/test_api_context.py`
  - 覆盖新 API 基础契约。
- Modify: `apps/web/src/lib/types.ts`
  - 增加验证状态、检查项、报告、SSE 事件类型。
- Modify: `apps/web/src/lib/api.ts`
  - 增加验证结果查询、清除、流式验证客户端；保留现有 `streamChat`。
- Create: `apps/web/src/lib/model-validation-events.mjs`
  - 纯函数解析验证 SSE 事件。
- Create: `apps/web/src/lib/model-validation-events.test.mjs`
  - 覆盖 started/check/chat_chunk/done/error/cancelled 解析与错误降级。
- Create: `apps/web/src/features/chat/model-validation-state.mjs`
  - 纯函数合并验证事件、初始化检查项、格式化状态标签、生成 `/chat` 验证链接。
- Create: `apps/web/src/features/chat/model-validation-state.test.mjs`
  - 覆盖检查项状态映射、URL 编码、失败报告、取消临时态。
- Create: `apps/web/src/features/chat/model-validation-panel.tsx`
  - 右侧验证面板 UI。
- Modify: `apps/web/src/features/chat/chat-client.tsx`
  - 读取 query 参数、预选模型、打开验证面板、运行验证、把验证输出插入消息流。
- Modify: `apps/web/src/features/chat/model-selection.mjs`
  - 增加验证状态标签辅助函数，保持现有聊天模型筛选规则。
- Modify: `apps/web/src/app/page.tsx`
  - 首页默认模型保存失败时提供“去 AI 对话验证”链接。
- Modify: `apps/web/src/features/task-create/create-task-client.tsx`
  - 创建任务因未验证失败时提供验证入口链接。
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
  - 运行动作因未验证失败时提供验证入口链接。
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`
  - 审核动作因未验证失败时提供验证入口链接。
- Modify: `worklog/active/模型兼容性/20260629-01-模型兼容性验证功能规划.md`
  - 持续记录实施状态、验证结果和剩余风险。

## 版本门禁

AGENTS.md 要求项目代码修改任务默认将 `<子目录>/src/Cargo.toml` 的 patch 版本 +1。当前仓库先前未发现 `Cargo.toml`，但真正执行前必须重新核对：

```bash
find . -path '*/Cargo.toml' -print
```

Expected: 无输出。若出现 `Cargo.toml`，停止并确认应修改的版本文件。

### Task 0: 执行前门禁

**Files:**
- Modify: `worklog/active/模型兼容性/20260629-01-模型兼容性验证功能规划.md`

- [ ] **Step 1: 核对仓库与工作区**

Run:

```bash
pwd
git rev-parse --show-toplevel
git status --short
find . -path '*/Cargo.toml' -print
```

Expected:
- `pwd` 与 `git rev-parse --show-toplevel` 均为 `/home/user01/WorkSpace/AgentProject`。
- `Cargo.toml` 无输出；若有输出，按版本规则先处理。
- `git status --short` 可存在用户已有变更，但不得回滚非本任务改动。

- [ ] **Step 2: 更新 worklog**

追加：

```markdown
## 实施状态

- 已进入实施前门禁。
- 执行范围：AI 对话页模型兼容性验证、后端本地验证覆盖、模型目录兼容性合并、模型未验证失败引导。
- 版本门禁：当前未发现 `Cargo.toml`；若后续出现版本文件需先确认。
```

### Task 1: 后端验证报告与持久化服务

**Files:**
- Create: `apps/agent-runtime/app/llm/model_compatibility.py`
- Test: `apps/agent-runtime/tests/test_model_compatibility.py`

- [ ] **Step 1: 写持久化失败测试**

Create `apps/agent-runtime/tests/test_model_compatibility.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from app.llm.model_compatibility import (
    CHECK_IDS,
    ModelCompatibilityService,
    build_check,
)


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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_model_compatibility.py -q
```

Expected: FAIL，提示 `app.llm.model_compatibility` 不存在。

- [ ] **Step 3: 实现最小服务**

Create `apps/agent-runtime/app/llm/model_compatibility.py`，至少包含：

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHECK_IDS = [
    "gateway_visible",
    "streaming",
    "content_output",
    "reasoning_signal",
    "context_echo",
    "json_schema",
    "novel_minimum",
]

CHECK_LABELS = {
    "gateway_visible": "网关可见",
    "streaming": "流式输出",
    "content_output": "内容输出",
    "reasoning_signal": "推理信号",
    "context_echo": "上下文回显",
    "json_schema": "结构化 JSON",
    "novel_minimum": "小说任务最小能力",
}

VALID_REPORT_STATUSES = {"verified", "failed", "unverified"}
VALID_CHECK_STATUSES = {"pending", "running", "passed", "failed", "skipped"}
VALIDATOR_VERSION = "2026-06-30"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_check(
    check_id: str,
    status: str,
    summary: str,
    evidence: dict[str, Any] | None = None,
    failure_reason: str = "",
) -> dict[str, Any]:
    if check_id not in CHECK_IDS:
        raise ValueError(f"未知验证项：{check_id}")
    if status not in VALID_CHECK_STATUSES:
        raise ValueError(f"未知验证项状态：{status}")
    return {
        "id": check_id,
        "label": CHECK_LABELS[check_id],
        "status": status,
        "summary": summary,
        "failure_reason": failure_reason,
        "evidence": evidence or {},
    }


class ModelCompatibilityService:
    def __init__(self, tasklog_root: str, gateway_client: Any | None, model_catalog_resolver: Any | None = None) -> None:
        self.tasklog_root = Path(tasklog_root)
        self.gateway_client = gateway_client
        self.model_catalog_resolver = model_catalog_resolver
        self.path = self.tasklog_root / "model_compatibility.json"

    def _load_store(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "models": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "models": {}}
        if not isinstance(data, dict):
            return {"version": 1, "models": {}}
        models = data.get("models")
        if not isinstance(models, dict):
            models = {}
        return {"version": 1, "models": models}

    def _save_store(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_report(
        self,
        model_id: str,
        status: str,
        summary: str,
        checks: list[dict[str, Any]],
        evidence: dict[str, Any] | None = None,
        failure_reason: str = "",
    ) -> dict[str, Any]:
        if status not in VALID_REPORT_STATUSES:
            raise ValueError(f"未知验证状态：{status}")
        return {
            "model_id": model_id,
            "status": status,
            "validated_at": utc_now_iso() if status != "unverified" else "",
            "validator_version": VALIDATOR_VERSION,
            "summary": summary,
            "failure_reason": failure_reason,
            "checks": checks,
            "evidence": evidence or {},
        }

    def get_report(self, model_id: str) -> dict[str, Any]:
        candidate = (model_id or "").strip()
        data = self._load_store()
        report = data["models"].get(candidate)
        if isinstance(report, dict):
            return {"model_id": candidate, **report}
        return self.build_report(candidate, "unverified", "尚未验证", [])

    def save_report(self, report: dict[str, Any]) -> dict[str, Any]:
        model_id = str(report.get("model_id") or "").strip()
        if not model_id:
            raise ValueError("model_id 不能为空")
        data = self._load_store()
        payload = {k: v for k, v in report.items() if k != "model_id"}
        data["models"][model_id] = payload
        self._save_store(data)
        return report

    def clear_report(self, model_id: str) -> dict[str, Any]:
        candidate = (model_id or "").strip()
        data = self._load_store()
        data["models"].pop(candidate, None)
        self._save_store(data)
        return self.get_report(candidate)
```

- [ ] **Step 4: 运行测试通过**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_model_compatibility.py -q
```

Expected: PASS。

### Task 2: 模型目录应用兼容性覆盖

**Files:**
- Modify: `apps/agent-runtime/app/llm/model_catalog.py`
- Modify: `apps/agent-runtime/tests/test_model_catalog.py`

- [ ] **Step 1: 写失败测试**

在 `apps/agent-runtime/tests/test_model_catalog.py` 的 `ModelCatalogServiceTests` 类内新增以下测试方法，保持四空格缩进：

```python
class FakeCompatibilityProvider:
    def __init__(self, reports):
        self.reports = reports

    def get_report(self, model_id):
        return self.reports.get(model_id, {"model_id": model_id, "status": "unverified", "summary": "尚未验证"})


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
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
uv run --project apps/agent-runtime pytest \
  apps/agent-runtime/tests/test_model_catalog.py::ModelCatalogServiceTests::test_gateway_only_model_can_be_verified_by_local_compatibility_report \
  apps/agent-runtime/tests/test_model_catalog.py::ModelCatalogServiceTests::test_failed_compatibility_report_does_not_enable_novel_workflow \
  apps/agent-runtime/tests/test_model_catalog.py::ModelCatalogServiceTests::test_registry_only_model_is_not_enabled_by_verified_compatibility_report \
  -q
```

Expected: FAIL，`ModelCatalogService.__init__()` 不接受 `compatibility_provider`。

- [ ] **Step 3: 实现模型目录覆盖**

Modify `apps/agent-runtime/app/llm/model_catalog.py`:

- `__init__` 增加 `compatibility_provider: Any | None = None`。
- 保存为 `self.compatibility_provider`。
- 在 `_build_model_item()` 返回前调用 `_apply_compatibility_override(item, source)`。
- 规则：
  - 只对 `source` 包含 `gateway` 的模型应用 verified 放行。
  - `status == "verified"`：`metadata.compatibility="verified"`，`features.novel_task_supported=True`，写入 `metadata.validation`。
  - `status == "failed"`：保持或设置 `metadata.compatibility="unverified"`，`features.novel_task_supported=False`，写入 `metadata.validation`。

- [ ] **Step 4: 运行测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_model_catalog.py -q
```

Expected: PASS。

### Task 3: 后端验证流与 API 路由

**Files:**
- Modify: `apps/agent-runtime/app/llm/model_compatibility.py`
- Modify: `apps/agent-runtime/app/api/routes.py`
- Modify: `apps/agent-runtime/app/main.py`
- Test: `apps/agent-runtime/tests/test_model_compatibility.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 写验证流服务测试**

在 `test_model_compatibility.py` 增加异步 fake client 和测试：

```python
import asyncio


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


def test_run_validation_stream_persists_verified_report(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        gateway = FakeStreamingGateway(
            [
                FakeChunk(content='{"context_marker":"CTX-test","outline":[{"title":"雨夜","goal":"发现线索"}],"risk_flags":[]}', reasoning_content="hidden"),
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
        self.assertIn("中文小说", sent_text)


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
        ("missing_context", [FakeChunk(content='{"context_marker":"wrong","outline":[{"title":"雨夜","goal":"发现线索"}],"risk_flags":[]}', reasoning_content="hidden")], "context_echo"),
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
```

- [ ] **Step 2: 实现验证流最小逻辑**

Modify `ModelCompatibilityService`:

- 新增 `_gateway_visible(model_id)`。
- 新增 `async run_validation_stream(model_id, context_marker=None)` 返回 async generator of dict events。
- 新增 `_build_validation_messages(model_id, context_marker)`，必须构造明确验证 prompt：
  - system 消息说明这是模型兼容性验证，不要求文学质量评分。
  - user 消息包含上下文哨兵 `context_marker`，要求原样放入 JSON 的 `context_marker` 字段。
  - user 消息要求返回严格 JSON：`context_marker`、`outline`、`risk_flags`。
  - user 消息要求 `outline` 至少包含 1 个中文小说章节对象 `{title, goal}`。
  - prompt 中不要要求模型输出隐藏思考链；推理信号只由 provider 流式字段观测。
- 使用 `gateway_client.complete_stream()` 收集 content、reasoning length、chunk count、usage。
- `content_output` 只判断 `content.strip()` 非空。
- `context_echo` 判断 `context_marker in content`。
- `json_schema` 从 content 中解析 JSON；可先直接 `json.loads(content)`，后续实现可从包裹文本中抽取 JSON。
- `novel_minimum` 判断 outline 非空或中文内容非空。
- 验证通过保存 verified；验证失败保存 failed；不保存 reasoning 原文。

- [ ] **Step 3: 写 API 失败测试**

在 `apps/agent-runtime/tests/test_api_context.py` 增加路由测试。若现有测试有 `TestClient`/fixture，沿用现有模式；否则创建最小 FastAPI app 调 `build_router(..., model_compatibility_service=fake)`。

断言：

- `GET /api/model-validation?model_id=K2.7` 返回 `status`。
- `DELETE /api/model-validation` body `{"model_id":"K2.7"}` 返回 `unverified`。
- `POST /api/model-validation/stream` 返回 `text/event-stream` 且包含 `validation.started`。

- [ ] **Step 4: 修改路由构造**

Modify `apps/agent-runtime/app/api/routes.py`:

- `build_router(..., model_compatibility_service=None)`。
- 增加三个接口：
  - `GET /model-validation`
  - `POST /model-validation/stream`
  - `DELETE /model-validation`
- 使用 Pydantic 或 dict body 读取 `model_id`。
- `POST` 将 `service.run_validation_stream()` 包装为 `StreamingResponse`，事件格式：

```python
yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
```

- [ ] **Step 5: 修改 main 注入服务**

Modify `apps/agent-runtime/app/main.py`:

- 创建 `model_compatibility_service = ModelCompatibilityService(settings.tasklog_root, engine.gateway_client, model_catalog_resolver=lambda: model_catalog.list_models(force_refresh=True))`。
- 创建 `ModelCatalogService(..., compatibility_provider=model_compatibility_service)`。
- 将 `model_compatibility_service` 传入 `build_router()`。

注意初始化顺序：`model_catalog_resolver` lambda 可以引用稍后已赋值的 `model_catalog`，但要避免在构造时立即调用。

- [ ] **Step 6: 运行后端测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_model_compatibility.py apps/agent-runtime/tests/test_model_catalog.py apps/agent-runtime/tests/test_api_context.py -q
```

Expected: PASS。

### Task 4: 前端验证 SSE 解析与状态纯函数

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`
- Create: `apps/web/src/lib/model-validation-events.mjs`
- Create: `apps/web/src/lib/model-validation-events.test.mjs`
- Create: `apps/web/src/features/chat/model-validation-state.mjs`
- Create: `apps/web/src/features/chat/model-validation-state.test.mjs`

- [ ] **Step 1: 写 SSE parser 测试**

Create `apps/web/src/lib/model-validation-events.test.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { createModelValidationSseParser } from "./model-validation-events.mjs";

test("parses validation check and done events", () => {
  const events = [];
  const parser = createModelValidationSseParser({
    onEvent: (event) => events.push(event),
    onError: (message) => events.push({ type: "error", message }),
  });

  parser.push('event: validation.check\\n');
  parser.push('data: {"check":{"id":"streaming","status":"passed"}}\\n\\n');
  parser.push('event: validation.done\\n');
  parser.push('data: {"status":"verified","report":{"status":"verified"}}\\n\\n');
  parser.flush();

  assert.equal(events[0].type, "validation.check");
  assert.equal(events[0].data.check.id, "streaming");
  assert.equal(events[1].type, "validation.done");
});
```

- [ ] **Step 2: 写状态 reducer 测试**

Create `apps/web/src/features/chat/model-validation-state.test.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import {
  buildValidationChatUrl,
  createInitialValidationState,
  reduceValidationEvent,
} from "./model-validation-state.mjs";

test("buildValidationChatUrl encodes model id", () => {
  assert.equal(buildValidationChatUrl("vendor/model 1"), "/chat?model=vendor%2Fmodel%201&validate=1");
});

test("reduceValidationEvent updates check status and report", () => {
  let state = createInitialValidationState("K2.7");
  state = reduceValidationEvent(state, {
    type: "validation.check",
    data: { check: { id: "streaming", status: "passed", summary: "收到 chunk", evidence: {} } },
  });
  assert.equal(state.checks.find((item) => item.id === "streaming").status, "passed");
  state = reduceValidationEvent(state, {
    type: "validation.done",
    data: { status: "verified", report: { status: "verified", checks: [] } },
  });
  assert.equal(state.status, "verified");
});

test("cancelled is frontend-only temporary state", () => {
  let state = createInitialValidationState("K2.7");
  state = reduceValidationEvent(state, { type: "validation.cancelled", data: { message: "用户取消验证" } });
  assert.equal(state.status, "cancelled");
  assert.equal(state.report, null);
});
```

- [ ] **Step 3: 实现 parser 与 reducer**

Implement:

- `createModelValidationSseParser({ onEvent, onError })`，模式可参考 `stream-chat-events.mjs`。
- `CHECK_IDS`、`createInitialValidationState()`、`reduceValidationEvent()`、`buildValidationChatUrl(modelId)`。

- [ ] **Step 4: 增加类型与 API**

Modify `apps/web/src/lib/types.ts`:

- `ModelValidationCheck`
- `ModelValidationReport`
- `ModelValidationStatus = "unverified" | "running" | "verified" | "failed" | "cancelled"`
- `ModelValidationEvent`
- `ModelMetadata.validation?: ModelValidationReport`

Modify `apps/web/src/lib/api.ts`:

- `getModelValidation(modelId)`
- `clearModelValidation(modelId)`
- `streamModelValidation(modelId, callbacks, signal)`
- `normalizeModelOptions()` 保留 `metadata.validation`。

- [ ] **Step 5: 运行前端单元测试**

Run:

```bash
npm --prefix apps/web test -- src/lib/model-validation-events.test.mjs src/features/chat/model-validation-state.test.mjs
```

Expected: PASS。

### Task 5: AI 对话页验证面板

**Files:**
- Create: `apps/web/src/features/chat/model-validation-panel.tsx`
- Modify: `apps/web/src/features/chat/chat-client.tsx`
- Modify: `apps/web/src/features/chat/model-selection.mjs`
- Test: `apps/web/src/features/chat/model-selection.test.mjs`
- Test: `apps/web/src/features/chat/model-validation-state.test.mjs`

- [ ] **Step 1: 写模型状态标签测试**

Extend `model-selection.test.mjs`:

```javascript
import { getModelValidationLabel } from "./model-selection.mjs";

test("getModelValidationLabel returns verified failed and unverified labels", () => {
  assert.equal(getModelValidationLabel({ metadata: { compatibility: "verified" } }), "已验证");
  assert.equal(getModelValidationLabel({ metadata: { validation: { status: "failed" } } }), "最近验证失败");
  assert.equal(getModelValidationLabel({ metadata: { compatibility: "unverified" } }), "未验证");
});
```

- [ ] **Step 2: 实现 `ModelValidationPanel`**

Create component props:

```ts
interface ModelValidationPanelProps {
  model: ModelOption | null;
  state: ValidationState;
  running: boolean;
  onRun: () => void;
  onClear: () => void;
  onCancel: () => void;
}
```

UI:

- `Card` / `Stack` / `Chip` 展示模型与状态。
- `Button`：运行验证、重新验证、清除验证、取消。
- `Alert` 展示失败原因。
- 检查项列表用 `List` 或 `Stack`，状态图标用 MUI icons。
- 移动端由 `ChatClient` 负责 Drawer，组件本身保持纯展示。

- [ ] **Step 3: 修改 `ChatClient` 状态**

Modify `chat-client.tsx`:

- 使用 `window.location.search` 在 `useEffect` 中读取 query，避免 `useSearchParams` 触发 App Router 静态构建的 Suspense 要求。
- 新增 `validationPanelOpen`、`validationState`、`validationRunning`。
- 扩展本地 `DisplayMessage`，增加可选 `validation_meta?: { reasoningSignal?: boolean; reasoningChars?: number; runId?: string }`；该字段只用于验证消息，不持久化为普通 `reasoning_content`。
- 初次加载模型后，如果 query 有 `model`，预选该模型；如果 `validate=1`，打开面板。
- 不自动运行验证。

- [ ] **Step 4: 实现运行验证**

在 `ChatClient` 中：

- 点击运行验证时 abort 普通聊天请求。
- 插入用户消息 `运行模型兼容性验证：<modelId>` 和空助手消息。
- 调用 `streamModelValidation(modelId, ...)`。
- `validation.chat_chunk` 的 `content` 累加到助手消息正文。
- `reasoning_signal/reasoning_chars_delta` 更新助手消息的专用 `validation_meta` 字段，例如 `{reasoningSignal: true, reasoningChars: 126}`；不要写入普通 `reasoning_content`，避免在“思考过程”区域展示验证元数据。
- 渲染验证消息时，在消息底部用专用 `Chip` / `Typography` 展示 `收到推理信号，累计 126 字符`。
- `validation.done` 后刷新模型目录 `getModelCatalog({ refresh: true })`。
- 用户取消时 abort controller，状态进入前端临时 `cancelled`，不调用清除接口。

- [ ] **Step 5: 布局**

桌面端：

- 当前 `ChatClient` 是左侧会话 + 主对话两列。
- 改为左侧会话 + 主对话 + 右侧验证面板三列。
- 右侧宽度建议 `320px`，可在 `md` 以上显示。

移动端：

- 标题栏增加一个带图标的“验证”按钮。
- 点击打开 MUI `Drawer`，宽度 `min(100vw, 360px)`。

- [ ] **Step 6: 运行前端测试**

Run:

```bash
npm --prefix apps/web test -- src/features/chat/model-selection.test.mjs src/features/chat/model-validation-state.test.mjs
npm --prefix apps/web run lint
```

Expected: PASS。

### Task 6: 未验证失败引导

**Files:**
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/features/task-create/create-task-client.tsx`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`
- Modify: `apps/web/src/features/chat/model-validation-state.mjs`
- Test: `apps/web/src/features/chat/model-validation-state.test.mjs`

- [ ] **Step 1: 增加错误识别与链接函数测试**

Extend `model-validation-state.test.mjs`:

```javascript
import { getValidationLinkFromError } from "./model-validation-state.mjs";

test("getValidationLinkFromError returns encoded chat validation link for compatibility error", () => {
  const link = getValidationLinkFromError("模型 vendor/model 1 未完成兼容性验证，暂不支持小说任务流。", "vendor/model 1");
  assert.equal(link, "/chat?model=vendor%2Fmodel%201&validate=1");
});

test("getValidationLinkFromError ignores unrelated errors", () => {
  assert.equal(getValidationLinkFromError("网络失败", "K2.7"), "");
});
```

- [ ] **Step 2: 实现错误识别**

In `model-validation-state.mjs`:

```js
export function isCompatibilityValidationError(message) {
  return /未完成兼容性验证|暂不支持小说任务流/.test(String(message || ""));
}
```

`getValidationLinkFromError(message, modelId)` 返回编码链接或空字符串。

- [ ] **Step 3: 修改首页默认模型失败提示**

在 `apps/web/src/app/page.tsx` 中找到 `updateDefaultModel()` 的失败处理逻辑。

当捕获错误且当前模型 ID 可得：

- 显示 `Alert` 或 `Snackbar` 文案。
- 增加 `Button component={Link} href={buildValidationChatUrl(modelId)}` 文案 `去 AI 对话验证`。

- [ ] **Step 4: 修改创建/运行/审核页错误提示**

对 `createTask`、`runTask`、`continueTask`、`resumeTask` 等 catch 中：

- 判断错误是否兼容性验证失败。
- 使用当前选中模型 ID 生成验证链接。
- 在错误 Alert 或动作区展示 `去 AI 对话验证`。

不要改变原有阻断语义，不自动重试任务。

- [ ] **Step 5: 运行相关前端测试**

Run:

```bash
npm --prefix apps/web test -- src/features/chat/model-validation-state.test.mjs
npm --prefix apps/web run lint
```

Expected: PASS。

### Task 7: 端到端手工验证与真实模型验证

**Files:**
- Modify: `worklog/active/模型兼容性/20260629-01-模型兼容性验证功能规划.md`

- [ ] **Step 1: 启动服务**

Run:

```bash
# 后端
uv run --project apps/agent-runtime python -m uvicorn app.main:app --app-dir apps/agent-runtime --host localhost --port 8000 --reload

# 前端
npm --prefix apps/web run dev -- --hostname localhost --port 3000
```

若已有服务运行，先确认是否为本仓库服务；不要误杀无关进程。

- [ ] **Step 2: API 冒烟**

Run:

```bash
curl -sS "http://localhost:8000/api/models?refresh=true" | python3 -m json.tool | sed -n '1,120p'
curl -sS "http://localhost:8000/api/model-validation?model_id=K2.7" | python3 -m json.tool
```

Expected:

- `K2.7` 存在且初始可为 `unverified`。
- validation 查询返回 JSON。

- [ ] **Step 3: 前端验证流程**

打开：

```text
http://localhost:3000/chat?model=K2.7&validate=1
```

Expected:

- 聊天模型预选 `K2.7`。
- 验证面板打开。
- 不自动发起验证。
- 点击 `运行验证` 后检查项逐项更新。

- [ ] **Step 4: 真实端到端模型验证**

使用真实 `LLM_API_KEY` / `LLM_BASE_URL` 已配置环境运行验证。

记录：

- 是否收到 `validation.chat_chunk`。
- 是否收到推理信号元数据。
- 是否通过上下文哨兵回显。
- 是否通过 JSON schema。
- 最终 `K2.7` 是否变为 `verified`。

如果失败，记录具体失败项与后端返回原因，不手动改覆盖文件伪造通过。

- [ ] **Step 5: 验证小说任务门禁**

验证通过后：

```bash
curl -sS "http://localhost:8000/api/models?refresh=true" | python3 -c 'import json,sys; payload=json.load(sys.stdin); [print(json.dumps(item["metadata"], ensure_ascii=False, indent=2), "\n" + json.dumps(item["capabilities"]["features"], ensure_ascii=False, indent=2)) for item in payload["data"] if item["id"] == "K2.7"]'
```

Expected:

- `metadata.compatibility == "verified"`
- `features.novel_task_supported == true`

- [ ] **Step 6: 更新 worklog**

记录：

```markdown
## 验证结果

- 后端单测：通过/失败，命令与摘要。
- 前端单测：通过/失败，命令与摘要。
- Lint：通过/失败。
- 真实 K2.7 验证：通过/失败；失败项与原因。
- 小说任务门禁：通过/失败。
```

### Task 8: 收口验证

**Files:**
- Modify: `worklog/active/模型兼容性/20260629-01-模型兼容性验证功能规划.md`

- [ ] **Step 1: 全量相关测试**

Run:

```bash
uv run --project apps/agent-runtime pytest \
  apps/agent-runtime/tests/test_model_compatibility.py \
  apps/agent-runtime/tests/test_model_catalog.py \
  apps/agent-runtime/tests/test_api_context.py \
  -q

npm --prefix apps/web test -- \
  src/lib/model-validation-events.test.mjs \
  src/features/chat/model-validation-state.test.mjs \
  src/features/chat/model-selection.test.mjs

npm --prefix apps/web run lint

npm --prefix apps/web run build
```

Expected: 全部 PASS。

- [ ] **Step 2: 项目接口冒烟**

如果服务已启动：

```bash
python3 .agents/skills/project-interface-smoke/scripts/run_smoke.py \
  --frontend-url http://localhost:3000 \
  --backend-url http://localhost:8000
```

Expected: 无阻断性失败。若 smoke 创建任务用默认模型，与本功能无关的失败需单独记录。

- [ ] **Step 3: 最终 worklog 状态**

更新当前问题文档：

```markdown
## 当前状态

已完成实现与验证，等待用户确认是否归档提交。
```

不要自动归档；根据 AGENTS.md，只有用户明确同意收口后才归档并提交。
