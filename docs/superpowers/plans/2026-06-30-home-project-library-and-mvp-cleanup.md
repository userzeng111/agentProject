# 首页作品库 2B 与 MVP 第二批清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成首页作品库项目卡片切片，并处理 MVP 审查第二批低风险清理与日志覆盖。

**Architecture:** 首页仍复用现有 Dashboard API 和 MUI 布局，只替换任务项呈现层与对应 E2E 断言；MVP 第二批限定在小型死代码删除和异常日志覆盖，保持外部行为不变。两个切片文件范围独立，可由主线程与 worker 并行推进。

**Tech Stack:** Next.js 14 App Router, React 18, MUI v5, Playwright, Python 3.11, pytest/unittest, ruff

---

## 执行边界

- 不新增 API 字段。
- 不迁移审核、结果、归档详情旧路由。
- 不提交 `.superpowers/brainstorm/` 临时目录。
- 当前未发现 `Cargo.toml`，本轮不执行版本 patch 递增。

## Task 1: 首页作品库项目卡片

**Files:**
- Modify: `apps/web/e2e/home-create.spec.ts`
- Modify: `apps/web/src/app/page.tsx`
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`

- [x] **Step 1: 写失败 E2E**

在 `home-create.spec.ts` 增加断言：

- 首页展示“作品库”。
- 可见项目卡片包含 `自动化测试-created`、`Playwright fixture 摘要`、`待启动`、`created`、`短篇 · 原创`。
- 项目卡片主入口链接指向 `/p/task_created_fixture`。
- 390x844 viewport 下 `scrollWidth <= clientWidth`。

Run:

```bash
npm --prefix apps/web run test:e2e -- home-create.spec.ts --project=chromium
```

Expected: FAIL，因为首页尚未展示作品库语义或卡片测试标识。

- [x] **Step 2: 实现最小 UI**

在 `page.tsx` 中将 `TaskListItem` 调整为项目卡片式呈现：

- 增加可稳定定位的 `data-testid="project-card"`。
- 主按钮文案调整为“进入项目”。
- 摘要允许两行，元信息分组为 Chip/Caption。
- 保留失败重试和删除按钮逻辑。
- 主区域标题加入“作品库”语义。

- [x] **Step 3: 跑前端相关验证**

Run:

```bash
npm --prefix apps/web run test:e2e -- home-create.spec.ts --project=chromium
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

Expected: 相关 E2E、lint、build 通过；build 只允许既有 `metadataBase` 警告。

## Task 2: MVP 第二批后端日志与死代码

**Files:**
- Modify: `apps/agent-runtime/tests/test_runtime_settings.py`
- Modify: `apps/agent-runtime/app/settings/runtime_settings.py`
- Modify: `apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py`
- Modify: `apps/agent-runtime/app/settings/config.py`
- Modify: `apps/agent-runtime/tests/test_model_compatibility.py`
- Modify: `apps/agent-runtime/app/llm/model_compatibility.py`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`

- [x] **Step 1: 写失败测试**

新增或扩展测试：

- `runtime_settings` 的 set/remove round-trip 覆盖协议覆盖写入与删除，不依赖 `save_runtime_settings()`。
- 无效 `MODEL_PROTOCOL_OVERRIDES` 返回 `{}` 且记录 warning。
- 损坏 `model_compatibility.json` 返回 `unverified` 且记录 warning。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_runtime_settings.py apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py apps/agent-runtime/tests/test_model_compatibility.py -q
```

Expected: FAIL，warning 断言尚未满足。

- [x] **Step 2: 实现最小后端改动**

- 删除未使用的 `save_runtime_settings()`。
- 在 `config.py` 解析 `MODEL_PROTOCOL_OVERRIDES` 失败时记录 warning。
- 在 `model_compatibility.py` 读取缓存损坏时记录 warning。

- [x] **Step 3: 跑后端相关验证**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_runtime_settings.py apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py apps/agent-runtime/tests/test_model_compatibility.py -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

Expected: 通过。

## Task 3: 前端字体死代码清理

**Files:**
- Modify: `apps/web/src/app/globals.css`
- Delete: `apps/web/src/lib/fonts.ts`
- Modify: `apps/web/src/lib/api.test.mjs` 或新增轻量测试文件

- [x] **Step 1: 写失败测试**

新增前端测试，读取 `globals.css` 并断言保留：

- `--font-sans-sc`
- `--font-serif-sc`

Run:

```bash
npm --prefix apps/web test
```

Expected: 测试通过后再删除 `fonts.ts`；若先断言文件不存在则当前应 FAIL。

- [x] **Step 2: 删除死代码**

删除 `apps/web/src/lib/fonts.ts`，不修改全局字体变量。

- [x] **Step 3: 跑前端验证**

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

Expected: 通过。

## Task 4: 汇总验证与收口

**Files:**
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- Modify: `worklog/index.md`
- Modify: `worklog/history.md`

- [x] **Step 1: 跑完整验证**

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

- [x] **Step 2: 更新 worklog**

记录本轮实施结果、验证结果和仍未完成的阶段 3/4 风险。只有用户明确同意收口后，才归档 active。

- [x] **Step 3: 提交前门禁**

Run:

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

确认仓库无误后，先归档 active，再提交。提交信息使用中文并包含主体大纲。
