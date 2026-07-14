# 工作流图谱暗黑精调与 test-only 组件清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精调工作台工作流图谱暗黑模式，并清理前端只被 import-only 测试引用的 test-only 组件。

**Architecture:** 前端图谱保持现有 `WorkflowOverviewCard` 组件边界，只把节点、边、画布、MiniMap 和空态样式改为主题感知。test-only 组件清理只删除无生产引用的叶子组件和对应 smoke 测试，不改变生产行为。

**Tech Stack:** Next.js 14、React 18、MUI 5 `sx`/theme、@xyflow/react React Flow、Playwright、Node test runner。

---

### Task 1: 图谱暗色红灯

**Files:**
- Modify: `apps/web/e2e/task-state-branches.spec.ts`

- [x] **Step 1: 写失败 E2E**

在移动端工作台用例或新增用例中设置暗色模式：

```ts
await page.addInitScript(() => {
  window.localStorage.setItem("theme-mode", "dark");
});
```

打开 `/p/{taskId}`，断言：

- `workflow-overview-card` 可见。
- `.react-flow` 可见。
- 页面 `scrollWidth <= clientWidth`。
- 第一个 `.react-flow__node` 的 `backgroundColor` 不是旧浅色 `rgb(255, 250, 242)` 或接近白色。

- [x] **Step 2: 运行红灯**

Run:

```bash
npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium
```

Expected: FAIL，因为当前图谱节点仍使用旧浅色硬编码。

### Task 2: 图谱暗黑最小实现

**Files:**
- Modify: `apps/web/src/features/task-run/workflow-overview-card.tsx`

- [x] **Step 1: 主题化节点和边样式**

把 `stateStyles()` 和 `edgeColor()` 改为接收 `mode`，保留状态色语义，但为 dark mode 使用低眩光深色背景、可读文字和高对比边框。

- [x] **Step 2: 主题化 React Flow 容器**

给 `GraphCanvas` 增加主题派生：

- `ReactFlow colorMode={mode}`。
- `Background color` 按 mode 设置。
- `MiniMap` 使用 `bgColor`、`nodeColor`、`nodeStrokeColor`、`maskColor`。
- 边 label `fill` 和 `labelBgStyle.fill` 按 mode 设置。
- 外层 `Box` 保留 `width/maxWidth/minWidth/contain/overflow` 移动端约束。

- [x] **Step 3: 增加稳定定位和可访问标签**

给卡片加 `data-testid="workflow-overview-card"`，给两个图谱容器加清晰 `aria-label`。

- [x] **Step 4: 运行绿灯**

Run:

```bash
npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium
```

Expected: PASS。

### Task 3: test-only 组件清理

**Files:**
- Delete: `apps/web/src/components/loading-overlay.tsx`
- Delete: `apps/web/src/components/loading-overlay.test.ts`
- Delete: `apps/web/src/components/page-container.tsx`
- Delete: `apps/web/src/components/page-container.test.ts`
- Delete: `apps/web/src/components/model-select.tsx`
- Delete: `apps/web/src/components/model-select.test.ts`
- Delete: `apps/web/src/components/confirm-dialog.tsx`
- Delete: `apps/web/src/components/confirm-dialog.test.ts`
- Delete: `apps/web/src/components/decision-bar.tsx`
- Delete: `apps/web/src/components/decision-bar.test.ts`
- Delete: `apps/web/src/components/stage-badge.tsx`
- Delete: `apps/web/src/components/stage-badge.test.ts`
- Delete: `apps/web/src/components/progress-bar.tsx`
- Delete: `apps/web/src/components/progress-bar.test.ts`
- Delete: `apps/web/src/components/skeleton-grid.tsx`
- Delete: `apps/web/src/components/skeleton-grid.test.ts`
- Delete: `apps/web/src/components/empty-state.tsx`
- Delete: `apps/web/src/components/empty-state.test.ts`

- [x] **Step 1: 记录清理前引用证据**

Run:

```bash
rg -n "LoadingOverlay|PageContainer|ModelSelect|ConfirmDialog|DecisionBar|StageBadge|ProgressBar|SkeletonGrid|EmptyState" apps/web/src --glob '!**/*.test.*'
```

Expected: 只命中目标组件自身定义，不出现生产调用方。

- [x] **Step 2: 删除目标组件和 import-only 测试**

删除目标文件，不改任何生产调用点。

- [x] **Step 3: 确认无残留引用**

Run:

```bash
rg -n "LoadingOverlay|PageContainer|ModelSelect|ConfirmDialog|DecisionBar|StageBadge|ProgressBar|SkeletonGrid|EmptyState" apps/web/src
```

Expected: 无输出。

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
npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium
```

- [x] **Step 2: 后端联动门禁**

Run:

```bash
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
```

- [x] **Step 3: 必要全量 E2E**

若目标 E2E 或暗色样式改动影响工作台布局，Run:

```bash
npm --prefix apps/web run test:e2e
```

- [x] **Step 4: 只读代码审查**

派发 subagent 审查：

- 图谱暗色模式是否仍保留工作流/Agent 图业务语义。
- React Flow 样式是否使用官方 props 且没有移动端回归。
- test-only 组件删除是否无生产引用残留。

- [x] **Step 5: 更新 worklog 并提交**

记录实施、审查反馈、验证结果；active 未全部完成，不归档。提交前核对：

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

提交信息使用中文，并排除 `.superpowers/brainstorm/*` 未跟踪辅助目录。
