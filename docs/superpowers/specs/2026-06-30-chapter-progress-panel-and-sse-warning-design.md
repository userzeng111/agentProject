# 工作台章节进度面板与 SSE warning 设计

## 背景

当前仍有两个 active 主线需要继续推进：

- UI/UX 后续阶段：阶段 3 剩余“章节与归档体验进一步重构”，阶段 4 剩余“大组件拆分、可访问性、移动端布局”。
- MVP 审查后续：继续补关键运行时异常路径 warning/error 覆盖，并保留主链路语义。

本批只做两个低耦合切片：工作台“章节进度”面板最小拆分，以及任务 SSE 终态检查异常 warning 覆盖。

## 目标

1. 从 `TaskRunClient` 中抽出章节进度面板和章节正文弹窗，降低工作台主组件体积。
2. 给章节进度面板补稳定定位、可访问名称、长标题断词与移动端无横向滚动保障。
3. 保留当前 `/api/tasks/{task_id}/chapters` 懒加载正文语义，不改任务动作、事件流、恢复流程或路由。
4. `stream_task_events()` 中 `task_service.store.get(task_id)` 异常时记录一次 warning，并继续等待事件队列或 keep-alive，不改变 SSE 对外事件顺序。

## UI 设计

新增 `apps/web/src/features/task-run/chapter-progress-panel.tsx`：

- 输入 `chapters`、`expanded`、`selectedChapter`、`dialogOpen`、`onSelectChapter`、`onCloseDialog` 与 `formatEventTime`。
- 面板根节点提供 `data-testid="chapter-progress-panel"`。
- 列表使用 `aria-label="章节进度列表"`。
- 每个章节按钮使用 `aria-label="查看第 N 章正文：标题"`。
- 每个进度条使用 `aria-label="第 N 章进度"`。
- 章节正文弹窗使用 `aria-labelledby` 指向标题，关闭按钮使用 `aria-label="关闭章节正文"`。
- 标题和摘要统一使用 `overflowWrap: "anywhere"`，避免长章节标题在 390px 宽度下撑开页面。

`TaskRunClient` 继续负责：

- `buildChapterProgress()` 调用。
- `getCurrentChapters()` 懒加载正文。
- `selectedChapter` 与弹窗 open/close 状态。

## 后端设计

`apps/agent-runtime/app/api/routes.py` 中 `event_stream()` 保留现有结构：

1. 先发送 `snapshot`。
2. 循环中先尝试读取 `task_service.store.get(task_id)` 判断终态。
3. 读取失败时只记录一次 warning，后续循环不重复刷日志。
4. 继续等待 queue；queue 收到 `task.completed` / `task.cancelled` / `task.failed` 时仍发送 `task.event` 与 `task.done` 并结束。
5. `finally` 中继续调用 `unsubscribe_task_events()`。

warning 文案为中文，包含 `task_id`，不包含敏感 payload。

## 测试策略

前端先写 E2E 红灯：

- 在 `task-state-branches.spec.ts` 构造包含 `chapter.saved` 的 workspace，并让 `/chapters` 返回正文。
- 点击“章节进度”Tab 后断言 `chapter-progress-panel` 可见。
- 通过 role/name 点击章节按钮，断言正文弹窗可见。
- 通过 role/name 定位关闭按钮并关闭弹窗。
- 390px 视口下断言页面没有横向滚动。

后端先写 API 红灯：

- 构造 fake task service，`build_sse_snapshot()` 成功、`subscribe_task_events()` 返回 queue、`store.get()` 抛异常。
- queue 中预置 `task.completed`。
- 请求 `/api/tasks/{task_id}/events/stream`。
- 断言响应包含 `snapshot`、`task.event`、`task.done`。
- 用 `assertLogs("app.api.routes", level="WARNING")` 断言出现 SSE 终态检查 warning。

## 非目标

- 不重写工作台 Tab 结构。
- 不改 `/p/[projectId]` 路由。
- 不改章节正文 API 契约。
- 不清理全站暗黑模式硬编码。
- 不删除 legacy 模型验证路由、动态 Agent 栈或 `StoryEngine` 代码。
