# 审核页分屏与 RAG 工作区日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成审核页桌面左右分屏、RAG workspace 异常 warning 覆盖，并清理未使用的主题初始化 helper。

**Architecture:** 前端在 `TaskReviewClient` 内新增本地 `ReviewSplitLayout`，只重排三类审核分支，不改审核 API 和状态流；`ProjectShell` 增加默认不变的 `maxWidth` prop。后端只给 `_build_rag_status()` 异常降级补 warning 与 characterization tests。主题 helper 清理仅删除未使用导出和旧测试断言。

**Tech Stack:** Next.js 14 App Router, React 18, MUI v5, Playwright, Node test runner, Python 3.11, unittest/pytest, ruff

---

## 执行边界

- 不改 `/review?id=` 路由。
- 不改审核接口、恢复接口、LangGraph 状态机、结果页和归档页。
- 不拆 `AgentTracePanel` 统计逻辑。
- 不做全站暗色模式、移动端底部 Tab 或 `TaskRunClient` 大拆分。
- 不清理 `TaskLogStore` supervisor helper 和 legacy 模型验证流式路由。
- 已用 Context7 确认 MUI v5 `sx` 响应式 CSS grid 与 Next.js App Router client hook/Suspense 用法。
- 当前未发现 `src/Cargo.toml`，本轮不执行 Cargo patch 版本递增。

## Task 1: 审核页分屏失败 E2E

**Files:**
- Modify: `apps/web/e2e/review-result-archive.spec.ts`

- [x] **Step 1: 大纲审核用例增加分屏断言**

在“审核页大纲分支展示审核操作”中增加：

- `review-split-layout` 可见。
- `review-main` 可见。
- `review-aside` 可见。
- 桌面端 bounding box 中 `aside.x > main.x + main.width * 0.5`。

Run:

```bash
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: FAIL，因为当前没有这些 test id，也没有分屏布局。

- [x] **Step 2: 章节/验证分支增加 aside 断言**

在章节与验证分支中断言：

- `review-aside` 可见。
- `review-aside` 包含“审核操作”。
- `review-aside` 包含 label “审核意见”。

Run 同上。Expected: FAIL。

- [x] **Step 3: 新增移动端无横向滚动测试**

390px 宽访问 `/review/?id=task_review_fixture`，断言：

- `review-split-layout` 可见。
- `document.documentElement.scrollWidth <= clientWidth`。
- `review-aside` 中审核意见和通过按钮可见。

Run 同上。Expected: FAIL。

## Task 2: 审核页分屏实现

**Files:**
- Modify: `apps/web/src/components/project-shell.tsx`
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`

- [x] **Step 1: ProjectShell 增加 maxWidth prop**

增加可选 `maxWidth?: "xs" | "sm" | "md" | "lg" | "xl" | false`，默认 `md`，传给 `Container`。

- [x] **Step 2: 新增 ReviewSplitLayout**

在 `task-review-client.tsx` 内新增本地组件：

- `data-testid="review-split-layout"`。
- `Box` CSS grid，`gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 1fr) minmax(340px, 400px)" }`。
- `review-main` 和 `review-aside` 均 `minWidth: 0`。
- aside 内层桌面端 `position: "sticky"`，`top: 24`，移动端 `position: "static"`。

- [x] **Step 3: 重排 OutlineReview**

左侧保留标题/chips、大纲材料、章节计划、回滚；右侧放 Agent 追踪、错误提示、审核操作卡。

- [x] **Step 4: 重排 ChapterPairReview**

左侧保留标题/chips、进度、审核摘要、章节正文；右侧放 Agent 追踪、错误提示、审核操作卡。

- [x] **Step 5: 重排 VerificationReview**

左侧保留标题/chips、验证摘要、问题列表；右侧放 Agent 追踪、错误提示、审核操作卡。

- [x] **Step 6: 审核页 ProjectShell 传 maxWidth=\"lg\"**

只改审核页，其他 `ProjectShell` 使用方默认不变。

Run:

```bash
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: PASS。

## Task 3: RAG workspace warning 覆盖

**Files:**
- Modify: `apps/agent-runtime/tests/test_task_service_workspace.py`
- Modify: `apps/agent-runtime/app/application/task_service/queries.py`

- [x] **Step 1: 写 is_ready 异常 warning 测试**

构造 `BrokenReadyRagService.is_ready()` 抛 `RuntimeError("rag backend down")`，调用 `service.get_workspace(task.id)`，断言：

- `workspace.rag_status["enabled"] is True`。
- `workspace.rag_status["ready"] is False`。
- `workspace.rag_status["last_error"]` 包含 `rag backend down`。
- `assertLogs("app.application.task_service.queries", level="WARNING")` 包含 `读取 RAG 工作区就绪状态失败`。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py::TaskServiceWorkspaceTests::test_workspace_rag_status_warns_when_readiness_check_fails -q
```

Expected: FAIL，因为当前没有 warning。

- [x] **Step 2: 写 readiness_error 异常 warning 测试**

构造 `is_ready()` 返回 `False`，`readiness_error()` 抛 `RuntimeError("rag status missing")`，断言 warning 和 `last_error`。

Run 对应单测。Expected: FAIL。

- [x] **Step 3: 补最小 warning 实现**

在 `_build_rag_status()` 两个异常分支记录 warning，保持返回语义不变。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py -q
```

Expected: PASS。

## Task 4: 清理 getInitialMode

**Files:**
- Modify: `apps/web/src/lib/theme-mode.ts`
- Modify: `apps/web/src/lib/theme-mode.test.ts`

- [x] **Step 1: 改测试为导出面断言**

删除 localStorage/window mock，断言模块不再暴露 `getInitialMode`，仍暴露 `STORAGE_KEY === "theme-mode"`。

Run:

```bash
npm --prefix apps/web test -- src/lib/theme-mode.test.ts
```

Expected: FAIL，因为当前仍导出 `getInitialMode`。

- [x] **Step 2: 删除 getInitialMode 导出**

保留：

```ts
export type ThemeMode = "light" | "dark" | "system";
export const STORAGE_KEY = "theme-mode";
```

Run 同上。Expected: PASS。

## Task 5: 汇总验证与 worklog

**Files:**
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- Modify: `worklog/index.md`

- [x] **Step 1: 更新 active worklog**

记录本批实施结果、验证结果和剩余事项。两个 active 若仍未全部完成，保持 active，不归档。

- [x] **Step 2: 前端汇总验证**

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

- [x] **Step 3: 后端汇总验证**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

- [x] **Step 4: 扩展验证**

若相关验证通过，再跑：

```bash
npm --prefix apps/web run test:e2e
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
```

- [x] **Step 5: 提交前门禁**

提交前执行：

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

确认没有暂存 `.superpowers/` 后提交。两个 active 未全部完成时不归档。

## Actual Verification

- 红灯确认：
  - RAG workspace 两个 warning 新测试在实现前失败，符合预期。
  - `theme-mode` 导出面测试在删除 `getInitialMode()` 前失败，符合预期。
  - 审核页分屏 E2E 在实现前失败，符合预期。
- 实施后局部验证：
  - `npm --prefix apps/web test -- src/lib/theme-mode.test.ts`：通过。
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py::TaskServiceWorkspaceTests::test_workspace_rag_status_warns_when_readiness_check_fails apps/agent-runtime/tests/test_task_service_workspace.py::TaskServiceWorkspaceTests::test_workspace_rag_status_warns_when_readiness_error_fails -q`：2 passed。
  - `npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium`：9 passed。
- 汇总验证：
  - `npm --prefix apps/web test`：111 passed。
  - `npm --prefix apps/web run lint`：通过。
  - `npm --prefix apps/web run build`：通过，仅保留既有 `metadataBase` 警告。
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py -q`：24 passed。
  - `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：通过。
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q`：378 passed，1 skipped，2 warnings，4 subtests passed。
- 扩展 E2E：
  - 首次 `npm --prefix apps/web run test:e2e` 暴露移动端项目误跑桌面位置断言，修正为仅桌面 `chromium` 校验 `aside.x`。
  - `npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts`：18 passed。
  - 重新运行 `npm --prefix apps/web run test:e2e`：102 passed。
