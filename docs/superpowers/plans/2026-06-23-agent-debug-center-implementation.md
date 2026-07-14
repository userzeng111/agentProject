# Agent Debug Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有任务工作台内新增只读“调试”标签页，展示任务健康结论、实时连接、LLM、Agent Trace、上下文/RAG、状态对账和证据链接。

**Architecture:** 后端只在 `WorkspaceResponse` 增加两个稳定只读摘要字段：`pending_review_summary` 与 `rag_status`，不新增 debug API。前端把诊断规则放入可单测纯函数 `debug-diagnostics.mjs`，`debug-panel.tsx` 只消费派生结果并渲染第 5 个任务工作台 Tab。

**Tech Stack:** FastAPI, Pydantic, LangGraph task workspace, Next.js 14 App Router, React 18, MUI v5, Python pytest, Node test runner

---

## 参考输入

- 规格：`docs/superpowers/specs/2026-06-23-agent-debug-center-design.md`
- 当前问题文档：`worklog/active/功能开发/20260623-01-AgentProject功能补充方向分析.md`
- Context7 已确认：
  - Material UI：`/mui/material-ui`，沿用当前 `Tabs variant="scrollable"`、`scrollButtons`、`allowScrollButtonsMobile` 模式。
  - Next.js：`/vercel/next.js`，当前 `TaskRunClient` 是 Client Component，新增本地组件可继续使用 hooks 与本地导入。

## 执行边界

- 首批只做任务级调试 Tab，不做全局 `/debug`。
- 不新增事件分页 API、完整日志浏览器、LLM exchange 全量列表、Supervisor 实调度、可靠任务队列、显式状态转移表。
- 默认不展示完整 prompt、raw response、上传素材全文或章节正文。
- `pending_review_summary` 不返回待审核正文，只返回类型、阶段、批次、修订计数和短摘要。
- `rag_status` 不返回检索命中文本或完整上下文，只返回 enabled/ready/summary/last_error/injected 等摘要。
- SSE 连接状态只影响“实时连接”模块，不能单独把运行中任务判定为“状态不一致”。

## 文件结构

- Modify: `apps/agent-runtime/app/domain/models.py`
  - 在 `WorkspaceResponse` 增加 `pending_review_summary`、`rag_status` 两个 `dict[str, Any]` 字段。
- Modify: `apps/agent-runtime/app/application/task_service/queries.py`
  - 增加 `_build_pending_review_summary()` 与 `_build_rag_status()`，并在 `get_workspace()` 组装。
- Test: `apps/agent-runtime/tests/test_task_service_workspace.py`
  - 覆盖 service 层字段、无正文泄露、RAG ready/not ready/error/unknown 降级，以及无 RAG 事件时的上下文注入证据兜底。
- Test: `apps/agent-runtime/tests/test_api_context.py`
  - 覆盖 `/api/tasks/{task_id}/workspace` JSON 返回新字段。
- Modify: `apps/web/src/lib/types.ts`
  - 增加 `PendingReviewSummary`、`RagStatus` 类型，并挂入 `WorkspaceResponse`。
- Create: `apps/web/src/features/task-run/debug-diagnostics.mjs`
  - 纯函数派生整体诊断、状态对账、LLM 摘要、Agent Trace 摘要、上下文/RAG 摘要、证据链接。
  - 状态对账必须覆盖 `pending_review_summary`、`novel_progress`、`supervisor_plan`、恢复契约字段、最近事件阶段，不能只检查单一字段。
- Create: `apps/web/src/features/task-run/debug-diagnostics.test.mjs`
  - Node test runner 覆盖诊断优先级和降级行为。
- Create: `apps/web/src/features/task-run/debug-panel.tsx`
  - 只读 UI，渲染七个模块。
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
  - 导入 `DebugPanel`，新增第 5 个“调试” Tab，传入 `workspace`、`streamState`、`streamPath`、`onRefresh`、`onOpenRecovery`。
- Modify: `worklog/active/功能开发/20260623-01-AgentProject功能补充方向分析.md`
  - 记录计划落盘、执行状态和验证结果。

## 版本门禁

当前仓库检查未发现任何 `Cargo.toml`，因此本次无法执行 AGENTS.md 中的 `src/Cargo.toml` patch +1 规则。真正进入代码修改前必须再次执行：

```bash
find . -path '*/Cargo.toml' -print
```

Expected: 无输出。若出现 `Cargo.toml`，先停止并确认应修改的 `<子目录>/src/Cargo.toml`。

### Task 0: 执行前门禁

**Files:**
- Modify: `worklog/active/功能开发/20260623-01-AgentProject功能补充方向分析.md`

- [ ] **Step 1: 核对工作区与版本文件**

Run:

```bash
pwd
git rev-parse --show-toplevel
git status --short
find . -path '*/Cargo.toml' -print
```

Expected:
- `pwd` 和 `git rev-parse --show-toplevel` 均指向 `/home/user01/WorkSpace/AgentProject`。
- `Cargo.toml` 无输出；若有输出，先处理版本规则。
- `git status --short` 允许存在用户已有变更，但执行时不得回滚非本任务改动。

- [ ] **Step 2: 更新 worklog 当前状态**

在当前问题文档追加：

```markdown
## Agent 运行调试中心实施状态

- 已进入代码实施前门禁。
- 本次执行范围：任务工作台内只读调试 Tab；后端仅补 `WorkspaceResponse.pending_review_summary` 与 `WorkspaceResponse.rag_status`。
- 版本门禁：当前未发现 `Cargo.toml`，无法执行 Cargo patch +1；若后续出现版本文件需先确认。
```

### Task 1: 后端 Workspace 调试摘要字段

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Modify: `apps/agent-runtime/app/application/task_service/queries.py`
- Test: `apps/agent-runtime/tests/test_task_service_workspace.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 写 service 层失败测试**

在 `apps/agent-runtime/tests/test_task_service_workspace.py` 的 import 中补充：

```python
from app.domain.models import ReviewPayload, StoryPlan
```

新增测试，确保等待审核任务返回摘要且不泄露正文：

```python
def test_workspace_exposes_pending_review_summary_without_review_body(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="gpt-5.4",
            tasklog_root=str(Path(tmp_dir) / "tasklog"),
        )
        store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
        engine = FakeEngine(settings)
        model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)
        service = TaskService(store=store, engine=engine, model_catalog=model_catalog)

        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一部克制风格的都市悬疑小说",
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
        store.set_waiting_review(task.id, review, story_plan)

        workspace = service.get_workspace(task.id)

        self.assertTrue(workspace.pending_review_summary["present"])
        self.assertEqual(workspace.pending_review_summary["review_type"], "outline_review")
        self.assertEqual(workspace.pending_review_summary["stage"], "waiting_outline_review")
        self.assertEqual(workspace.pending_review_summary["revision_count"], 2)
        self.assertIn("大纲", workspace.pending_review_summary["summary"])
        self.assertNotIn("story_plan", workspace.pending_review_summary)
        self.assertNotIn("chapter_pair", workspace.pending_review_summary)
```

新增 RAG 摘要测试：

```python
def test_workspace_exposes_rag_status_summary_from_context_evidence(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="gpt-5.4",
            tasklog_root=str(Path(tmp_dir) / "tasklog"),
        )
        store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
        engine = FakeEngine(settings)
        model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)

        class ReadyRagService:
            config = type("Config", (), {"enabled": True})()

            def is_ready(self) -> bool:
                return True

            def readiness_error(self) -> str:
                return ""

        service = TaskService(
            store=store,
            engine=engine,
            model_catalog=model_catalog,
            rag_service=ReadyRagService(),
        )
        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一部克制风格的都市悬疑小说",
                model_id="gpt-5.4",
            )
        )
        store.write_context_snapshot(
            task.id,
            stage="drafting",
            snapshot_name="draft-context",
            payload={
                "task_id": task.id,
                "stage": "drafting",
                "cache_hit": False,
                "budget": {"max_input_tokens": 256000},
                "packet": {
                    "estimated_input_tokens": 4096,
                    "references_text": "RAG 参考内容只作为长度证据，不应原样返回。",
                },
                "compressed_references": [{"was_compressed": False, "original_chars": 32, "compressed_chars": 32}],
            },
        )

        workspace = service.get_workspace(task.id)

        self.assertTrue(workspace.rag_status["enabled"])
        self.assertTrue(workspace.rag_status["ready"])
        self.assertTrue(workspace.rag_status["injected"])
        self.assertEqual(workspace.rag_status["last_query_stage"], "drafting")
        self.assertEqual(workspace.rag_status["injection_evidence"], "context_snapshot")
        self.assertNotIn("hits", workspace.rag_status)
        self.assertNotIn("contexts", workspace.rag_status)
        self.assertNotIn("RAG 参考内容", workspace.rag_status.get("summary", ""))
```

新增 not ready / disabled 降级测试：

```python
def test_workspace_exposes_rag_status_when_rag_is_not_ready_or_missing(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        settings = Settings(
            OPENAI_API_KEY="test-key",
            DEFAULT_CHAT_MODEL="gpt-5.4",
            tasklog_root=str(Path(tmp_dir) / "tasklog"),
        )
        store = TaskLogStore(root_dir=str(Path(tmp_dir) / "tasklog"))
        engine = FakeEngine(settings)
        model_catalog = ModelCatalogService(settings=settings, gateway_client=engine.gateway_client)

        class MissingRagService:
            config = type("Config", (), {"enabled": True})()

            def is_ready(self) -> bool:
                return False

            def readiness_error(self) -> str:
                return "小说RAG知识库尚未构建，请先前往设置页完成索引构建。"

        service = TaskService(
            store=store,
            engine=engine,
            model_catalog=model_catalog,
            rag_service=MissingRagService(),
        )
        task = service.create_task(
            TaskCreateRequest(
                mode=TaskMode.SHORT_STORY,
                prompt="写一部克制风格的都市悬疑小说",
                model_id="gpt-5.4",
            )
        )

        workspace = service.get_workspace(task.id)

        self.assertTrue(workspace.rag_status["enabled"])
        self.assertFalse(workspace.rag_status["ready"])
        self.assertIn("尚未构建", workspace.rag_status["last_error"])

        service_without_rag = TaskService(store=store, engine=engine, model_catalog=model_catalog)
        workspace_without_rag = service_without_rag.get_workspace(task.id)
        self.assertFalse(workspace_without_rag.rag_status["enabled"])
        self.assertFalse(workspace_without_rag.rag_status["ready"])
```

- [ ] **Step 2: 跑 service 层失败测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py::TaskServiceWorkspaceTests::test_workspace_exposes_pending_review_summary_without_review_body apps/agent-runtime/tests/test_task_service_workspace.py::TaskServiceWorkspaceTests::test_workspace_exposes_rag_status_summary_from_context_evidence apps/agent-runtime/tests/test_task_service_workspace.py::TaskServiceWorkspaceTests::test_workspace_exposes_rag_status_when_rag_is_not_ready_or_missing -v
```

Expected: FAIL，错误应指向 `WorkspaceResponse` 缺少 `pending_review_summary` / `rag_status`。

- [ ] **Step 3: 写 API 层失败测试**

在 `apps/agent-runtime/tests/test_api_context.py` 新增：

```python
def test_workspace_endpoint_returns_debug_summary_fields(self) -> None:
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
        revision_count=1,
    )
    self.store.set_waiting_review(task.id, review, story_plan)

    response = self.client.get(f"/api/tasks/{task.id}/workspace")

    self.assertEqual(response.status_code, 200)
    payload = response.json()
    self.assertTrue(payload["pending_review_summary"]["present"])
    self.assertEqual(payload["pending_review_summary"]["review_type"], "outline_review")
    self.assertIn("rag_status", payload)
    self.assertIn("enabled", payload["rag_status"])
    self.assertNotIn("story_plan", payload["pending_review_summary"])
```

- [ ] **Step 4: 跑 API 层失败测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_workspace_endpoint_returns_debug_summary_fields -v
```

Expected: FAIL，响应 JSON 缺少新字段。

- [ ] **Step 5: 最小实现 Pydantic 字段**

在 `apps/agent-runtime/app/domain/models.py` 的 `WorkspaceResponse` 中加入：

```python
    pending_review_summary: dict[str, Any] = Field(default_factory=dict)
    rag_status: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 6: 实现 pending review 摘要 helper**

在 `apps/agent-runtime/app/application/task_service/queries.py` 中新增私有方法：

```python
    def _build_pending_review_summary(self, task: TaskRecord) -> dict[str, Any]:
        review = task.pending_review
        if review is None:
            return {
                "present": False,
                "review_type": "",
                "stage": task.current_stage or task.status.value,
                "summary": "当前没有待审核上下文。",
            }

        summary: dict[str, Any] = {
            "present": True,
            "review_type": review.type,
            "stage": task.current_stage or task.status.value,
            "revision_count": review.revision_count,
            "outline_phase": "",
            "summary": review.summary or "当前任务等待人工审核。",
        }
        if review.type == "chapter_pair_review":
            summary["batch_index"] = review.batch_index
            summary["revision_count"] = review.chapter_pair_revision_count
            completed = review.completed_count or 0
            total = review.total_chapters or 0
            chapter_count = len(review.chapter_pair or [])
            summary["summary"] = (
                f"等待章节批次审核（已完成 {completed}/{total}，本批 {chapter_count} 章）。"
                if total
                else f"等待章节批次审核（本批 {chapter_count} 章）。"
            )
        elif review.type == "verification_review":
            summary["revision_count"] = review.verification_revision_count
            summary["summary"] = review.summary or "等待全文验证审核。"
        else:
            outline_batch = review.outline_batch
            if outline_batch is not None:
                summary["outline_phase"] = outline_batch.phase
                summary["batch_index"] = outline_batch.batch_index
                summary["revision_count"] = review.revision_count
                if outline_batch.phase == "chapter_batches":
                    summary["summary"] = (
                        f"等待章节计划审核（已确认 {outline_batch.completed_count}/{outline_batch.total_count} 章）。"
                    )
            else:
                summary["summary"] = review.summary or "等待大纲审核。"
        return summary
```

Implementation note: 该方法不得把 `story_plan`、`chapter_pair`、`verification_report` 放入返回值。

- [ ] **Step 7: 实现 RAG 摘要 helper**

在同一文件新增：

```python
    def _build_rag_status(self, task: TaskRecord, context_status: dict[str, Any]) -> dict[str, Any]:
        rag_service = getattr(self, "rag_service", None)
        enabled = bool(rag_service)
        config = getattr(rag_service, "config", None)
        if config is not None and hasattr(config, "enabled"):
            enabled = bool(config.enabled)

        ready = False
        last_error = ""
        if rag_service is not None:
            try:
                ready = bool(rag_service.is_ready())
            except Exception as exc:  # pragma: no cover - 防御第三方后端异常
                last_error = str(exc)
            if not ready and not last_error:
                try:
                    last_error = str(rag_service.readiness_error())
                except Exception:  # pragma: no cover - 防御第三方后端异常
                    last_error = ""

        last_query_stage = str(context_status.get("stage") or "")
        injected = False
        injection_evidence = ""
        for event in reversed(task.events):
            payload = event.payload if isinstance(event.payload, dict) else {}
            text = " ".join(
                str(item)
                for item in (event.event_type, event.message, payload.get("summary"), payload.get("error"))
                if item
            ).lower()
            if "rag" not in text:
                continue
            if not last_query_stage:
                last_query_stage = event.stage
            if any(token in text for token in ("inject", "injected", "注入", "context")):
                injected = True
                injection_evidence = "event"
            if not last_error and payload.get("error"):
                last_error = str(payload.get("error"))
            break

        if not injected:
            try:
                context_snapshot = self.store.read_json(task.id, "context/drafting/draft-context.json")
            except FileNotFoundError:
                try:
                    context_snapshot = self.store.read_json(task.id, "context/planning/outline-context.json")
                except FileNotFoundError:
                    context_snapshot = {}
            packet = context_snapshot.get("packet") if isinstance(context_snapshot.get("packet"), dict) else {}
            compressed_references = context_snapshot.get("compressed_references")
            if packet.get("references_text") or (isinstance(compressed_references, list) and len(compressed_references) > 0):
                injected = True
                injection_evidence = "context_snapshot"
                if not last_query_stage:
                    last_query_stage = str(context_snapshot.get("stage") or context_status.get("stage") or "")

        if not enabled:
            summary = "RAG 未启用。"
        elif ready:
            summary = "RAG 已启用且索引可用。"
        else:
            summary = last_error or "RAG 已启用但索引尚未就绪。"

        return {
            "enabled": enabled,
            "ready": ready,
            "source": "workspace",
            "summary": summary,
            "last_query_stage": last_query_stage,
            "last_error": last_error,
            "injected": injected,
            "injection_evidence": injection_evidence,
        }
```

Implementation notes:
- 首批允许 `last_query_stage` 为空，前端显示“暂无最近检索证据”；不要新增检索详情 API。
- `context_snapshot` 只用于判断是否存在上下文引用装配，不返回 `references_text` 原文。

- [ ] **Step 8: 接入 `get_workspace()`**

在 `get_workspace()` 中先把上下文字段赋给局部变量，避免重复读取：

```python
        context_status = self._load_context_status(task.id)
        response_cache_status = self._load_response_cache_status(task)
```

在 `WorkspaceResponse(...)` 构造中使用局部变量并加入：

```python
            context_status=context_status,
            response_cache_status=response_cache_status,
            pending_review_summary=self._build_pending_review_summary(task),
            rag_status=self._build_rag_status(task, context_status),
```

- [ ] **Step 9: 跑后端定向测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_api_context.py -v
```

Expected: PASS。

### Task 2: 前端类型与诊断纯函数

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Create: `apps/web/src/features/task-run/debug-diagnostics.mjs`
- Create: `apps/web/src/features/task-run/debug-diagnostics.test.mjs`

- [ ] **Step 1: 更新 TypeScript 类型**

在 `apps/web/src/lib/types.ts` 中新增：

```ts
export interface PendingReviewSummary {
  present: boolean;
  review_type?: string;
  stage?: string;
  batch_index?: number | null;
  revision_count?: number;
  outline_phase?: string;
  summary?: string;
}

export interface RagStatus {
  enabled?: boolean;
  ready?: boolean;
  source?: string;
  summary?: string;
  last_query_stage?: string;
  last_error?: string;
  injected?: boolean;
}
```

并在 `WorkspaceResponse` 中加入：

```ts
  pending_review_summary?: PendingReviewSummary;
  rag_status?: RagStatus;
```

- [ ] **Step 2: 写诊断失败测试**

创建 `apps/web/src/features/task-run/debug-diagnostics.test.mjs`：

```js
import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAgentDebugDiagnostics,
  buildStateCheck,
} from "./debug-diagnostics.mjs";

const baseWorkspace = {
  meta: {
    task_id: "task-1",
    status: "drafting",
    current_stage: "drafting",
    current_unit: "chapter-01",
    progress: 40,
    updated_at: "2026-06-23T08:00:00Z",
    summary: "生成中",
  },
  recent_events: [],
  allowed_actions: [],
  recovery_options: [],
  pending_review_summary: { present: false },
  rag_status: { enabled: true, ready: true, source: "workspace", summary: "RAG 已就绪", injected: false },
  llm_report: {},
};

test("运行中且无冲突时诊断为运行正常", () => {
  const diagnostics = buildAgentDebugDiagnostics(baseWorkspace, { streamState: "已连接事件流" });

  assert.equal(diagnostics.health.status, "running");
  assert.equal(diagnostics.health.label, "运行正常");
  assert.equal(diagnostics.stateCheck.status, "ok");
});

test("等待审核但缺少 pending_review_summary 时状态不一致优先", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    {
      ...baseWorkspace,
      meta: { ...baseWorkspace.meta, status: "waiting_chapter_review", current_stage: "waiting_chapter_review" },
      pending_review_summary: { present: false },
      allowed_actions: ["restart_from_input"],
      recovery_options: [{ action: "restart_from_input", available: true, label: "按原始输入重新开始" }],
    },
    { streamState: "已连接事件流" },
  );

  assert.equal(diagnostics.health.status, "inconsistent");
  assert.equal(diagnostics.stateCheck.conflicts.length, 1);
  assert.equal(diagnostics.stateCheck.conflicts[0].status, "error");
});

test("可恢复异常优先于等待用户", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    {
      ...baseWorkspace,
      meta: { ...baseWorkspace.meta, status: "waiting_manual_action", current_stage: "waiting_manual_action" },
      allowed_actions: ["restart_from_input"],
      recovery_options: [{ action: "restart_from_input", available: true, label: "按原始输入重新开始" }],
    },
    { streamState: "连接失败" },
  );

  assert.equal(diagnostics.health.status, "recoverable");
  assert.equal(diagnostics.connection.status, "error");
});

test("终态任务诊断为已终止", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    { ...baseWorkspace, meta: { ...baseWorkspace.meta, status: "completed", current_stage: "completed", progress: 100 } },
    { streamState: "事件流已正常结束" },
  );

  assert.equal(diagnostics.health.status, "terminal");
});

test("RAG 缺失只影响 RAG 模块，不影响整体健康结论", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    { ...baseWorkspace, rag_status: undefined },
    { streamState: "已连接事件流" },
  );

  assert.equal(diagnostics.health.status, "running");
  assert.equal(diagnostics.rag.status, "unknown");
});

test("状态对账证据不足时不误报异常", () => {
  const check = buildStateCheck({ meta: { status: "waiting_chapter_review" }, recent_events: [] });

  assert.equal(check.status, "unknown");
  assert.equal(check.conflicts.length, 0);
});

test("状态对账识别终态任务仍有运行中 Supervisor 子任务", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    {
      ...baseWorkspace,
      meta: { ...baseWorkspace.meta, status: "completed", current_stage: "completed" },
      supervisor_plan: {
        subtasks: [{ id: "chapter_writing", title: "章节写作", kind: "chapter_writing", status: "running" }],
        dependencies: [],
      },
    },
    { streamState: "任务已完成，事件流已关闭" },
  );

  assert.equal(diagnostics.health.status, "inconsistent");
  assert.equal(diagnostics.stateCheck.conflicts[0].label, "Supervisor 子任务");
});

test("状态对账识别章节进度超过规划章节数", () => {
  const check = buildStateCheck({
    ...baseWorkspace,
    novel_progress: { planned_chapter_count: 3, completed_chapter_count: 5 },
  });

  assert.equal(check.status, "error");
  assert.equal(check.conflicts[0].label, "章节进度");
});

test("LLM 诊断汇总请求、阶段耗时、缓存、重试修复和 JSON 解析失败", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    {
      ...baseWorkspace,
      llm_report: {
        usage_total: { total_tokens: 140 },
        usage_count: 2,
        exchange_count: 3,
        cache_hit_count: 1,
        timing_by_stage: {
          planning: { call_count: 1, total_duration_ms: 1000, retry_count: 1, repair_count: 0 },
          drafting: { call_count: 2, total_duration_ms: 8000, retry_count: 0, repair_count: 1 },
        },
        latest_usage: { model: "gpt-5.4" },
        slowest_step: { stage: "drafting", exchange_label: "chapter-01", duration_ms: 8000 },
        slowest_first_token: { stage: "drafting", exchange_label: "chapter-01", first_token_ms: 1200 },
      },
      recent_events: [
        { event_id: "parse-1", event_type: "model.response.parse_failed", stage: "drafting", message: "JSON 解析失败" },
      ],
    },
    { streamState: "事件流已连接" },
  );

  assert.equal(diagnostics.llm.requestCount, 2);
  assert.equal(diagnostics.llm.exchangeCount, 3);
  assert.equal(diagnostics.llm.cacheHitCount, 1);
  assert.equal(diagnostics.llm.retryCount, 1);
  assert.equal(diagnostics.llm.repairCount, 1);
  assert.equal(diagnostics.llm.jsonParseFailedCount, 1);
  assert.equal(diagnostics.llm.latestModel, "gpt-5.4");
});

test("Agent Trace 摘要包含最近轮次、成功失败数量、评分、问题、警告和裁决", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    {
      ...baseWorkspace,
      auto_review_trace: [
        { __summary__: true, trace_round: 2, overall_score: 72, approved: false, comment: "需要修订" },
        { agent_id: "a1", status: "completed", score: 80, issues: [{ severity: "critical", description: "冲突" }] },
        { agent_id: "a2", status: "failed", warnings: [{ severity: "warning", description: "节奏" }] },
      ],
    },
    { streamState: "事件流已连接" },
  );

  assert.equal(diagnostics.agentTrace.round, 2);
  assert.equal(diagnostics.agentTrace.completedCount, 1);
  assert.equal(diagnostics.agentTrace.failedCount, 1);
  assert.equal(diagnostics.agentTrace.displayScore, 72);
  assert.equal(diagnostics.agentTrace.issueCount, 1);
  assert.equal(diagnostics.agentTrace.warningCount, 1);
  assert.equal(diagnostics.agentTrace.verdict, "未通过");
});

test("终态关闭文案识别为正常终止", () => {
  const diagnostics = buildAgentDebugDiagnostics(baseWorkspace, { streamState: "任务已完成，事件流已关闭" });

  assert.equal(diagnostics.connection.status, "closed");
});
```

- [ ] **Step 3: 跑前端失败测试**

Run:

```bash
npm --prefix apps/web test -- src/features/task-run/debug-diagnostics.test.mjs
```

Expected: FAIL，提示找不到 `debug-diagnostics.mjs` 或导出函数。

- [ ] **Step 4: 创建诊断纯函数最小实现**

创建 `apps/web/src/features/task-run/debug-diagnostics.mjs`，至少导出：

```js
import { getCurrentTraceRound, summarizeTraceRound } from "../task-review/trace-rounds.mjs";

const waitingStatuses = new Set([
  "created",
  "sources_ingested",
  "ready_for_batch",
  "waiting_outline_review",
  "waiting_chapter_review",
  "waiting_verification_review",
]);
const runningStatuses = new Set(["planning", "drafting", "assembling"]);
const terminalStatuses = new Set(["completed", "cancelled", "failed"]);
const reviewStatuses = new Set(["waiting_outline_review", "waiting_chapter_review", "waiting_verification_review"]);

function hasAvailableRecovery(workspace = {}) {
  const actions = Array.isArray(workspace.allowed_actions) ? workspace.allowed_actions : [];
  const options = Array.isArray(workspace.recovery_options) ? workspace.recovery_options : [];
  return actions.some(Boolean) || options.some((item) => item && item.available);
}

function buildConnection(streamState = "") {
  const normalized = String(streamState || "");
  if (normalized.includes("已连接")) return { status: "connected", label: "已连接", summary: normalized };
  if (normalized.includes("正常结束") || normalized.includes("正常终止") || normalized.includes("事件流已关闭") || normalized.includes("任务已结束")) {
    return { status: "closed", label: "正常终止", summary: normalized };
  }
  if (normalized.includes("重连")) return { status: "retrying", label: "重连中", summary: normalized };
  if (normalized.includes("失败") || normalized.includes("错误")) return { status: "error", label: "连接失败", summary: normalized };
  if (normalized.includes("连接")) return { status: "connecting", label: "连接中", summary: normalized };
  return { status: "unknown", label: "未连接", summary: normalized || "未连接事件流" };
}

export function buildStateCheck(workspace = {}) {
  const status = workspace?.meta?.status || "";
  const pending = workspace?.pending_review_summary;
  const hasPendingEvidence = pending && typeof pending.present === "boolean";
  const progress = workspace?.novel_progress || {};
  const supervisorPlan = workspace?.supervisor_plan || null;
  const recentEvents = Array.isArray(workspace?.recent_events) ? workspace.recent_events : [];
  const runningAgentRuns = Array.isArray(workspace?.agent_runs)
    ? workspace.agent_runs.filter((run) => run?.status === "running")
    : [];
  const items = [];
  const conflicts = [];

  function addItem(item) {
    items.push(item);
    if (item.status === "error") conflicts.push(item);
  }

  if (reviewStatuses.has(status)) {
    if (!hasPendingEvidence) {
      addItem({
        label: "待审核上下文",
        status: "unknown",
        summary: "缺少 pending_review_summary，无法确认待审核上下文。",
        evidence: "WorkspaceResponse.pending_review_summary",
      });
      return { status: "unknown", items, conflicts };
    }
    if (!pending.present) {
      addItem({
        label: "待审核上下文",
        status: "error",
        summary: "任务处于等待审核状态，但后端未返回待审核上下文。",
        evidence: "pending_review_summary.present=false",
      });
    } else {
      addItem({
        label: "待审核上下文",
        status: "ok",
        summary: pending.summary || "待审核上下文存在。",
        evidence: `pending_review_summary.review_type=${pending.review_type || ""}`,
      });
    }
  }

  if (typeof progress.planned_chapter_count === "number" && typeof progress.completed_chapter_count === "number") {
    addItem({
      label: "章节进度",
      status: progress.completed_chapter_count > progress.planned_chapter_count ? "error" : "ok",
      summary: `已完成 ${progress.completed_chapter_count}/${progress.planned_chapter_count} 章。`,
      evidence: "WorkspaceResponse.novel_progress",
    });
  }

  const runningSubtasks = Array.isArray(supervisorPlan?.subtasks)
    ? supervisorPlan.subtasks.filter((subtask) => subtask?.status === "running")
    : [];
  if (terminalStatuses.has(status) && (runningSubtasks.length > 0 || runningAgentRuns.length > 0)) {
    addItem({
      label: "Supervisor 子任务",
      status: "error",
      summary: "任务已进入终态，但仍存在运行中的 Supervisor 子任务或 Agent 运行记录。",
      evidence: "WorkspaceResponse.supervisor_plan / WorkspaceResponse.agent_runs",
    });
  } else if (supervisorPlan) {
    addItem({
      label: "Supervisor 子任务",
      status: "ok",
      summary: `子任务 ${supervisorPlan.subtasks?.length || 0} 个，运行中 ${runningSubtasks.length} 个。`,
      evidence: "WorkspaceResponse.supervisor_plan",
    });
  }

  if (status === "waiting_manual_action") {
    addItem({
      label: "恢复契约",
      status: hasAvailableRecovery(workspace) ? "ok" : "warning",
      summary: hasAvailableRecovery(workspace) ? "存在可用恢复动作。" : "任务需要人工处理，但暂无可用恢复动作。",
      evidence: "allowed_actions / recovery_options / recommended_action",
    });
  }

  const latestEvent = recentEvents.at(-1);
  if (latestEvent) {
    const eventStage = latestEvent.stage || "";
    const currentStage = workspace?.meta?.current_stage || "";
    const isHardMismatch = runningStatuses.has(status) && eventStage && currentStage && eventStage !== currentStage;
    addItem({
      label: "最近事件阶段",
      status: isHardMismatch ? "warning" : "ok",
      summary: `最近事件：${eventStage || "unknown"} / ${latestEvent.event_type || "unknown"}`,
      evidence: latestEvent.event_id || latestEvent.event_type || "recent_events[-1]",
    });
  }

  if (conflicts.length > 0) {
      return { status: "error", items, conflicts };
  }

  items.push({
    label: "任务状态",
    status: status ? "ok" : "unknown",
    summary: status ? `当前状态：${status}` : "缺少任务状态。",
    evidence: "WorkspaceResponse.meta.status",
  });
  const hasWarning = items.some((item) => item.status === "warning");
  return {
    status: hasWarning ? "warning" : status ? "ok" : "unknown",
    items,
    conflicts,
  };
}

function buildHealth(workspace, stateCheck) {
  const status = workspace?.meta?.status || "";
  if (stateCheck.conflicts?.some((item) => item.status === "error")) {
    return { status: "inconsistent", label: "状态不一致", severity: "error", action: "查看状态对账与证据链接" };
  }
  if (hasAvailableRecovery(workspace) || status === "waiting_manual_action") {
    return { status: "recoverable", label: "可恢复异常", severity: "warning", action: "打开现有恢复弹窗" };
  }
  if (waitingStatuses.has(status)) {
    return { status: "waiting", label: "等待用户", severity: "info", action: "启动、继续创作或进入审核页" };
  }
  if (terminalStatuses.has(status)) {
    return { status: "terminal", label: "已终止", severity: status === "completed" ? "success" : "warning", action: "查看结果、归档或错误摘要" };
  }
  if (runningStatuses.has(status)) {
    return { status: "running", label: "运行正常", severity: "success", action: "继续观察" };
  }
  return { status: "unknown", label: "证据不足", severity: "info", action: "手动刷新并查看最近事件" };
}

function buildRag(workspace = {}) {
  const rag = workspace.rag_status;
  if (!rag) {
    return { status: "unknown", label: "证据不足", summary: "暂无 RAG 状态摘要。" };
  }
  if (!rag.enabled) return { status: "disabled", label: "未启用", summary: rag.summary || "RAG 未启用。" };
  if (!rag.ready) return { status: "warning", label: "未就绪", summary: rag.last_error || rag.summary || "RAG 尚未就绪。" };
  return {
    status: "ok",
    label: rag.injected ? "已注入" : "已就绪",
    summary: rag.summary || "RAG 已启用且索引可用。",
  };
}

function buildLlm(report = {}, events = []) {
  const usageTotal = report?.usage_total || {};
  const totalTokens = Number(usageTotal.total_tokens || 0);
  const timingByStage = report?.timing_by_stage && typeof report.timing_by_stage === "object" ? report.timing_by_stage : {};
  const stageTimings = Object.entries(timingByStage).map(([stage, bucket]) => ({
    stage,
    callCount: Number(bucket?.call_count || 0),
    totalDurationMs: Number(bucket?.total_duration_ms || 0),
    maxDurationMs: Number(bucket?.max_duration_ms || 0),
    maxFirstTokenMs: Number(bucket?.max_first_token_ms || 0),
    retryCount: Number(bucket?.retry_count || 0),
    repairCount: Number(bucket?.repair_count || 0),
  }));
  const retryCount = stageTimings.reduce((sum, item) => sum + item.retryCount, 0);
  const repairCount = stageTimings.reduce((sum, item) => sum + item.repairCount, 0);
  const jsonParseFailedCount = events.filter((event) => event?.event_type === "model.response.parse_failed").length;
  const latestModel =
    report?.latest_usage?.model ||
    report?.latest_exchange?.model ||
    report?.slowest_step?.model ||
    "";
  return {
    status: Object.keys(report || {}).length ? "ok" : "empty",
    totalTokens,
    requestCount: Number(report?.usage_count || 0),
    exchangeCount: Number(report?.exchange_count || 0),
    cacheHitCount: Number(report?.cache_hit_count || 0),
    retryCount,
    repairCount,
    jsonParseFailedCount,
    latestModel,
    stageTimings,
    summary: totalTokens
      ? `请求 ${Number(report?.usage_count || 0)} 次，累计 token：${totalTokens}`
      : "暂无 LLM usage 数据。",
    slowestStep: report?.slowest_step || {},
    slowestFirstToken: report?.slowest_first_token || {},
  };
}

function buildAgentTrace(workspace = {}) {
  const trace = Array.isArray(workspace.auto_review_trace) ? workspace.auto_review_trace : [];
  const runs = Array.isArray(workspace.agent_runs) ? workspace.agent_runs : [];
  const currentRound = getCurrentTraceRound(trace);
  const roundSummary = summarizeTraceRound(currentRound);
  const issueCount = roundSummary.agentItems.reduce((sum, agent) => sum + (Array.isArray(agent?.issues) ? agent.issues.length : 0), 0);
  const warningCount = roundSummary.agentItems.reduce((sum, agent) => {
    const warnings = Array.isArray(agent?.warnings) ? agent.warnings.length : 0;
    const issueWarnings = Array.isArray(agent?.issues) ? agent.issues.filter((issue) => issue?.severity === "warning").length : 0;
    return sum + warnings + issueWarnings;
  }, 0);
  const approved = roundSummary.summaryEntry?.approved;
  return {
    status: trace.length || runs.length ? "ok" : "empty",
    summary: trace.length || runs.length
      ? `最近第 ${currentRound.round || 0} 轮，完成 ${roundSummary.completedCount}/${roundSummary.trackedAgents.length}，失败 ${roundSummary.failedCount}。`
      : "暂无 Agent 审核轨迹。",
    round: currentRound.summary?.trace_round || currentRound.round || 0,
    completedCount: roundSummary.completedCount,
    failedCount: roundSummary.failedCount,
    displayScore: roundSummary.displayScore,
    issueCount,
    warningCount,
    verdict: approved === true ? "通过" : approved === false ? "未通过" : "暂无裁决",
    comment: roundSummary.summaryEntry?.comment || "",
    runCount: runs.length,
  };
}

function buildEvidenceLinks(workspace = {}) {
  const events = Array.isArray(workspace.recent_events) ? workspace.recent_events : [];
  return events
    .flatMap((event) => [
      event.md_ref ? { label: event.message || event.event_type, path: event.md_ref, type: "md" } : null,
      event.json_ref ? { label: event.message || event.event_type, path: event.json_ref, type: "json" } : null,
    ])
    .filter(Boolean)
    .slice(-8);
}

export function buildAgentDebugDiagnostics(workspace = {}, options = {}) {
  const stateCheck = buildStateCheck(workspace);
  const events = Array.isArray(workspace.recent_events) ? workspace.recent_events : [];
  return {
    health: buildHealth(workspace, stateCheck),
    connection: buildConnection(options.streamState),
    llm: buildLlm(workspace.llm_report || {}, events),
    agentTrace: buildAgentTrace(workspace),
    rag: buildRag(workspace),
    stateCheck,
    evidenceLinks: buildEvidenceLinks(workspace),
  };
}
```

Implementation note: 可在满足测试后继续补充上下文预算、最近事件摘要和更丰富的 Agent Trace 摘要，但不要把 UI 逻辑写入纯函数。

- [ ] **Step 5: 跑诊断单测**

Run:

```bash
npm --prefix apps/web test -- src/features/task-run/debug-diagnostics.test.mjs
```

Expected: PASS。

### Task 3: 前端调试面板 UI

**Files:**
- Create: `apps/web/src/features/task-run/debug-panel.tsx`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`

- [ ] **Step 1: 创建只读 DebugPanel**

创建 `apps/web/src/features/task-run/debug-panel.tsx`：

```tsx
"use client";

import Link from "next/link";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import type { WorkspaceResponse } from "@/lib/types";
import { reviewHref, resultHref } from "@/lib/task-routes";
import { buildAgentDebugDiagnostics } from "./debug-diagnostics.mjs";

type DebugPanelProps = {
  workspace: WorkspaceResponse;
  streamState: string;
  streamPath?: string;
  onRefresh: () => void;
  onOpenRecovery: () => void;
};

const severityMap = {
  success: "success",
  info: "info",
  warning: "warning",
  error: "error",
} as const;

function valueOrEmpty(value: unknown, fallback = "暂无数据") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

export default function DebugPanel({
  workspace,
  streamState,
  streamPath,
  onRefresh,
  onOpenRecovery,
}: DebugPanelProps) {
  const diagnostics = buildAgentDebugDiagnostics(workspace, { streamState });
  const healthSeverity = severityMap[diagnostics.health.severity as keyof typeof severityMap] ?? "info";
  const canReview = [
    "waiting_outline_review",
    "waiting_chapter_review",
    "waiting_verification_review",
  ].includes(workspace.meta.status);

  return (
    <Stack spacing={2}>
      <Alert
        severity={healthSeverity}
        action={
          <Stack direction="row" spacing={1}>
            {diagnostics.health.status === "recoverable" ? (
              <Button color="inherit" size="small" onClick={onOpenRecovery}>
                恢复
              </Button>
            ) : null}
            {canReview ? (
              <Button color="inherit" size="small" component={Link} href={reviewHref(workspace.meta.task_id)}>
                审核
              </Button>
            ) : null}
            {workspace.meta.status === "completed" ? (
              <Button color="inherit" size="small" component={Link} href={resultHref(workspace.meta.task_id)}>
                结果
              </Button>
            ) : null}
            <Button color="inherit" size="small" onClick={onRefresh}>
              刷新
            </Button>
          </Stack>
        }
      >
        <Typography variant="subtitle2">{diagnostics.health.label}</Typography>
        <Typography variant="body2">{diagnostics.health.action}</Typography>
      </Alert>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={1}>
                <Typography variant="subtitle1">实时连接</Typography>
                <Chip size="small" label={diagnostics.connection.label} />
                <Typography variant="body2" color="text.secondary">
                  {diagnostics.connection.summary}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  路径：{streamPath || "未上报"}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={1}>
                <Typography variant="subtitle1">LLM 诊断</Typography>
                <Typography variant="body2">{diagnostics.llm.summary}</Typography>
                <Typography variant="caption" color="text.secondary">
                  请求：{diagnostics.llm.requestCount}
                  {" · "}
                  Exchange：{diagnostics.llm.exchangeCount}
                  {" · "}
                  缓存命中：{diagnostics.llm.cacheHitCount}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  重试：{diagnostics.llm.retryCount}
                  {" · "}
                  修复：{diagnostics.llm.repairCount}
                  {" · "}
                  JSON 解析失败：{diagnostics.llm.jsonParseFailedCount}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  最近模型：{diagnostics.llm.latestModel || "未上报"}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  最慢步骤：{valueOrEmpty(diagnostics.llm.slowestStep?.exchange_label)}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  首 token 最慢：{valueOrEmpty(diagnostics.llm.slowestFirstToken?.exchange_label)}
                </Typography>
                {diagnostics.llm.stageTimings?.slice(0, 3).map((stage) => (
                  <Typography key={stage.stage} variant="caption" color="text.secondary">
                    {stage.stage}：{Math.round(stage.totalDurationMs)}ms / {stage.callCount} 次
                  </Typography>
                ))}
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={1}>
                <Typography variant="subtitle1">Agent Trace</Typography>
                <Typography variant="body2">{diagnostics.agentTrace.summary}</Typography>
                <Typography variant="caption" color="text.secondary">
                  最近轮次：{diagnostics.agentTrace.round}
                  {" · "}
                  评分：{diagnostics.agentTrace.displayScore}
                  {" · "}
                  裁决：{diagnostics.agentTrace.verdict}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  问题：{diagnostics.agentTrace.issueCount}
                  {" · "}
                  警告：{diagnostics.agentTrace.warningCount}
                  {" · "}
                  Agent 运行记录：{diagnostics.agentTrace.runCount}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={1}>
                <Typography variant="subtitle1">上下文 / RAG</Typography>
                <Typography variant="body2">{diagnostics.rag.summary}</Typography>
                <Typography variant="caption" color="text.secondary">
                  上下文阶段：{workspace.context_status?.stage || workspace.meta.current_stage || "未上报"}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  响应缓存：{workspace.response_cache_status?.summary || "暂无独立状态"}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ mb: 1 }}>
            状态对账
          </Typography>
          <List dense>
            {diagnostics.stateCheck.items.map((item) => (
              <ListItem key={`${item.label}-${item.evidence}`} disableGutters>
                <ListItemText
                  primary={
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography>{item.label}</Typography>
                      <Chip size="small" label={item.status} />
                    </Stack>
                  }
                  secondary={`${item.summary} · 证据：${item.evidence}`}
                />
              </ListItem>
            ))}
          </List>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ mb: 1 }}>
            最近事件与证据链接
          </Typography>
          <List dense>
            {workspace.recent_events?.slice(-8).reverse().map((event) => (
              <ListItem key={event.event_id} disableGutters alignItems="flex-start">
                <ListItemText
                  primary={event.message || event.event_type}
                  secondary={[
                    `${event.stage || "unknown"} · ${event.event_type} · ${event.created_at || ""}`,
                    event.md_ref ? `Markdown：${event.md_ref}` : "",
                    event.json_ref ? `JSON：${event.json_ref}` : "",
                  ].filter(Boolean).join("\n")}
                  secondaryTypographyProps={{ sx: { whiteSpace: "pre-line" } }}
                />
              </ListItem>
            ))}
          </List>
          <Divider sx={{ my: 1 }} />
          <Typography variant="caption" color="text.secondary">
            默认只展示引用与摘要，不展开完整 prompt、raw response 或正文。
          </Typography>
        </CardContent>
      </Card>
    </Stack>
  );
}
```

Implementation notes:
- 使用 `Card variant="outlined"` 作为模块边界，不要把调试页放进多层嵌套卡片。
- 所有文案保持中文。
- `onOpenRecovery` 只打开现有恢复弹窗，不直接执行恢复动作。

- [ ] **Step 2: 接入 TaskRunClient import**

在 `apps/web/src/features/task-run/task-run-client.tsx` 增加：

```tsx
import DebugPanel from "@/features/task-run/debug-panel";
```

- [ ] **Step 3: 跟踪当前事件流路径**

在 `TaskRunClient` state 区域新增：

```tsx
const [streamPath, setStreamPath] = useState("");
```

在 SSE 连接成功使用某个候选路径时调用：

```tsx
setStreamPath(path);
```

如果当前代码没有集中暴露 path，首批可传 `streamPathCandidates(resolvedTaskId)[0]`，不要重构 SSE 逻辑。

- [ ] **Step 4: 增加第 5 个 Tab 与展开状态**

新增 state：

```tsx
const [tab4Expanded, setTab4Expanded] = useState(true);
```

在 `<Tabs>` 中增加：

```tsx
<Tab label="调试" />
```

在 expand icon 区域增加：

```tsx
{activeTab === 4 && (
  <Tooltip title={tab4Expanded ? "收起调试" : "展开调试"}>
    <IconButton
      size="small"
      onClick={() => setTab4Expanded((prev) => !prev)}
      sx={{ mr: 1, transform: tab4Expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
    >
      <ExpandIcon />
    </IconButton>
  </Tooltip>
)}
```

- [ ] **Step 5: 渲染调试面板**

在 Tab 内容区域增加：

```tsx
{/* Tab 4: 调试 */}
{activeTab === 4 && (
  <Collapse in={tab4Expanded}>
    <DebugPanel
      workspace={workspace}
      streamState={streamState}
      streamPath={streamPath || (resolvedTaskId ? streamPathCandidates(resolvedTaskId)[0] : "")}
      onRefresh={() => void refreshWorkspace()}
      onOpenRecovery={handleOpenRecoveryDialog}
    />
  </Collapse>
)}
```

- [ ] **Step 6: 跑前端测试**

Run:

```bash
npm --prefix apps/web test
```

Expected: PASS。

- [ ] **Step 7: 跑前端 lint/build**

Run:

```bash
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

Expected: PASS。若 lint 对 `.mjs` 导入类型或 MUI Grid 有意见，按现有项目风格调整，不引入新依赖。

### Task 4: 后端与接口回归

**Files:**
- No new files expected.

- [ ] **Step 1: 跑后端 workspace 相关测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_api_context.py -v
```

Expected: PASS。

- [ ] **Step 2: 跑后端 lint**

Run:

```bash
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

Expected: PASS。

- [ ] **Step 3: 运行接口 smoke**

优先使用项目已有技能 `api-full-test` 或 `project-interface-smoke`。至少覆盖：

```bash
uv run --project apps/agent-runtime python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后验证：

```bash
curl -s http://127.0.0.1:8000/api/tasks/<task_id>/workspace
curl -N http://127.0.0.1:8000/api/tasks/<task_id>/events/stream
```

Expected:
- workspace JSON 包含 `pending_review_summary` 与 `rag_status`。
- SSE 正常返回事件或终态关闭；终态关闭不在 UI 中显示为异常断线。

### Task 5: 本地页面验证与记录

**Files:**
- Modify: `worklog/active/功能开发/20260623-01-AgentProject功能补充方向分析.md`

- [ ] **Step 1: 启动前端本地服务**

Run:

```bash
npm --prefix apps/web run dev
```

Expected: Next.js dev server 可访问。若 3000 已占用，使用 Next 自动分配端口或手动换端口。

- [ ] **Step 2: 手动验证任务工作台**

在浏览器打开：

```text
http://localhost:3000/tasks/<task_id>
```

或项目当前实际任务工作台路由。

Expected:
- 页面存在“调试”标签。
- 切换到“调试”后看到七个模块。
- 空数据不崩溃：LLM 空、Agent Trace 空、RAG unknown 都显示中文空态。
- 点击“刷新”只刷新 workspace。
- 点击“恢复”只打开现有恢复弹窗，不直接执行恢复。
- 证据链接只显示路径和摘要，不展开正文或 prompt。

- [ ] **Step 3: 更新 worklog 验证结果**

在当前问题文档追加：

```markdown
## Agent 运行调试中心实施验证

- 后端测试：
- 前端测试：
- 构建与 lint：
- 本地页面：
- 已知限制：
  - 首批不提供全局 `/debug`。
  - 首批不提供事件分页或完整日志浏览器。
  - 首批 RAG 最近检索失败依赖已有事件，缺少事件时降级为证据不足。
```

### Task 6: 收口准备

**Files:**
- Modify: `worklog/active/功能开发/20260623-01-AgentProject功能补充方向分析.md`

- [ ] **Step 1: 汇总变更**

Run:

```bash
git status --short
git diff --stat
```

Expected: 只包含本任务相关文件。若出现无关用户改动，不回滚，最终说明中标注未触碰。

- [ ] **Step 2: 暂不归档**

按 AGENTS.md，只有用户明确同意收口后才允许：
- `worklog/active/...` 移到 `worklog/archive/...`
- 更新 `worklog/index.md`
- 更新 `worklog/history.md`
- 再提交

因此实现完成后先向用户报告验证结果并询问是否收口归档+提交。

## 验收清单

- 后端 `WorkspaceResponse` 返回 `pending_review_summary` 和 `rag_status`。
- 新字段不包含完整 prompt、raw response、待审核正文、RAG 命中文本或完整上下文。
- 调试 Tab 在现有任务工作台内，不新增 `/debug`。
- 诊断优先级满足：状态不一致 > 可恢复异常 > 等待用户 > 已终止 > 运行正常 > 证据不足。
- SSE 连接状态只影响实时连接模块，不单独制造状态不一致。
- 前端空字段降级稳定，不因 `llm_report`、`auto_review_trace`、`rag_status` 缺失而崩溃。
- `npm --prefix apps/web test`、`npm --prefix apps/web run build`、后端 workspace 相关 pytest 通过。
