# 工作流图谱暗黑精调与 test-only 组件清理设计

## 背景

当前 active 仍有两条主线：

- UI/UX：阶段 4 剩余暗黑模式全页面精调、移动端布局、可访问性与大组件拆分。
- MVP 审查：剩余运行时死代码清理与关键异常日志覆盖。

本批只做两个低风险切片：工作台 `WorkflowOverviewCard` 暗黑模式精调，以及前端 `components/` 下只被 import-only 测试引用的 test-only 组件清理。两者互不依赖，不改后端业务语义，不改任务执行、SSE、审核、恢复或模型验证流程。

## 设计范围

### 工作流图谱暗黑模式

目标文件：

- `apps/web/src/features/task-run/workflow-overview-card.tsx`
- `apps/web/e2e/task-state-branches.spec.ts`

当前图谱节点、边标签、画布、MiniMap 和空态仍有浅色硬编码，例如 `#fffaf2`、`rgba(255,250,242,...)`、`#1d2a27`。本批将这些样式收敛到主题感知 token：

- 使用 MUI `sx` callback 或组件内 theme mode 派生样式。
- React Flow 使用 `colorMode`、`Background` color、`MiniMap` `bgColor` / `nodeColor` / `nodeStrokeColor` / `maskColor` 等官方 props。
- 节点、边、画布和空态保留现有结构、尺寸、缩放与交互。
- 增加稳定定位 `data-testid="workflow-overview-card"` 与图谱区域 `aria-label`，便于 E2E 和辅助技术识别。

参考约束：

- MUI 文档确认 `sx` 支持 theme callback 与模式化样式。
- React Flow 文档确认 `ReactFlow` 支持 `colorMode`，`MiniMap` 支持 `bgColor`、`nodeColor`、`nodeStrokeColor`、`maskColor`。
- UI skill 约束本批只采用暗色低眩光、高对比、可访问和响应式原则，不引入新的页面风格。

### test-only 组件清理

目标文件：

- 删除 `apps/web/src/components/loading-overlay.tsx` 与对应 import-only 测试。
- 删除 `apps/web/src/components/page-container.tsx` 与对应 import-only 测试。
- 删除 `apps/web/src/components/model-select.tsx` 与对应 import-only 测试。
- 删除 `apps/web/src/components/confirm-dialog.tsx` 与对应 import-only 测试。
- 删除 `apps/web/src/components/decision-bar.tsx` 与对应 import-only 测试。
- 删除 `apps/web/src/components/stage-badge.tsx` 与对应 import-only 测试。
- 删除 `apps/web/src/components/progress-bar.tsx` 与对应 import-only 测试。
- 删除 `apps/web/src/components/skeleton-grid.tsx` 与对应 import-only 测试。
- 删除 `apps/web/src/components/empty-state.tsx` 与对应 import-only 测试。

清理前用 `rg` 排除测试文件确认没有生产调用。清理后再次用相同查询确认没有残留引用，并用前端测试、lint、build 兜底。

## 不在本批处理

- 不做全站暗黑模式一次性清理。
- 不拆 `TaskRunClient`、`TaskReviewClient` 或 `ChatClient` 主体。
- 不删除 legacy `/api/model-validation/stream`，因为这是外部 API 表面变更。
- 不触碰 `TaskLogStore`、动态 Agent 栈或 `StoryEngine` 主链路。
- 不改后端路由、模型兼容性验证、任务状态机或任务持久化。

## 测试策略

- 图谱暗色红灯：新增/扩展 E2E，设置 `localStorage["theme-mode"]="dark"`，打开 390px 工作台，断言图谱卡片可见、页面无横向滚动，并检查 React Flow 节点背景不再是旧浅色硬编码。
- test-only 清理红灯：删除前先运行精确 `rg`，证明目标组件仅测试引用；删除后同样确认没有残留生产引用。
- 绿灯验证：`npm --prefix apps/web test`、`npm --prefix apps/web run lint`、`npm --prefix apps/web run build`、目标 E2E。
- 因本批不改后端业务代码，只在最终联动门禁跑后端 ruff 与 pytest。

## 验收标准

- 暗色模式下工作流图谱节点、边标签、画布、MiniMap 和空态不再使用旧浅色硬编码。
- 390px 工作台页面不产生横向滚动。
- 图谱卡片有稳定测试定位和可访问标签。
- 目标 test-only 组件及其 import-only 测试已删除，生产代码无残留引用。
- 自动化测试通过，active worklog 更新；两个 active 主线仍有后续任务，本批不归档。
