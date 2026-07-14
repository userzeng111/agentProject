# 导航玻璃态暗色与章节预览 warning 设计

## 背景

当前 active 仍有两条主线：

- UI/UX：阶段 4 暗黑模式全页面精调、移动端布局、可访问性与大组件拆分仍需继续推进。
- MVP 审查：运行时死代码与关键异常 warning 覆盖仍需继续分低风险批次清理。

本批只做两个互不依赖的小切片：全局导航与 `.glass-card` 玻璃态暗色精调，以及章节预览读取损坏章节文件时补 warning。两者文件范围独立，不改任务状态机、模型验证、动态 Agent、事件流、恢复语义或章节 API 返回结构。

## 设计范围

### 全局导航与玻璃态暗色精调

目标文件：

- `apps/web/src/components/app-header.tsx`
- `apps/web/src/app/globals.css`
- `apps/web/e2e/home-create.spec.ts`
- `apps/web/e2e/task-state-branches.spec.ts`

当前 `ClientLayout` 已按主题切换页面背景，但 `AppHeader` 仍固定使用浅色 `rgba(255, 250, 242, 0.80)` 和浅色边框。`.glass-card` 也通过全局 CSS 变量固定浅色，`WorkflowOverviewCard` 正在使用该 class。暗色模式下这些区域会形成浅色浮层，和近期已完成的工作流图谱节点暗色精调不一致。

本批将：

- `AppHeader` 增加稳定定位 `data-testid="app-header"`。
- `AppHeader` 背景、边框、hover/active 导航背景改为基于 MUI theme mode 派生。
- `.glass-card` 通过 `@media (prefers-color-scheme: dark)` 提供系统暗色兜底，并让 `WorkflowOverviewCard` 通过 `sx` 回补应用内 theme mode 的真实暗色背景和边框，避免只依赖系统媒体查询。
- 保留现有导航链接、移动端文案隐藏、可访问名称和路由语义。

测试策略：

- 扩展首页移动端 E2E，设置 `localStorage.theme-mode = "dark"`，断言 `app-header` 背景不是旧浅色，且页面无横向滚动。
- 扩展工作台暗色图谱 E2E，断言 `workflow-overview-card` 背景不是旧浅色，且页面无横向滚动。

### 章节预览损坏文件 warning

目标文件：

- `apps/agent-runtime/app/application/task_service/continuation.py`
- `apps/agent-runtime/tests/test_recovery_chapter_progress.py`

当前 `TaskService.get_current_chapters()` 读取 `chapters/index.json` 失败时直接返回 `[]`；读取单章 `chapters/NN.json` 失败时直接回退到 index item。这些返回语义对工作台预览是合理降级，但缺少 warning，排查磁盘损坏或写入中断时不可观测。

本批将：

- `index.json` 存在但 JSON 损坏或格式不正确时记录 `读取章节索引失败 task_id=%s path=%s` warning，并继续返回 `[]`。
- 单章 JSON 存在但读取或解析失败时记录 `读取章节文件失败 task_id=%s path=%s` warning，并继续回退 index item。
- 不改变 `index.json` 不存在时的静默空列表语义。
- 不改变 `/api/tasks/{task_id}/chapters` 返回结构。

测试策略：

- 构造损坏 `chapters/index.json`，断言返回 `[]` 且记录 warning。
- 构造有效 index 但损坏单章 JSON，断言返回 index item 且记录 warning。

## 不在本批处理

- 不做全站暗黑模式一次性扫尾。
- 不改聊天页移动端可访问性。
- 不拆 `TaskRunClient` 实时日志区。
- 不清理 `TaskLogStore`。
- 不删除 legacy `/api/model-validation/stream`。
- 不触碰动态 Agent 栈或 `StoryEngine` 主链路。

## 验收标准

- 暗色模式下全局导航和工作流玻璃卡片不再使用旧浅色背景。
- 暗色 390px 首页和工作台不产生横向滚动。
- 章节索引损坏时记录 warning，仍返回 `[]`。
- 单章文件损坏时记录 warning，仍回退 index item。
- 自动化测试、lint、build、后端 ruff/pytest 与目标 E2E 通过。
- active worklog 更新；若主线仍有未完成项，则不提前归档。
