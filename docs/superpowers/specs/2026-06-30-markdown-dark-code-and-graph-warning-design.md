# Markdown 暗色代码块与 graph state warning 设计

## 背景

当前 active 仍有两条主线：

- UI/UX：阶段 3/4 仍需继续做阅读体验、暗黑模式、移动端和可访问性收尾。
- MVP 审查：仍需继续补关键异常 warning 覆盖，并谨慎处理运行时死代码。

本批只做两个小切片：`MarkdownContent` 暗色代码块精调，以及 `TaskService._graph_state_values()` 静默异常补 warning。两者互不依赖，不改任务状态机、模型验证、动态 Agent、事件流、恢复语义或结果数据结构。

## 设计范围

### MarkdownContent 暗色代码块

目标文件：

- `apps/web/src/components/markdown-content.tsx`
- `apps/web/src/components/markdown-content.test.mjs`
- `apps/web/e2e/review-result-archive.spec.ts`

当前 `MarkdownContent` 的行内 code 使用 `rgba(0,0,0,0.06)`，正文和大纲 code fence 使用 `grey.100`，在暗色模式下会形成浅色块，影响结果页、归档详情和章节阅读器的阅读体验。本批将代码样式收敛为主题感知：

- 行内 code 改为 MUI `Box component="code"`，使用 `sx` callback 按 `theme.palette.mode` 派生背景、边框和文字颜色。
- code fence 抽出共享 `CodeBlock`，保留 article/outline 两种尺寸差异，但背景、边框、文字颜色按主题派生。
- code fence 保持 `overflowX: "auto"`、`maxWidth: "100%"` 和移动端不撑宽页面。
- 保留危险链接拦截、安全图片 data URI、外链 `target/rel` 等现有安全语义。

测试策略：

- 新增/扩展组件单测，覆盖危险链接和安全图片语义不变，并断言渲染结果不再包含旧浅色代码块硬编码。
- 扩展结果页 E2E：暗色 390px 下使用包含 code fence 的 result/chapter fixture，断言 `novel-reader-content pre` 可见、背景不是浅灰/浅米色，并保持页面无横向滚动。

### graph state warning

目标文件：

- `apps/agent-runtime/app/application/task_service/core.py`
- `apps/agent-runtime/tests/test_task_service_review_resume.py`

当前 `_graph_state_values()` 对 `workflow_engine.get_state()` 异常直接返回 `{}`，调用方依赖 `{}` 降级继续执行，但缺少可观测日志。本批只补 warning：

- 捕获异常时记录 `读取工作流 checkpoint 状态失败 task_id=%s` warning，并保留 `exc_info=True`。
- 返回值继续为 `{}`，保持 `_sync_checkpoint_with_db()`、恢复回填和 resume 流程现有降级语义。
- 不改 `workflow_engine` 接口、不改变异常传播、不增加重试。

测试策略：

- 新增服务层单测，用 fake workflow engine 让 `get_state()` 抛异常，断言返回 `{}` 且 warning 被记录。
- 相关目标测试通过后，再跑后端 ruff、全量 pytest 与前端联动门禁。

## 不在本批处理

- 不做全站暗黑模式扫尾。
- 不替换 `AppHeader` emoji logo 或导航结构。
- 不拆 `TaskRunClient`、`TaskReviewClient`、`ChatClient` 等大组件。
- 不删除 legacy `/api/model-validation/stream`。
- 不清理 `TaskLogStore`、动态 Agent 栈或 `StoryEngine` 主链路。

## 验收标准

- 暗色模式下结果页/归档详情/章节阅读器中的 Markdown code fence 不再使用旧浅色背景。
- Markdown 安全链接和图片过滤语义保持不变。
- 暗色 390px 结果页阅读器不产生横向滚动。
- `_graph_state_values()` 异常时记录 warning，返回 `{}` 语义不变。
- 自动化测试、lint、build、E2E、后端 ruff/pytest 通过；active worklog 更新但不归档。
