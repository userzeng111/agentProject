# 归档列表体验与上下文缓存日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将归档列表升级为更可扫描的作品库卡片，并补齐上下文缓存异常日志测试覆盖。

**Architecture:** 前端改 `ArchiveListClient` 的呈现层，继续使用 `archiveDetailHref()`。后端向 `TaskSummary` 增加向后兼容的可选归档指标字段，并补上下文缓存 warning 的 characterization tests；只有日志测试暴露生产缺口时才做最小实现。

**Tech Stack:** Next.js 14 App Router, React 18, MUI v5, Playwright, Node test runner, Python 3.11, unittest/pytest, ruff

---

## 执行边界

- 不改 `/archive/detail/?id=` 路由。
- 不改归档查询参数、分页语义或归档详情 payload。
- 不做审核页左右分屏。
- 不删除前端 test-only 组件。
- 不触碰动态 Agent、`StoryEngine`、`TaskLogStore` 恢复链路。
- 涉及第三方库用法时先查 context7；本批已确认 MUI/Next.js 继续沿用现有组件模式。
- 当前未发现 `src/Cargo.toml`，本轮不执行 Cargo patch 版本递增。

## Task 1: 归档列表 API contract 与前端失败测试

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Modify: `apps/agent-runtime/app/application/task_service/queries.py`
- Modify: `apps/agent-runtime/tests/test_api_context.py`
- Modify: `apps/web/e2e/helpers/fixtures.ts`
- Modify: `apps/web/e2e/review-result-archive.spec.ts`

- [x] **Step 1: 写后端归档指标 contract 失败测试**

扩展 `test_result_and_archive_endpoints_expose_json_refs_and_sources`：

- 完成任务归档后调用 `/api/archive`。
- 测试数据改为 2 个 `chapter_plan` 与 2 个 `draft_result.chapters`。
- 断言 `archive_list_payload["items"][0]["chapter_count"] == 2`。
- 断言 `archive_list_payload["items"][0]["word_count"] > 0`。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_result_and_archive_endpoints_expose_json_refs_and_sources -q
```

Expected: FAIL，因为 `TaskSummary` 当前没有 `chapter_count` / `word_count`。

- [x] **Step 2: 扩展归档 fixture**

在 `makeArchiveList()` 中补充：

- 长标题或长摘要。
- `default_model_id` 为长不可断模型 ID。
- `last_action_model_id`。
- `chapter_count: 2`。
- `word_count: 1200`。

- [x] **Step 3: 写失败 E2E**

在“归档列表和详情 Tab 可渲染”或新增测试中断言：

- `page.getByTestId("archive-card")` 可见。
- 卡片匹配 `/章节[:：]?\\s*2|2\\s*章/`。
- 卡片匹配 `/字数[:：]?\\s*1,?200|1,?200\\s*字/`。
- 卡片包含类型文案“全新原创 · 短篇”。
- 卡片包含长模型 ID。
- “查看归档详情”链接可见且 href 指向 `archiveDetailHref` 的结果。

新增移动端测试：

```ts
await page.setViewportSize({ width: 390, height: 844 });
await page.goto("/archive", { waitUntil: "commit" });
const hasHorizontalOverflow = await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
);
expect(hasHorizontalOverflow).toBe(false);
```

Run:

```bash
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Expected: FAIL，因为当前归档列表没有 `archive-card` test id，指标呈现也不足。

## Task 2: 归档指标 API 与归档列表 UI 最小实现

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Modify: `apps/agent-runtime/app/application/task_service/queries.py`
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/features/task-archive/archive-list-client.tsx`

- [x] **Step 1: 增加归档指标 API 字段**

实现：

- `TaskSummary` 增加 `chapter_count: int | None = None`。
- `TaskSummary` 增加 `word_count: int | None = None`。
- `ArchiveTaskSummary` 增加 `chapter_count?: number | null`。
- `ArchiveTaskSummary` 增加 `word_count?: number | null`。
- `_to_summary()` 从 `task.draft_result.chapters` 计算章节数和近似字数。
- 如果没有 `draft_result`，章节数回退到 `task.story_plan.chapter_plan` 长度；字数为 `None`。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_result_and_archive_endpoints_expose_json_refs_and_sources -q
```

Expected: PASS。

- [x] **Step 2: 重构卡片呈现**

实现：

- 每个归档项卡片加 `data-testid="archive-card"`。
- 使用 `Chip` 展示章节数、字数、类型。
- 使用 `Stack`/`Box` 展示默认模型、最近动作模型、更新时间。
- 标题、摘要、模型字段设置 `overflowWrap: "anywhere"`、`minWidth: 0`。
- 操作按钮保留 `archiveDetailHref(item.task_id)`。

- [x] **Step 3: 保留 loading/error/empty/pagination**

确认：

- loading skeleton 仍渲染。
- `error` Alert 不变。
- 空态仍显示“当前还没有可浏览的归档任务。”。
- `totalPages > 1` 时分页仍可用。

- [x] **Step 4: 针对性验证**

Run:

```bash
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_result_and_archive_endpoints_expose_json_refs_and_sources -q
```

Expected: PASS。

## Task 3: 上下文缓存日志 characterization tests

**Files:**
- Modify: `apps/agent-runtime/tests/test_context_manager.py`

- [x] **Step 1: 写 ContextManager cache get warning 测试**

新增抛异常 cache store：

- `get()` 抛 `RuntimeError("cache read broken")`。
- `set()` 记录写入。
- 调用 `ContextManager.build_snapshot()`。
- 使用 `assertLogs("app.context.manager", level="WARNING")` 断言“读取上下文缓存失败”。
- 断言 `snapshot.cache_hit is False` 且仍返回 assembled packet。

- [x] **Step 2: 写 ContextManager cache set warning 测试**

新增 cache store：

- `get()` 返回 `None`。
- `set()` 抛 `RuntimeError("cache write broken")`。
- 调用 `build_snapshot()`。
- 断言“写入上下文缓存失败”。
- 断言 snapshot 正常返回。

- [x] **Step 3: 写 FileBackedCacheStore 损坏文件 warning 测试**

导入 `FileBackedCacheStore`：

- 先 `store.set("demo", {"value": 1})`，再用 `_path_for_key("demo")` 定位并破坏文件内容。
- 调用 `store.get("demo")`。
- 断言返回 `None`。
- 使用 `assertLogs("app.context.cache_store", level="WARNING")` 断言“读取磁盘缓存失败”。

- [x] **Step 4: 写 LayeredCacheStore warning 测试**

导入 `LayeredCacheStore`：

- 第一层 `get()` 抛异常，第二层返回 `{"ok": true}`，断言返回第二层值且记录“缓存层读取失败”。
- 第一层 `set()` 抛异常，第二层记录值，断言第二层仍收到写入且记录“缓存写入失败”。
- 使用 `assertLogs("app.context.cache_store", level="WARNING")`。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_context_manager.py -q
```

Expected: PASS。该任务是现有 warning 行为刻画测试，不要求先失败；若失败，仅做最小生产日志补漏。

## Task 4: 汇总验证与 worklog

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Modify: `apps/agent-runtime/app/application/task_service/queries.py`
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- Modify: `worklog/index.md`

- [x] **Step 1: 实施前/实施中更新 worklog**

记录本批选择、范围、风险和当前状态到两个 active 文档。

- [x] **Step 2: 前端汇总验证**

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium
```

Actual:

- `npm --prefix apps/web test`：111 passed。
- `npm --prefix apps/web run lint`：通过。
- `npm --prefix apps/web run build`：通过，仅保留既有 `metadataBase` 警告。
- `npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium`：8 passed。

- [x] **Step 3: 后端汇总验证**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_result_and_archive_endpoints_expose_json_refs_and_sources apps/agent-runtime/tests/test_context_manager.py -q
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_context_manager.py -q
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

Actual:

- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_result_and_archive_endpoints_expose_json_refs_and_sources apps/agent-runtime/tests/test_context_manager.py -q`：11 passed。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_context_manager.py -q`：10 passed。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：通过。

- [x] **Step 4: 扩展验证**

若改动影响共享 E2E 稳定性，继续跑：

```bash
npm --prefix apps/web run test:e2e
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
```

Actual:

- `npm --prefix apps/web run test:e2e`：100 passed。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q`：376 passed，1 skipped，2 warnings，4 subtests passed。

- [x] **Step 5: 更新 worklog**

记录本批实施结果、验证结果和剩余事项。两个 active 若仍未全部完成，保持 active，不归档。

- [x] **Step 6: 提交前门禁**

只有提交时执行：

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

确认没有暂存 `.superpowers/` 后提交。

提交信息必须为中文，并包含主体大纲。两个 active 未全部完成时不归档；只有用户明确同意收口时才执行 active -> archive。

Actual:

- `pwd`：`/home/user01/WorkSpace/AgentProject`。
- `git rev-parse --show-toplevel`：`/home/user01/WorkSpace/AgentProject`。
- `git remote -v`：`origin git@github.com:userzeng111/agentProject.git`。
- `git status --short`：确认本批变更存在，`.superpowers/brainstorm/...` 为未跟踪且不纳入提交。
