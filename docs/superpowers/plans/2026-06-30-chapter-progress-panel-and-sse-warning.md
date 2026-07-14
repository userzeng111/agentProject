# 工作台章节进度面板与 SSE Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 拆出工作台章节进度面板并补 SSE 终态检查异常 warning，同时保持前后端行为语义不变。

**Architecture:** 前端新增一个纯展示 client 组件承接章节列表与正文弹窗，`TaskRunClient` 保留数据获取和状态。后端只在 SSE 循环内新增一次性 warning 标记，异常后继续走原有 queue/keep-alive 流程。

**Tech Stack:** Next.js 14 App Router、React、MUI、Playwright、FastAPI、Starlette StreamingResponse、Python unittest。

---

### Task 1: 前端章节面板红灯

**Files:**
- Modify: `apps/web/e2e/task-state-branches.spec.ts`
- Modify: `apps/web/e2e/helpers/fixtures.ts`

- [x] **Step 1: 写失败 E2E**

新增用例：移动端 `waiting_chapter_review` workspace 带 `chapter.saved` 事件，`/chapters` 返回长标题章节正文；点击“章节进度”Tab，断言面板 test id、章节按钮 aria name、正文弹窗、关闭按钮和无横向滚动。

- [x] **Step 2: 运行红灯**

Run: `npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium`

Expected: FAIL，因为当前没有 `chapter-progress-panel` 稳定定位，关闭按钮也没有可访问名称。

### Task 2: 前端最小实现

**Files:**
- Create: `apps/web/src/features/task-run/chapter-progress-panel.tsx`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`

- [x] **Step 1: 新增 `ChapterProgressPanel`**

组件接收章节进度、展开状态、选中章节、弹窗状态和回调，渲染列表、进度条、空态与正文弹窗。

- [x] **Step 2: 接入 `TaskRunClient`**

删除内嵌章节 Tab JSX 与内嵌 Dialog，改为调用 `ChapterProgressPanel`，保留 `handleChapterClick()` 逻辑。

- [x] **Step 3: 运行绿灯**

Run: `npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium`

Expected: PASS。

### Task 3: 后端 SSE warning 红灯

**Files:**
- Modify: `apps/agent-runtime/tests/test_api_context.py`

- [x] **Step 1: 写失败 API 测试**

新增 fake task service：`store.get()` 抛异常，queue 预置 `task.completed`。断言 SSE 响应仍含 `snapshot`、`task.event`、`task.done`，并捕获 `app.api.routes` warning。

- [x] **Step 2: 运行红灯**

Run: `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_task_event_stream_warns_once_when_terminal_status_check_fails -q`

Expected: FAIL，因为当前异常被静默吞掉。

### Task 4: 后端最小实现

**Files:**
- Modify: `apps/agent-runtime/app/api/routes.py`

- [x] **Step 1: 增加一次性 warning**

在 `event_stream()` 内声明 `terminal_check_warning_logged = False`。`store.get()` 异常时，如果尚未记录，则 `logger.warning("任务事件流终态检查失败 task_id=%s", task_id, exc_info=True)` 并置 true。

- [x] **Step 2: 运行绿灯**

Run: `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_task_event_stream_warns_once_when_terminal_status_check_fails -q`

Expected: PASS。

### Task 5: 验证与审查

**Files:**
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- Modify: `worklog/index.md`

- [x] **Step 1: 局部验证**

Run:

```bash
npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_task_event_stream_warns_once_when_terminal_status_check_fails -q
```

- [x] **Step 2: 必要全量验证**

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
```

视 E2E 风险补跑 `npm --prefix apps/web run test:e2e`。

- [x] **Step 3: 只读代码审查**

派发 subagent 审查前端组件拆分、SSE warning 是否保持语义、测试是否覆盖回归。

- [x] **Step 4: 更新 worklog 与提交**

记录实施和验证结果；active 未全部完成，不归档。按提交门禁核对 `pwd`、`git rev-parse --show-toplevel`、`git remote -v`、`git status --short` 后提交。
