# 归档阅读器与 RAG 状态日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一结果页/归档详情的章节阅读体验，归档详情接入 ProjectShell，并补齐 RAG status 损坏文件 warning。

**Architecture:** 前端新增共享 `NovelReader`，结果页和归档详情只负责数据加载与页面壳；阅读器只负责章节翻页和正文呈现。后端只在 RAG status 文件损坏时补 warning，保持 `get_status()` 返回结构不变。

**Tech Stack:** Next.js 14 App Router, React 18, MUI v5, Playwright, Node test runner, Python 3.11, pytest, ruff

---

## 执行边界

- 不迁移 `/result?id=` 与 `/archive/detail?id=` 路由。
- 不删除 test-only 通用组件。
- 不触碰 `TaskLogStore`、动态 Agent、`StoryEngine` 主链路。
- 当前未发现 `src/Cargo.toml`，本轮不执行版本 patch 递增。

## Task 1: StageNav review 修复

**Files:**
- Modify: `apps/web/src/components/stage-nav.test.mjs`
- Modify: `apps/web/src/components/stage-nav.tsx`

- [x] **Step 1: 写失败测试**

新增 SSR 渲染测试：

- `StageNav` 的阶段只传 `label`，不传 `icon`。
- `activeStep=1` 时当前圆点必须显示 `2`，不能为空。

Run:

```bash
npm --prefix apps/web test -- src/components/stage-nav.test.mjs
```

Expected: FAIL，当前阶段圆点为空。

- [x] **Step 2: 最小实现**

`StageNav` 对非 done 阶段渲染 `item.icon ?? item.index + 1`。

- [x] **Step 3: 验证**

Run:

```bash
npm --prefix apps/web test -- src/components/stage-nav.test.mjs
```

Expected: PASS。

## Task 2: 共享 NovelReader 与结果页阅读体验

**Files:**
- Create: `apps/web/src/components/novel-reader.tsx`
- Create: `apps/web/src/components/novel-reader.test.mjs`
- Modify: `apps/web/src/features/task-result/task-result-client.tsx`
- Modify: `apps/web/e2e/review-result-archive.spec.ts`

- [x] **Step 1: 写失败测试**

新增或修改测试：

- `novel-reader.test.mjs` 导入 helper，断言页码 clamp 或章节标题格式稳定。
- `novel-reader.test.mjs` SSR 渲染 `NovelReader`，断言输出不包含旧阅读器硬编码颜色 `#fffaf2` 与 `#1d2a27`。
- `review-result-archive.spec.ts` 结果页 fixture 提供两章 `chapter_index`。
- 结果页断言 `novel-reader` 可见、初始显示“第一章”，点击“下一章”后显示“第二章”。
- 结果页仍断言“复制全文”和“导出 MD”按钮可见；点击“复制全文”后出现复制反馈，防止全文工作流被阅读器替换。

Run:

```bash
npm --prefix apps/web test -- src/components/novel-reader.test.mjs
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: FAIL，因为 `novel-reader` 不存在，结果页没有阅读器。

- [x] **Step 2: 最小实现**

- 新增 `NovelReader`，导出 `resolveNovelReaderPage(chapters, page)` 供 Node 单测使用。
- `NovelReader` 根节点 `data-testid="novel-reader"`，正文区域 `data-testid="novel-reader-content"`。
- 空章节显示 info `Alert`。
- 顶部与底部提供上一章/下一章导航，底部保留 `Pagination`。
- 使用主题 token，不使用浅色硬编码。
- 结果页在 `chapter_index.length > 0` 时于“正文内容”卡片前展示 `NovelReader`。

- [x] **Step 3: 针对性验证**

Run:

```bash
npm --prefix apps/web test -- src/components/novel-reader.test.mjs
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: PASS。

## Task 3: 归档详情 ProjectShell 与共享阅读器

**Files:**
- Modify: `apps/web/src/features/task-archive/archive-detail-client.tsx`
- Modify: `apps/web/e2e/review-result-archive.spec.ts`

- [x] **Step 1: 写失败测试**

修改 E2E：

- 访问 `/archive/detail/?id=task_archive_fixture`，断言 `project-shell` 可见。
- 访问 `/archive/detail/?id=task_archive_fixture&tab=read`，断言 `novel-reader` 可见。
- 点击下一章后断言显示第二章。
- 点击“原始信息”Tab 后断言 URL query 更新为 `tab=meta`。
- 原始信息 Tab 中断言“复制全文”和“导出 MD”按钮可见；点击“复制全文”后出现复制反馈。

Run:

```bash
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: FAIL，因为归档详情尚未接入 `ProjectShell`，阅读器没有共享 test id。

- [x] **Step 2: 最小实现**

- 删除归档详情局部 `ChapterReader`。
- 导入 `ProjectShell` 与 `NovelReader`。
- 用 `ProjectShell` 包裹原 Tab 内容，保留 `Tabs`、`activeTab`、`handleTabChange` 与 `Snackbar`。
- `Tabs` 使用 `variant="scrollable"`、`scrollButtons="auto"`、`allowScrollButtonsMobile`，保留可访问标签。
- `read` Tab 改用 `<NovelReader chapters={detail.chapter_index} />`。

- [x] **Step 3: 针对性验证**

Run:

```bash
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: PASS。

## Task 4: RAG status 损坏文件 warning

**Files:**
- Modify: `apps/agent-runtime/app/rag/rebuild_service.py`
- Modify: `apps/agent-runtime/tests/test_rag_rebuild.py`

- [x] **Step 1: 写失败测试**

新增测试：

- 构造临时 RAG config，确保 `status_path` 文件存在且内容为损坏 JSON。
- 调用 `NovelCorpusRebuildService.get_status()`。
- 断言返回 `last_result is None`。
- 使用 `caplog` 或 `assertLogs` 断言记录“读取 RAG 重建状态失败” warning。
- 再构造 `status_path` 内容为 JSON 数组，断言返回 `last_result is None` 且记录“格式不正确” warning。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_rag_rebuild.py -q
```

Expected: FAIL，因为当前静默返回 `None`。

- [x] **Step 2: 最小实现**

- `_load_status()` 文件不存在时继续返回 `None` 且不记录 warning。
- 文件存在但读取/解析失败时记录 warning，返回 `None`。
- 文件内容不是对象时记录 warning，返回 `None`。

- [x] **Step 3: 后端针对性验证**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_rag_rebuild.py -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

Expected: PASS。

## Task 5: 汇总验证与 worklog

**Files:**
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- Modify: `worklog/index.md`

- [x] **Step 1: 汇总验证**

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_rag_rebuild.py -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

- [x] **Step 2: 视情况跑扩展验证**

若改动影响全局页面壳或结果/归档页面布局，继续跑：

```bash
npm --prefix apps/web run test:e2e
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
```

- [x] **Step 3: 更新 worklog**

记录本批实施结果、验证结果和剩余事项。UI 阶段 3/4 与 MVP 清理若仍未全部完成，保持 active，不归档。

- [x] **Step 4: 提交前门禁**

只有收口提交时执行：

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

确认 `.superpowers/` 未暂存后提交。
