# 工作台壳层与 Gateway prompt cache 日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让项目工作台接入统一 `ProjectShell + StageNav`，并补齐 Gateway prompt cache 设置读取失败 warning。

**Architecture:** 前端新增纯状态映射函数，`TaskRunClient` 只替换页面壳层，不改任务动作、事件流、恢复或 Tab 内容。后端只在 `_provider_prompt_cache_kwargs()` 的 `get_settings()` 异常分支补 warning，保持返回 `{}` 的降级语义。

**Tech Stack:** Next.js 14 App Router, React 18, MUI v5, Playwright, Node test runner, Python 3.11, unittest/pytest, ruff

---

## 执行边界

- 不改 `/p/[projectId]` 路由、静态导出壳或 pathname 解析。
- 不改任务动作 API、payload、SSE fallback 路径、恢复对话框或 Tab 内容。
- 不拆 `TaskRunClient` 大组件，不清理 test-only 组件。
- 不改 Gateway prompt cache 成功路径和 prompt cache 参数格式。
- 当前未发现 `*/src/Cargo.toml`，本轮不执行 Cargo patch 版本递增。
- 已用 Context7 确认 MUI v5 `Container maxWidth`、`Stack` 响应式属性、`minWidth: 0` 用法，以及 Next.js App Router client hook/Suspense 约束。

## Task 1: 工作台 StageNav 映射红灯测试

**Files:**
- Modify: `apps/web/src/features/task-run/task-run-state.test.mjs`
- Modify: `apps/web/src/features/task-run/task-run-state.mjs`

- [x] **Step 1: 写状态到 StageNav 的失败测试**

在 `task-run-state.test.mjs` 中导入 `resolveWorkspaceStageNav`，断言：

- `created` / `sources_ingested` activeStep 为 0。
- `planning` / `waiting_outline_review` activeStep 为 1。
- `waiting_chapter_review` / `waiting_verification_review` / `waiting_manual_action` activeStep 为 2。
- `ready_for_batch` / `drafting` / `assembling` activeStep 为 3。
- `completed` activeStep 为 4。
- 返回 `stages` 长度为 5，label 包含“创建”“规划”“审核”“创作”“完成”。

Run:

```bash
npm --prefix apps/web test -- src/features/task-run/task-run-state.test.mjs
```

Expected: FAIL，因为函数尚未导出。

- [x] **Step 2: 实现最小映射函数**

在 `task-run-state.mjs` 中新增：

```js
export function resolveWorkspaceStageNav(status = "") {
  const stages = [
    { label: "创建", description: "素材与任务创建" },
    { label: "规划", description: "大纲与章节计划" },
    { label: "审核", description: "人工确认与修订" },
    { label: "创作", description: "正文生成与整理" },
    { label: "完成", description: "结果归档" },
  ];
  const activeStepByStatus = {
    created: 0,
    sources_ingested: 0,
    planning: 1,
    waiting_outline_review: 1,
    waiting_chapter_review: 2,
    waiting_verification_review: 2,
    waiting_manual_action: 2,
    ready_for_batch: 3,
    drafting: 3,
    assembling: 3,
    completed: 4,
    failed: 2,
    cancelled: 2,
  };
  return { stages, activeStep: activeStepByStatus[status] ?? 0 };
}
```

Run 同上。Expected: PASS。

## Task 2: 工作台 ProjectShell E2E 红灯与实现

**Files:**
- Modify: `apps/web/e2e/task-state-branches.spec.ts`
- Modify: `apps/web/e2e/task-workspace-actions.spec.ts`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
- Modify: `apps/web/src/components/project-shell.tsx`

- [x] **Step 1: 状态分支 E2E 增加壳层断言**

在 `task-state-branches.spec.ts` 每个状态分支中断言：

- `project-shell` 可见。
- `stage-nav` 可见。
- `stage-nav` 当前项存在：`locator('[data-stage-state="current"]')` 可见。

Run:

```bash
npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium
```

Expected: FAIL，因为工作台尚未接入 `ProjectShell` / `StageNav`。

- [x] **Step 2: 增加移动端无横向滚动测试**

在 `task-state-branches.spec.ts` 新增 390px viewport 用例：

- mock `ready_for_batch` 或 `waiting_manual_action` workspace，并覆盖标题缺失时长不可断任务 ID 回退路径。
- 访问 `/p/{taskId}`。
- 断言 `project-shell` 可见。
- 断言 `document.documentElement.scrollWidth <= clientWidth`。
- 断言“调试” Tab 或关键动作按钮可见。

Run 同上。Expected: FAIL。

- [x] **Step 3: TaskRunClient 接入 ProjectShell 和 StageNav**

修改 `task-run-client.tsx`：

- 引入 `ProjectShell`、`StageNav`、`resolveWorkspaceStageNav`。
- 在 `workspace` 已加载分支中计算 `workspaceStageNav = resolveWorkspaceStageNav(workspace.meta.status)`。
- 用 `ProjectShell` 替换外层 `Container`。
- breadcrumbs：`首页` -> 当前任务标题或 ID。
- actions：保留状态 Chip。
- metaItems：任务 ID、创作模型、审核模型。
- stageNav：`<StageNav stages={workspaceStageNav.stages} activeStep={workspaceStageNav.activeStep} />`。
- 原 `Stack spacing={3}` 保留为 `ProjectShell` children；删除旧顶部 `Breadcrumbs + Chip`。

Run:

```bash
npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium
```

Expected: PASS。

- [x] **Step 4: 动作分支回归**

Run:

```bash
npm --prefix apps/web run test:e2e -- task-workspace-actions.spec.ts --project=chromium
```

Expected: PASS，证明壳层替换没有破坏 run/continue/cancel/review/result/delete。

## Task 3: Gateway prompt cache warning 覆盖

**Files:**
- Modify: `apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py`
- Modify: `apps/agent-runtime/app/llm/gateway_client.py`

- [x] **Step 1: 写 get_settings 异常 warning 失败测试**

在 `SettingsAndGatewayFailFastTests` 中新增测试：

- 使用 `unittest.mock.patch("app.settings.config.get_settings", side_effect=RuntimeError("settings unavailable"))`。
- 构造 `OpenAICompatibleGatewayClient(default_protocol="anthropic")`。
- 调用 `client._provider_prompt_cache_kwargs(AnthropicAdapter())`。
- 断言返回 `{}`。
- `assertLogs("app.llm.gateway_client", level="WARNING")` 包含 `读取 provider prompt cache 设置失败`。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py::SettingsAndGatewayFailFastTests::test_prompt_cache_settings_failure_logs_warning_and_disables_prompt_cache -q
```

Expected: FAIL，因为当前无 warning。

- [x] **Step 2: 补 warning 实现**

在 `gateway_client.py` 中 `_provider_prompt_cache_kwargs()` 的 `except Exception as exc` 分支记录：

```python
logger.warning("读取 provider prompt cache 设置失败: %s", exc)
```

保持返回 `{}`。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

Expected: PASS。

## Task 4: 汇总验证与 worklog

**Files:**
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- Modify: `worklog/index.md`

- [x] **Step 1: 更新 active worklog**

记录本批工作台壳层、Gateway warning 的实施结果、验证结果和剩余事项。两个 active 若仍未全部完成，保持 active，不归档。

- [x] **Step 2: 前端汇总验证**

Run:

```bash
npm --prefix apps/web test -- src/features/task-run/task-run-state.test.mjs src/components/stage-nav.test.mjs
npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium
npm --prefix apps/web run test:e2e -- task-workspace-actions.spec.ts --project=chromium
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

- [x] **Step 3: 后端汇总验证**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
```

- [x] **Step 4: 扩展 E2E**

若局部验证通过，再跑：

```bash
npm --prefix apps/web run test:e2e
```

- [x] **Step 5: 提交前门禁**

提交前执行：

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

确认 `.superpowers/brainstorm/` 未暂存后提交。两个 active 未全部完成时不归档。

## Actual Verification

- `npm --prefix apps/web test -- src/features/task-run/task-run-state.test.mjs`：14 passed；红灯阶段先因缺少 `resolveWorkspaceStageNav` 导出失败。
- `npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium`：15 passed；红灯阶段先因缺少 `project-shell` 失败。
- `npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium`：长任务 ID 移动端红灯阶段曾失败为 `scrollWidth=622`，修复 `ProjectShell` 面包屑断词后 15 passed。
- `npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium`：9 passed。
- `npm --prefix apps/web run test:e2e -- task-workspace-actions.spec.ts --project=chromium`：5 passed。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py::SettingsAndGatewayFailFastTests::test_prompt_cache_settings_failure_logs_warning_and_disables_prompt_cache -q`：1 passed；红灯阶段先因无 warning 失败。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py -q`：24 passed。
- `npm --prefix apps/web test -- src/features/task-run/task-run-state.test.mjs src/components/stage-nav.test.mjs`：17 passed。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：通过。
- `npm --prefix apps/web test`：112 passed。
- `npm --prefix apps/web run lint`：通过。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q`：379 passed，1 skipped，2 warnings，4 subtests passed。
- `npm --prefix apps/web run build`：通过，仅保留既有 `metadataBase` 警告。
- `npm --prefix apps/web run test:e2e`：104 passed，最终轮次覆盖长任务 ID 移动端工作台用例。
