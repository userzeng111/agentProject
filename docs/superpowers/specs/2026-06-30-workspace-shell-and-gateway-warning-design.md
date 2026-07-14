# 工作台壳层与 Gateway prompt cache 日志设计

## 背景

当前 UI/UX active 已完成审核页、结果页、归档详情的 `ProjectShell` / `StageNav` 接入，但项目工作台 `/p/[projectId]` 仍在 `TaskRunClient` 内直接维护 `Container`、面包屑、状态 Chip 和主内容，导致项目级页面体验不一致。MVP 审查 active 中，`OpenAICompatibleGatewayClient._provider_prompt_cache_kwargs()` 在读取全局设置失败时直接降级为 `{}`，没有 warning，属于低风险日志覆盖缺口。

本批目标是推进两个 active 的收敛，但保持范围可控：工作台只替换壳层和阶段导航，不改任务动作、事件流、Tab 内容、恢复逻辑或路由；Gateway 只补 warning，不改 prompt cache 参数语义。

## 设计目标

- `/p/[projectId]` 工作台使用与审核页/结果页/归档详情一致的 `ProjectShell`。
- 工作台顶部展示 `StageNav`，当前阶段由任务状态映射得到，可被单元测试覆盖。
- 工作台移动端 390px 不产生横向滚动，工作台关键动作仍可点击。
- Gateway prompt cache 设置读取失败时记录 warning，并继续返回 `{}` 降级。
- 两个 active 继续保持 active，不在本批归档。

## UI 方案

在 `apps/web/src/features/task-run/task-run-state.mjs` 新增纯函数：

- `resolveWorkspaceStageNav(status)`：把工作台状态映射为 `StageNav` 所需的阶段列表和 `activeStep`。
- 阶段建议保持五步：创建、规划、审核、创作、完成。
- 映射规则：
  - `created` / `sources_ingested`：创建阶段。
  - `planning` / `waiting_outline_review`：规划阶段，其中待大纲审核仍停在规划后等待审核。
  - `waiting_chapter_review` / `waiting_verification_review` / `waiting_manual_action`：审核阶段。
  - `ready_for_batch` / `drafting` / `assembling`：创作阶段。
  - `completed`：完成阶段。
  - `failed` / `cancelled`：停留在最接近当前进度的阶段，不新增失败阶段，失败状态继续由状态 Chip 和告警表达。

在 `TaskRunClient` 中：

- 引入 `ProjectShell` 和 `StageNav`。
- `workspace` 已加载时，用 `ProjectShell` 包裹原有内容。
- `ProjectShell` 的 breadcrumbs 为“首页 / 当前任务名”，metaItems 展示状态、任务 ID、创作模型、审核模型等轻量元信息。
- 原顶部 `Breadcrumbs + Chip` 删除，状态 Chip 迁移到 `ProjectShell` actions。
- 主内容中的 `WorkflowOverviewCard`、请求摘要、Tab、Snackbar、恢复弹窗等保持原位置和语义。
- `workspace` 未加载的错误兜底暂保留 `Container`，避免扩大加载态改动。
- `ProjectShell` 面包屑需要对长不可断任务 ID 做断词和收缩处理，防止工作台标题缺失时回退到任务 ID 造成移动端横向溢出。

## Gateway 日志方案

在 `apps/agent-runtime/app/llm/gateway_client.py`：

- 使用已有模块 logger。
- `_provider_prompt_cache_kwargs()` 调用 `get_settings()` 抛异常时记录 warning：`读取 provider prompt cache 设置失败`。
- 保持返回 `{}`，不影响非 Anthropic adapter、不启用 prompt cache 和默认设置读取成功路径。

## 测试设计

前端：

- `task-run-state.test.mjs` 覆盖 `resolveWorkspaceStageNav()` 对主要状态的 activeStep 映射。
- `task-state-branches.spec.ts` 在每个状态分支断言 `project-shell`、`stage-nav` 可见，且当前阶段可见。
- 新增移动端工作台无横向滚动测试，390px 访问 `/p/{taskId}`，断言 `scrollWidth <= clientWidth`，并保留调试 Tab 或关键按钮可见。
- 移动端无横向滚动测试使用标题缺失且长不可断任务 ID 的 fixture，覆盖 `ProjectShell` 面包屑回退路径。
- `task-workspace-actions.spec.ts` 保持原动作 API 测试，确认壳层替换不影响按钮行为。

后端：

- `test_settings_and_gateway_fail_fast.py` 新增 `get_settings()` 抛异常时的 warning 测试。
- 断言 `_provider_prompt_cache_kwargs(AnthropicAdapter()) == {}` 且日志包含 `读取 provider prompt cache 设置失败`。
- 保留协议 resolver、网关 URL、JSON 解析等既有测试。

## 风险与边界

- 不改 `/p/[projectId]` 静态壳和 `project-workspace-client.tsx` 的 pathname 解析。
- 不改 `runTask`、`continueTask`、`recoverTask`、`cancelTask`、`deleteTask` 调用与 payload。
- 不改 SSE fallback 路径、事件流状态转换或恢复对话框。
- 不拆 `TaskRunClient` 内部大组件；大组件拆分留给后续阶段。
- 不删除 test-only 组件，不清理 `TaskLogStore`、legacy 模型验证流式路由、动态 Agent 栈或 `StoryEngine`。

## 验证范围

- 前端局部：`npm --prefix apps/web test -- src/features/task-run/task-run-state.test.mjs src/components/stage-nav.test.mjs`。
- 前端 E2E：`npm --prefix apps/web run test:e2e -- task-state-branches.spec.ts --project=chromium`、`npm --prefix apps/web run test:e2e -- task-workspace-actions.spec.ts --project=chromium`。
- 后端局部：`uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py -q`。
- 汇总门禁：前端 test/lint/build/E2E，后端 ruff 与全量 pytest。
