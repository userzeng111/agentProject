# ProjectShell/StageNav 与 MVP 第三批清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成审核页/结果页的 ProjectShell 与 StageNav 最小切片，并补齐模型兼容性第三批日志覆盖与首页长 ID 移动端风险修复。

**Architecture:** 前端新增两个共享组件，先接入审核页和结果页，保留旧路由与业务表单；后端只补日志和实例级兼容性 store 缓存，保持外部返回语义。首页仅加断词样式并扩展现有 E2E fixture。

**Tech Stack:** Next.js 14 App Router, React 18, MUI v5, Playwright, Node test runner, Python 3.11, pytest/unittest, ruff

---

## 执行边界

- 不提交任何 `.superpowers/` 临时目录；提交前必须检查 `git status --short`。
- 不迁移 `/review?id=`、`/result?id=`、`/archive/detail?id=` 路由。
- 不接入 `/p/[projectId]` 工作台。
- 当前未发现 `src/Cargo.toml`，本轮不执行版本 patch 递增。

## Task 1: 后端模型兼容性日志与缓存

**Files:**
- Modify: `apps/agent-runtime/tests/test_model_compatibility.py`
- Modify: `apps/agent-runtime/tests/test_model_catalog.py`
- Modify: `apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py`
- Modify: `apps/agent-runtime/app/llm/model_compatibility.py`
- Modify: `apps/agent-runtime/app/llm/gateway_client.py`

- [x] **Step 1: 写失败测试**

新增测试：

- 损坏 `model_compatibility.json` 经过 `ModelCatalogService.list_models_payload(force_refresh=True)` 多模型聚合时，只记录一次“读取模型兼容性报告失败” warning。
- 外部修改 `model_compatibility.json` 后，`get_report()` 能按文件指纹读到新内容。
- 损坏文件修复后，`get_report()` 不继续沿用空 store。
- `clear_report()` 后立即返回 `unverified`，不会读到旧缓存。
- `model_catalog_invalidator` 抛错时，`save_report()` 不抛出并记录“刷新模型目录缓存失败” warning。
- `model_catalog_resolver` 抛错时，`run_validation_stream()` 以 `gateway_visible` 失败结束并记录 warning。
- `protocol_overrides_resolver` 抛错时，`_resolve_protocol()` 继续返回默认协议并记录 warning。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_model_compatibility.py apps/agent-runtime/tests/test_model_catalog.py apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py -q
```

Expected: FAIL，warning 次数或日志断言尚未满足。

- [x] **Step 2: 最小实现**

- 在 `ModelCompatibilityService` 中增加 store 缓存和文件指纹。
- 文件损坏时同一指纹只记录一次 warning。
- `save_report()` / `clear_report()` 写入后更新或失效缓存。
- 三处静默异常补 warning，不改变返回值。

- [x] **Step 3: 后端针对性验证**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_model_compatibility.py apps/agent-runtime/tests/test_model_catalog.py apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

Expected: 全部通过。

## Task 2: StageNav 与 ProjectShell 最小切片

**Files:**
- Create: `apps/web/src/components/stage-nav.tsx`
- Create: `apps/web/src/components/stage-nav.test.mjs`
- Create: `apps/web/src/components/project-shell.tsx`
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`
- Modify: `apps/web/src/features/task-result/task-result-client.tsx`
- Modify: `apps/web/e2e/review-result-archive.spec.ts`

- [x] **Step 1: 写失败测试**

新增或修改测试：

- `stage-nav.test.mjs` 导入 helper，断言 active index、done/current/upcoming 状态稳定。
- `review-result-archive.spec.ts` 审核页大纲分支断言 `project-shell` 与 `stage-nav` 可见，当前阶段包含“审核”。
- `review-result-archive.spec.ts` 审核页章节分支与验证分支也断言 `project-shell` 与 `stage-nav` 可见，当前阶段分别包含“审核”或“验证”。
- `review-result-archive.spec.ts` 结果页断言 `project-shell` 与 `stage-nav` 可见，当前阶段包含“结果”。

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: FAIL，因为组件和 test id 尚未存在。

- [x] **Step 2: 最小实现**

- 新增 `StageNav`，使用 MUI `Card`/`Stack`/`Typography`，暴露 `resolveStageNavItems()` 供 Node 单测使用。
- `StageNav` 使用 `aria-label="任务阶段导航"`、`data-testid="stage-nav"`、`minWidth: 0`、`overflowX: "auto"`，阶段项 `flexShrink: 0`。
- 新增 `ProjectShell`，统一渲染面包屑、标题、meta chips、顶部 actions 和 `stageNav` 插槽，带 `data-testid="project-shell"`。
- 审核页删除局部 `StepIndicator`，用 `StageNav` + `ProjectShell` 包裹当前内容。
- 结果页删除内联步骤条和重复面包屑/标题，改用 `ProjectShell`；复制全文和导出 MD 继续保留在正文卡片内。

- [x] **Step 3: 前端针对性验证**

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: 全部通过，build 只允许既有 `metadataBase` 警告。

## Task 3: 首页长任务 ID 移动端溢出

**Files:**
- Modify: `apps/web/e2e/helpers/fixtures.ts`
- Modify: `apps/web/e2e/home-create.spec.ts`
- Modify: `apps/web/src/app/page.tsx`

- [x] **Step 1: 写失败测试**

把首页移动端 E2E fixture 的 created 任务 ID 扩展为长不可断字符串，断言项目卡片仍可见、链接 href 同步指向长 ID，且 document 与目标项目卡片都满足 `scrollWidth <= clientWidth`。

Run:

```bash
npm --prefix apps/web run test:e2e -- home-create.spec.ts --project=chromium
```

Expected: FAIL，因为底部 ID caption 尚未设置断词，长不可断 ID 会造成卡片或页面横向溢出。

- [x] **Step 2: 最小实现**

给首页卡片底部 ID caption 增加 `minWidth: 0`、`overflowWrap: "anywhere"`，必要时让底部 meta 容器 `minWidth: 0`。

- [x] **Step 3: 针对性验证**

Run:

```bash
npm --prefix apps/web run test:e2e -- home-create.spec.ts --project=chromium
```

Expected: 通过。

## Task 4: 汇总验证与 worklog

**Files:**
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- Modify: `worklog/index.md`

- [x] **Step 1: 汇总验证**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts home-create.spec.ts --project=chromium
npm --prefix apps/web run test:e2e
```

- [x] **Step 2: 更新 worklog**

记录本批实施结果、验证结果和剩余事项。若阶段 3/4 与 MVP 清理仍未全部完成，保持 active，不归档。

- [ ] **Step 3: 提交前门禁**

只有用户明确要求收口提交时执行：

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

确认目标仓库无误后，按“先归档，后提交”规则处理。
