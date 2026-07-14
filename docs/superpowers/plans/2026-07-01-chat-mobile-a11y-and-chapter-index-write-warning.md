# 聊天移动端可访问性与章节索引写入 warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复聊天页移动端消息区可访问性/横向溢出问题，并补章节索引写入侧 warning 与格式防护。

**Architecture:** 前端保持 `ChatClient` 边界不拆分，只增强消息区控件语义和响应式样式；后端只在 `TaskService._write_chapter_file()` 的旧索引读取/规范化分支补 warning 与容错，不改变章节正文落盘结构。

**Tech Stack:** Next.js 14、React 18、MUI 5、Playwright、FastAPI、pytest、ruff。

---

### Task 1: 前端聊天页红灯

**Files:**
- Modify: `apps/web/e2e/chat-settings.spec.ts`

- [x] **Step 1: 写移动端聊天长文本与思考按钮红灯**

新增或扩展聊天页 E2E：

- viewport 设置为 390x844。
- mock `/api/chat/stream` 返回：
  - `reasoning_content` 为长不可断字符串。
  - `content` 为长不可断字符串。
  - `chat.done` 正常结束。
- 发送长不可断用户输入。
- 断言页面无横向滚动。
- 断言思考过程可通过 `getByRole("button", { name: /思考过程|正在思考/ })` 定位。
- 断言 `aria-expanded` 初始为 `false`，按 `Enter` 或 `Space` 后为 `true`。

- [x] **Step 2: 运行前端红灯**

Run:

```bash
npm --prefix apps/web run test:e2e -- chat-settings.spec.ts --project=chromium
```

Expected: FAIL，因为当前思考过程不是 button 语义，长文本也缺少完整断词兜底。

Result: FAIL。初始红灯无法通过 `getByRole("button", { name: /思考过程|正在思考/ })` 定位思考过程触发区；审查反馈后新增 320px 顶部导航/聊天标题栏无横向滚动用例，红灯为页面 `scrollWidth > innerWidth`。

### Task 2: 前端聊天页实现

**Files:**
- Modify: `apps/web/src/features/chat/chat-client.tsx`
- Modify: `apps/web/src/components/app-header.tsx`

- [x] **Step 1: 补移动端菜单按钮可访问名称**

给移动端打开会话列表的 `IconButton` 增加：

```tsx
aria-label="打开会话列表"
```

- [x] **Step 2: 思考过程触发区改为可访问按钮**

将当前可点击 `Box` 改为 `Box component="button"` 或 MUI `ButtonBase`：

- `type="button"`。
- `aria-expanded={Boolean(expandedThinking[idx])}`。
- `aria-controls={`thinking-content-${idx}`}`。
- 保留视觉样式，增加焦点态。
- 不改变 `toggleThinking(idx)` 的状态逻辑。

- [x] **Step 3: 消息区增加溢出兜底**

在消息滚动区和气泡内部补：

- `minWidth: 0`。
- `overflowX: "hidden"`。
- 用户/助手气泡使用移动端更宽但受限的 `maxWidth`。
- 正文、思考链和 token/验证 Chip 容器使用 `overflowWrap: "anywhere"` 与 `wordBreak: "break-word"`。
- 滚动条颜色按 theme mode 派生。

- [x] **Step 4: 跑前端绿灯**

Run:

```bash
npm --prefix apps/web run test:e2e -- chat-settings.spec.ts --project=chromium
```

Expected: PASS。

Result: PASS。审查反馈后同步补移动端聊天标题栏换行收缩、长默认模型 ID 断词、长模型显示名/provider 省略，以及全局顶部导航在 320px 下的图标按钮间距收缩和 44px 触控目标，最终 `chat-settings.spec.ts --project=chromium` 为 6 passed。

### Task 3: 后端章节索引写入红灯

**Files:**
- Modify: `apps/agent-runtime/tests/test_recovery_chapter_progress.py`

- [x] **Step 1: 写损坏写入索引红灯**

新增测试：

- 创建任务。
- 写入损坏 `chapters/index.json`。
- `assertLogs("app.application.task_service.continuation", level="WARNING")`。
- 调用 `service._write_chapter_file(task.id, 1, "第一章", "摘要", "正文")`。
- 断言 warning 包含 `读取章节索引失败` 和 task id。
- 断言 `01.md`、`01.json`、`index.json` 存在。
- 断言 `get_current_chapters(task.id)` 能读回第 1 章正文。

- [x] **Step 2: 写非 list 索引红灯**

新增测试：

- `index.json` 写入对象而非数组。
- 调用 `_write_chapter_file()`。
- 断言 warning 包含 `章节索引格式不正确`。
- 断言 index 重建并包含当前章节。

- [x] **Step 3: 写坏条目跳过红灯**

新增测试：

- `index.json` 写入坏条目、非法编号条目和一个有效旧章节。
- 调用 `_write_chapter_file()` 写入新章节。
- 断言 warning 包含 `章节索引条目格式不正确`。
- 断言有效旧章节保留，新章节追加，坏条目跳过。

- [x] **Step 4: 运行后端红灯**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py -q
```

Expected: FAIL，因为当前写入侧无 warning，非 list/坏条目还可能抛异常。

Result: FAIL。新增已有 `01.json`/`02.json` 且 `index.json` 损坏时写第 3 章的红灯，当前实现只保留第 3 章，未从已有章节文件重建索引。

### Task 4: 后端章节索引写入实现

**Files:**
- Modify: `apps/agent-runtime/app/application/task_service/continuation.py`

- [x] **Step 1: 增加写入侧索引读取与规范化**

在 `_write_chapter_file()` 的 lock 内：

- 捕获 `OSError/json.JSONDecodeError/ValueError`，warning 后使用空索引。
- 非 list warning 后使用空索引。
- 遍历条目时跳过非 dict 或非法 `number`，并 warning。
- 保留有效条目。

- [x] **Step 2: 去重追加当前章节并稳定排序**

- 用有效条目的 `number` 去重。
- 当前章节 `chapter_number` 为正整数时追加或替换为最新 title/summary。
- 排序只对合法正整数执行。

- [x] **Step 3: 跑后端绿灯**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py -q
```

Expected: PASS。

Result: PASS。`_write_chapter_file()` 在损坏或错误结构 index 下记录 warning 并从已有章节 JSON 重建轻量索引，再用当前章节 title/summary 覆盖对应编号。

### Task 5: 验证、审查与收口

**Files:**
- Modify: `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
- Modify: `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- Modify: `worklog/index.md`

- [x] **Step 1: 目标验证**

Run:

```bash
npm --prefix apps/web run test:e2e -- chat-settings.spec.ts --project=chromium
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py -q
```

- [x] **Step 2: 全量门禁**

Run:

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q
npm --prefix apps/web run test:e2e
```

- [x] **Step 3: 只读审查**

派发只读审查 subagent：

- 前端是否保留聊天流式响应、思考链折叠、模型选择和验证入口语义。
- 后端写入侧 warning 是否不改变章节正文落盘结构，并能安全重建索引。
- 测试是否覆盖红灯风险。

- [x] **Step 4: 更新 worklog**

记录实施结果、红绿灯、审查反馈和验证结果；若 active 主线仍未完整完成，不归档。

- [x] **Step 5: 提交前门禁**

Run:

```bash
git diff --check
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

若提交，中文提交信息建议：

```text
修复聊天移动端可访问性并补章节索引写入 warning

- 聊天页思考过程补按钮语义与长文本溢出兜底
- 章节索引写入侧损坏索引和坏条目记录 warning
- 补设计、计划和 active worklog
```

Result: PASS。`git diff --check` 无输出；`pwd` 与 `git rev-parse --show-toplevel` 均为 `/home/user01/WorkSpace/AgentProject`；远端为 `git@github.com:userzeng111/agentProject.git`；`git status --short` 已确认 `.superpowers/brainstorm/*` 为未跟踪且不纳入本批提交。

### Execution Summary

- 前端目标验证：
  - 红灯：`npm --prefix apps/web run test:e2e -- chat-settings.spec.ts --project=chromium` 曾因思考过程缺少 button 语义失败；新增 320px 用例曾因页面横向溢出失败。
  - 绿灯：`npm --prefix apps/web run test:e2e -- chat-settings.spec.ts --project=chromium`：6 passed，覆盖 Enter/Space 键盘展开折叠、长默认模型 ID、长模型显示名/provider、顶部导航 44px 触控目标和无横向滚动。
- 后端目标验证：
  - 红灯：`uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py -q` 曾因损坏 index 重建只保留当前章节失败。
  - 绿灯：`uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py -q`：13 passed, 1 skipped。
- 全量门禁：
  - `npm --prefix apps/web test`：114 passed。
  - `npm --prefix apps/web run lint`：通过。
  - `npm --prefix apps/web run build`：通过，仅保留既有 `metadataBase` warning。
  - `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：All checks passed。
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q`：389 passed, 1 skipped, 2 warnings, 4 subtests passed。
  - `npm --prefix apps/web run test:e2e`：112 passed。
- 提交前门禁：
  - `git diff --check`：无输出。
  - `pwd`：`/home/user01/WorkSpace/AgentProject`。
  - `git rev-parse --show-toplevel`：`/home/user01/WorkSpace/AgentProject`。
  - `git remote -v`：`origin git@github.com:userzeng111/agentProject.git`。
  - `git status --short`：确认本批代码、测试、设计/计划与 active worklog 文件；未跟踪 `.superpowers/brainstorm/*` 不纳入提交。
