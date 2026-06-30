# 审核页分屏与 RAG 工作区日志 Design

## 背景

当前 active 主线仍有两类剩余事项：

- UI/UX 阶段 3：审核页已接入 `ProjectShell` 与 `StageNav`，但审核材料、Agent 追踪和审核操作仍在单列长流中，桌面端扫描与决策效率不足。
- MVP 审查后续：RAG、模型、上下文缓存等异常日志已推进多批，但工作区 RAG 状态构建在 RAG 服务异常时只把错误写入响应，没有 warning 断言覆盖。

本批选择两个边界清楚的切片：审核页左右分屏、RAG workspace 状态异常 warning 覆盖。另附一个已确认低风险死代码清理：删除仅测试使用、运行时代码未调用的 `getInitialMode()`。

## 目标

1. 审核页桌面端形成“左侧审核材料、右侧审核决策”的稳定分屏。
2. 移动端继续单列展示，不产生页面级横向滚动。
3. 三类审核分支继续保留现有内容、按钮文案、提交行为和恢复行为。
4. `ProjectShell` 支持按页面选择最大宽度，默认行为不变，审核页可使用更宽布局。
5. `_build_rag_status()` 在 RAG readiness 检查异常时记录 warning，同时保持返回结构和降级语义不变。
6. 删除 `getInitialMode()` 历史 helper，保留 `ThemeMode` 与 `STORAGE_KEY`。

## 非目标

- 不改 `/review?id=` 路由。
- 不改 `GET /api/tasks/{id}/review`、`resumeTask()` 或恢复接口。
- 不改审核状态机、LangGraph、checkpoint 和归档/结果页。
- 不拆 `AgentTracePanel` 的轮次统计逻辑。
- 不做全站暗色模式、移动端底部 Tab 或 `TaskRunClient` 大拆分。
- 不删除 `TaskLogStore` supervisor helper，不评估 legacy 模型验证流式路由。

## 前端设计

新增本地布局组件 `ReviewSplitLayout`：

- 外层 `Box` 使用 MUI `sx` 响应式 CSS grid。
- `xs` 到 `md`：单列，顺序为材料区再决策区。
- `lg` 起：两列，`minmax(0, 1fr)` + `minmax(340px, 400px)`，`gap` 使用主题 spacing。
- 左侧区域 `data-testid="review-main"`，右侧区域 `data-testid="review-aside"`。
- 右侧桌面端使用 `position: sticky; top: 24px`，移动端取消 sticky。
- 两侧都设置 `minWidth: 0`，长标题、模型 ID 和正文内容由现有组件继续断词或滚动。

三类审核分支只重排，不改业务状态：

- 大纲审核左侧：分支标题、chips、大纲总纲、章节计划或 Markdown、回滚控制。
- 大纲审核右侧：`AgentTracePanel`、错误提示、审核操作、历史记录、模型选择、审核意见、通过/驳回按钮。
- 章节审核左侧：标题、chips、进度、审核摘要、章节正文。
- 章节审核右侧：`AgentTracePanel`、错误提示和审核操作。
- 验证审核左侧：标题、chips、验证摘要、问题列表。
- 验证审核右侧：`AgentTracePanel`、错误提示和审核操作。

`ProjectShell` 增加可选 `maxWidth` prop，类型沿用 MUI Container 常用值，默认仍为 `md`；审核页传 `lg`。

## 后端设计

`TaskServiceQueriesMixin._build_rag_status()` 保持现有响应字段：

- `rag_service.is_ready()` 抛异常：记录 warning，`ready=False`，`last_error=str(exc)`。
- `rag_service.readiness_error()` 抛异常：记录 warning，`ready=False`，`last_error=str(exc)`。
- 未配置 RAG 或正常未就绪路径行为不变。

日志文案需要能被测试稳定断言，例如：

- `读取 RAG 工作区就绪状态失败`
- `读取 RAG 工作区未就绪原因失败`

## 测试设计

### RED

- `review-result-archive.spec.ts`：
  - 大纲审核桌面用例断言 `review-split-layout`、`review-main`、`review-aside` 可见。
  - 用 bounding box 断言桌面端 aside 位于 main 右侧。
  - 章节和验证审核继续断言 `review-aside` 内包含“审核操作”和“审核意见”。
  - 新增 390px 移动端审核页测试，断言无横向滚动，审核意见和提交按钮可见。
- `test_task_service_workspace.py`：
  - RAG `is_ready()` 抛异常时，`workspace.rag_status.ready` 为 `False`，`last_error` 保留错误，并记录 warning。
  - RAG `readiness_error()` 抛异常时，保持 `ready=False` 和 `last_error`，并记录 warning。
- `theme-mode.test.ts`：
  - 断言 `theme-mode` 模块不再导出 `getInitialMode`，但仍导出 `STORAGE_KEY`。

### GREEN

- 实现 `ReviewSplitLayout` 并重排三类审核分支。
- `ProjectShell` 增加默认不变的 `maxWidth` prop。
- 给 RAG workspace 异常路径补 warning。
- 删除 `getInitialMode()` 与旧测试。

### 汇总验证

- `npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium`
- `npm --prefix apps/web test`
- `npm --prefix apps/web run lint`
- `npm --prefix apps/web run build`
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py -q`
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`
- 若变更影响共享页面稳定性，再跑 `npm --prefix apps/web run test:e2e` 与后端全量 pytest。

## 风险

- 三类审核分支 props 很多，重排时容易漏传 `comment`、`actionModelId`、`modelRefresh` 或 `submitting`。
- 审核页宽度扩大不能影响结果页/归档详情，因此 `ProjectShell` 默认必须不变。
- sticky 侧栏必须在移动端退化为普通流，避免遮挡内容。
- RAG warning 不能改变 `rag_status` API contract，只能增强可观测性。
