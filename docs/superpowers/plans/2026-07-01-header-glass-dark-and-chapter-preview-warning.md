# 导航玻璃态暗色与章节预览 warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 精调全局导航/玻璃态暗色显示，并补章节预览读取损坏章节文件时的 warning 覆盖。

**Architecture:** 前端保持 `AppHeader` 与 `WorkflowOverviewCard` 组件边界，用 MUI theme mode 派生暗色背景和边框；全局 `.glass-card` 只提供系统暗色兜底。后端只在 `TaskService.get_current_chapters()` 的损坏文件降级分支补 warning，不改变返回结构。

**Tech Stack:** Next.js 14、React 18、MUI 5 `sx`/theme、Playwright、FastAPI、pytest、ruff。

---

### Task 1: 前端暗色红灯

**Files:**
- Modify: `apps/web/e2e/home-create.spec.ts`
- Modify: `apps/web/e2e/task-state-branches.spec.ts`

- [x] **Step 1: 写首页 header 暗色红灯**

在首页移动端用例中设置：

```ts
await page.addInitScript(() => {
  window.localStorage.setItem("theme-mode", "dark");
});
```

并断言：

- `page.getByTestId("app-header")` 可见。
- header 背景不是旧浅色：解析 `rgba?()`，要求 alpha > 0.1 且 luminance < 128。
- 页面无横向滚动。

- [x] **Step 2: 运行首页红灯**

Run:

```bash
npm --prefix apps/web run test:e2e -- home-create.spec.ts --project=chromium
```

Expected: FAIL，因为当前 `AppHeader` 没有 `data-testid="app-header"`，且背景仍是旧浅色。

- [x] **Step 3: 写工作流玻璃卡片暗色红灯**

扩展 `task-state-branches.spec.ts` 的暗色工作流图谱用例，断言：

- `workflow-overview-card` 背景不是旧浅色，使用 alpha/luminance 判断。
- 页面无横向滚动保持不变。

- [x] **Step 4: 运行工作台红灯**

Run:

```bash
npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium
```

Expected: FAIL，因为 `.glass-card` 当前仍固定浅色变量。

### Task 2: 前端暗色实现

**Files:**
- Modify: `apps/web/src/components/app-header.tsx`
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/src/features/task-run/workflow-overview-card.tsx`

- [x] **Step 1: AppHeader 主题化**

- 给 `AppBar` 加 `data-testid="app-header"`。
- 将 `background`、`borderBottom`、active/hover 背景改为 `sx` callback，按 `theme.palette.mode` 派生。
- 保留现有导航链接、移动端 aria-label 和路由判断。

- [x] **Step 2: glass-card 暗色兜底**

- 在 `globals.css` 增加 `@media (prefers-color-scheme: dark)` 下的 `--glass-bg` 与 `--glass-border`。
- 不改变 light 默认变量。

- [x] **Step 3: WorkflowOverviewCard 使用 theme mode 回补**

给 `Card className="glass-card"` 增加 `sx` callback：

- light 模式保持接近现有玻璃态。
- dark 模式使用低亮度半透明背景与暗色边框。
- 保留 `data-testid="workflow-overview-card"`。

- [x] **Step 4: 跑前端绿灯**

Run:

```bash
npm --prefix apps/web run test:e2e -- home-create.spec.ts task-state-branches.spec.ts --project=chromium
```

Expected: PASS。

### Task 3: 后端 warning 红灯与实现

**Files:**
- Modify: `apps/agent-runtime/tests/test_recovery_chapter_progress.py`
- Modify: `apps/agent-runtime/app/application/task_service/continuation.py`

- [x] **Step 1: 写损坏 index 红灯测试**

在 `RecoveryChapterProgressTests` 新增测试：

- 创建任务。
- 写入 `chapters/index.json` 内容为非法 JSON。
- `with self.assertLogs("app.application.task_service.continuation", level="WARNING")`。
- 调用 `service.get_current_chapters(task.id)`。
- 断言返回 `[]`，日志包含 `读取章节索引失败` 和 task id。

- [x] **Step 2: 写损坏单章红灯测试**

新增测试：

- 创建任务。
- 写入合法 `chapters/index.json`，包含第 1 章摘要 item。
- 写入损坏 `chapters/01.json`。
- 断言返回 index item，日志包含 `读取章节文件失败` 和 task id。

- [x] **Step 3: 运行后端红灯**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py::RecoveryChapterProgressTests::test_get_current_chapters_warns_when_index_json_is_corrupt apps/agent-runtime/tests/test_recovery_chapter_progress.py::RecoveryChapterProgressTests::test_get_current_chapters_warns_and_falls_back_when_chapter_json_is_corrupt -q
```

Expected: FAIL，因为当前异常分支没有 warning。

- [x] **Step 4: 最小实现**

在 `get_current_chapters()` 中：

- index 读取/解析失败时 `logger.warning("读取章节索引失败 task_id=%s path=%s", task_id, index_file, exc_info=True)` 并返回 `[]`。
- 单章读取/解析失败时 `logger.warning("读取章节文件失败 task_id=%s path=%s", task_id, chapter_file, exc_info=True)` 并回退 `item`。

- [x] **Step 5: 跑后端绿灯**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py -q
```

Expected: PASS。

### Task 4: 验证、审查与提交

**Files:**
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- Modify: `worklog/index.md`

- [x] **Step 1: 前端验证**

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- home-create.spec.ts task-state-branches.spec.ts --project=chromium
```

- [x] **Step 2: 后端验证**

Run:

```bash
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py -q
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
```

- [x] **Step 3: 全量 E2E**

Run:

```bash
npm --prefix apps/web run test:e2e
```

- [x] **Step 4: 代码审查**

派发只读审查 subagent：

- 暗色背景断言是否能覆盖旧浅色回归。
- `AppHeader`、`.glass-card`、`WorkflowOverviewCard` 是否不破坏浅色模式和导航语义。
- `get_current_chapters()` warning 是否不改变 `[]` / index item 降级语义。

- [x] **Step 5: 更新 worklog 并提交**

记录实施、审查反馈、验证结果；若 active 仍未完整完成，不归档。提交前核对：

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

提交信息使用中文，并排除 `.superpowers/brainstorm/*` 未跟踪辅助目录。

---

## 执行结果

- 前端 `AppHeader` 已增加 `data-testid="app-header"`，背景、边框、导航 active/hover 状态按 MUI theme mode 派生；移动端导航语义和原有路由保持不变。
- 全局 `.glass-card` 增加系统暗色兜底，`WorkflowOverviewCard` 通过 theme mode 回补应用内暗色背景、边框和阴影；工作流图谱节点/边语义未改。
- 后端 `TaskService.get_current_chapters()` 已对损坏 `chapters/index.json`、非 list 索引、非法 index 条目、非法章节编号和损坏单章 JSON 记录 warning；`index.json` 不存在仍静默返回 `[]`，损坏单章仍回退 index item。
- 只读审查发现 `index` 条目 `number` 异常值可能导致 API 500，以及工作流玻璃卡片测色存在主题水合竞态；已补实现和 `expect.poll` 断言后复核，未再发现阻塞问题。

## 验证结果

- 前端红灯：目标 E2E 曾因 `app-header` 定位缺失失败；后续暗色测色断言暴露主题水合竞态并已收敛为 `expect.poll`。
- 后端红灯：新增章节 warning 测试曾因无 warning 失败；补充错误结构和非法编号测试后暴露并修复 `AttributeError` / `ValueError`。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py -q`：9 passed，1 skipped。
- `npm --prefix apps/web run test:e2e -- home-create.spec.ts task-state-branches.spec.ts --project=chromium`：22 passed。
- `npm --prefix apps/web test`：114 passed。
- `npm --prefix apps/web run lint`：通过。
- `npm --prefix apps/web run build`：通过，仅保留既有 `metadataBase` warning。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：通过。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q`：385 passed，1 skipped，2 warnings，4 subtests passed。
- `npm --prefix apps/web run test:e2e`：108 passed。

## 收口状态

- 本批两个切片已完成并准备提交。
- `worklog/active` 仍包含 UI/UX 阶段 4 与 MVP 后续日志/死代码清理主线剩余项，本批不归档 active。
