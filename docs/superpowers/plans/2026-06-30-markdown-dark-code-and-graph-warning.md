# Markdown 暗色代码块与 graph state warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精调 Markdown 阅读链路暗色代码块，并补 `_graph_state_values()` 静默异常 warning 覆盖。

**Architecture:** 前端保持 `MarkdownContent` 组件边界，抽出本地代码样式 helper，结果页和归档详情通过共享阅读链路自然受益。后端只在 `TaskService._graph_state_values()` 的异常降级分支补 warning，不改变返回语义。

**Tech Stack:** Next.js 14、React 18、MUI 5 `sx`/theme、react-markdown、Playwright、FastAPI、pytest、ruff。

---

### Task 1: Markdown 暗色红灯

**Files:**
- Create: `apps/web/src/components/markdown-content.test.mjs`
- Modify: `apps/web/e2e/review-result-archive.spec.ts`

- [x] **Step 1: 写组件红灯测试**

新增 `markdown-content.test.mjs`：

- 渲染包含行内 code、code fence、危险链接、安全图片 data URI 的 Markdown。
- 断言输出不包含 `grey.100` 和 `rgba(0,0,0,0.06)` 等旧浅色代码样式。
- 断言危险链接不会保留 `javascript:`，安全图片 data URI 仍渲染。

- [x] **Step 2: 运行组件红灯**

Run:

```bash
npm --prefix apps/web test -- src/components/markdown-content.test.mjs
```

Expected: FAIL，因为当前组件仍输出旧浅色代码样式。

- [x] **Step 3: 写 E2E 红灯**

扩展 `review-result-archive.spec.ts` 的结果页用例：

- 设置 390px 暗色模式。
- result/chapter fixture 加入 code fence。
- 断言 `novel-reader-content pre` 可见，背景不是浅灰/浅米色，页面无横向滚动。

- [x] **Step 4: 运行 E2E 红灯**

Run:

```bash
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: FAIL，当前 code fence 暗色背景仍是浅色。

### Task 2: MarkdownContent 暗色实现

**Files:**
- Modify: `apps/web/src/components/markdown-content.tsx`

- [x] **Step 1: 抽出主题感知代码样式**

新增本地 `codeSx` / `codeBlockSx` helper，按 `theme.palette.mode` 返回暗色背景、边框和文字色。

- [x] **Step 2: 替换行内 code**

将行内 code 从原生 `style` 改为 `Box component="code"`，保留 react-markdown ref 兼容注释，增加 `maxWidth` 与断词约束。

- [x] **Step 3: 替换 code fence**

抽出共享 `CodeBlock`，article 使用 14px/1.6，outline 使用 13px/1.5；保留 `overflowX: "auto"`、`maxWidth: "100%"`。

- [x] **Step 4: 跑绿灯**

Run:

```bash
npm --prefix apps/web test -- src/components/markdown-content.test.mjs
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: PASS。

### Task 3: graph state warning 红灯与实现

**Files:**
- Modify: `apps/agent-runtime/tests/test_task_service_review_resume.py`
- Modify: `apps/agent-runtime/app/application/task_service/core.py`

- [x] **Step 1: 写后端红灯测试**

在 `TaskServiceReviewResumeTests` 新增测试：

- fake `workflow_engine.get_state()` 抛 `RuntimeError("boom")`。
- `with self.assertLogs("app.application.task_service.core", level="WARNING")`。
- 调用 `service._graph_state_values(task.id)`。
- 断言返回 `{}`，日志包含 `读取工作流 checkpoint 状态失败` 和 task_id。

- [x] **Step 2: 运行后端红灯**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_review_resume.py::TaskServiceReviewResumeTests::test_graph_state_values_warns_when_get_state_fails -q
```

Expected: FAIL，因为当前异常分支没有 warning。

- [x] **Step 3: 最小实现**

在 `_graph_state_values()` 的 `except Exception` 中记录：

```python
logger.warning("读取工作流 checkpoint 状态失败 task_id=%s", task_id, exc_info=True)
```

继续返回 `{}`。

- [x] **Step 4: 跑绿灯**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_review_resume.py::TaskServiceReviewResumeTests::test_graph_state_values_warns_when_get_state_fails -q
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
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

- [x] **Step 2: 后端验证**

Run:

```bash
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_review_resume.py -q
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
```

- [x] **Step 3: 全量 E2E**

Run:

```bash
npm --prefix apps/web run test:e2e
```

- [x] **Step 4: 只读代码审查**

派发 subagent 审查：

- Markdown 安全链接/图片语义是否保留。
- 暗色 code fence 是否避免旧浅色背景和移动端溢出。
- `_graph_state_values()` warning 是否不改变 `{}` 降级语义。

- [x] **Step 5: 更新 worklog 并提交**

记录实施、审查反馈、验证结果；active 未全部完成，不归档。提交前核对：

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

提交信息使用中文，并排除 `.superpowers/brainstorm/*` 未跟踪辅助目录。

## 执行结果

- MarkdownContent 已改为主题感知行内 code 与 code fence 样式，并保留危险链接拦截、外链安全属性和安全 `data:image/*` 图片渲染语义。
- 结果页暗色移动端 E2E 已覆盖 code fence 可见、背景亮度阈值和页面无横向滚动。
- `_graph_state_values()` 读取 checkpoint 状态异常时记录 warning，返回 `{}` 降级语义不变。
- 只读审查发现两个低风险点：E2E 背景断言过窄、无语言 code fence 混入行内 code 样式；均已修复并补测。
- 完整验证已通过：前端单测、lint、build、目标 E2E、全量 E2E、后端 ruff、目标服务测试与后端全量 pytest。
