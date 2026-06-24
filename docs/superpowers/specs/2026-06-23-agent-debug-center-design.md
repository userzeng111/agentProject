# Agent 运行调试中心设计

## 1. 背景

AgentProject 当前已经具备小说创作长任务、LangGraph 工作流、人工审核中断恢复、自动/动态多 Agent 审核、RAG 增强、SSE 实时事件、模型切换与任务归档能力。随着功能持续增加，用户在运行任务时遇到“卡住”“后端掉线”“审核结果异常”“RAG 是否参与”“LLM 慢在哪里”等问题，需要一个任务级调试入口快速定位问题。

本设计聚焦首批能力：在现有任务工作台内新增只读“调试”标签页，帮助用户判断当前任务是否正常、卡在哪里、慢在哪里、是否需要恢复，以及有哪些证据可查看。

## 2. 已确认决策

- 第一阶段先做：Agent 运行调试中心。
- 入口形态：A 方案，嵌入现有任务工作台。
- 信息密度：B 方案，均衡诊断页。
- 首批不做独立 `/debug` 全局页面。
- 首批只读诊断，不触发 LLM/RAG 重跑，不改变任务状态。
- 后续再补：Supervisor 调度实化、可靠任务队列、显式状态转移表。

## 3. 目标

首批调试页要解决以下问题：

- 用户打开某个任务工作台后，能直接看到任务当前健康结论。
- 用户能区分任务是运行正常、等待人工、可恢复异常、已终止，还是状态不一致。
- 用户能看到 SSE 是否正常、最近事件是否继续更新，避免把正常终态或限流误判为后端掉线。
- 用户能看到 LLM 最慢阶段、token、缓存命中、重试/修复、JSON 解析失败等摘要。
- 用户能看到自动审核 Agent 的最近一轮结果、评分、问题数和综合裁决。
- 用户能看到上下文预算、压缩、响应缓存和 RAG 参与状态。
- 用户能看到状态对账摘要与证据链接，方便进一步查文件或事件。

## 4. 非目标

首批明确不做：

- 独立全局 `/debug` 页面。
- 完整日志浏览器。
- 事件分页 API。
- LLM exchange 全量列表。
- 完整 prompt 或 raw response 默认展示。
- 跨任务成本报表。
- Prometheus/APM/分布式追踪。
- 可靠任务队列。
- 显式状态转移表。
- Supervisor 真实调度。
- 一键自动修复所有问题。

## 5. 用户入口

在任务工作台 `TaskRunClient` 中增加“调试”标签页或等价区域，与现有运行概览、事件流、Supervisor 信息并列。

首批不新增顶部导航入口，也不从首页任务卡额外跳转独立调试页。用户仍先进入某个任务工作台，再查看该任务的调试页。

## 6. 页面结构

调试标签页由七个模块组成。

### 6.1 诊断结论

展示任务整体健康判断：

- 运行正常
- 等待用户
- 可恢复异常
- 已终止
- 状态不一致

同时展示：

- 当前判断说明。
- 判断依据摘要。
- 推荐下一步动作。

推荐动作只跳转或提示，不直接改变状态。例如跳审核页、打开现有恢复弹窗、手动刷新、查看证据链接。

诊断结论必须由确定性规则派生，按以下优先级从高到低命中，命中后不再继续降级到低优先级结论：

| 优先级 | 结论 | 判定规则 | 推荐动作 |
| --- | --- | --- | --- |
| 1 | 状态不一致 | `state_check.conflicts` 存在 `error` 级冲突，例如等待审核状态但没有 `pending_review_summary.present`、终态任务仍有活动运行证据、章节进度与当前阶段硬冲突 | 查看状态对账与证据链接 |
| 2 | 可恢复异常 | `allowed_actions` 或可用 `recovery_options` 包含恢复动作，或状态为 `waiting_manual_action` 且存在恢复契约 | 打开现有恢复弹窗 |
| 3 | 等待用户 | 状态为 `created`、`sources_ingested`、`ready_for_batch`、`waiting_outline_review`、`waiting_chapter_review`、`waiting_verification_review`，且没有更高优先级异常 | 启动、继续创作或进入审核页 |
| 4 | 已终止 | 状态为 `completed`、`cancelled`，或状态为 `failed` 但没有可用恢复动作，且没有状态不一致 | 查看结果、归档或错误摘要 |
| 5 | 运行正常 | 状态为 `planning`、`drafting`、`assembling`，且没有状态不一致或可恢复异常 | 继续观察 |
| 6 | 证据不足 | 缺少判断所需字段，无法稳定归类 | 手动刷新并查看最近事件 |

SSE 连接状态只影响“实时连接”模块和诊断说明，不能单独把运行中任务判定为“状态不一致”。只有当 SSE 证据与任务状态、事件、恢复契约形成硬冲突时，才进入“状态不一致”。

### 6.2 实时连接

展示 SSE 连接状态：

- 连接中
- 已连接
- 正常终止
- 重连中
- 连接失败

展示最近事件类型、最近事件时间、重连次数、当前使用的事件流路径。终态正常关闭不能显示为异常断线。

### 6.3 LLM 诊断

从 `llm_report` 和近期事件中展示：

- 请求次数。
- token 总量。
- 按阶段耗时。
- 最慢步骤。
- 最慢首 token。
- 最近模型。
- cache hit 摘要。
- retry/repair 摘要。
- JSON parse failed 摘要。

若 provider 没有返回 usage，页面显示“暂无 usage 数据”，不能误报为异常。

### 6.4 Agent Trace

展示自动审核或动态审核相关信息：

- 最近审核轮次。
- 子 Agent 成功/失败数量。
- 子 Agent 评分。
- 问题数与警告数。
- 综合裁决。
- 最近一轮摘要。

首批优先复用 `auto_review_trace`、`agent_runs` 和现有 `AgentTracePanel`/`trace-rounds` 逻辑。若没有 trace，显示空态说明。

### 6.5 上下文 / RAG

展示：

- 上下文预算使用情况。
- 是否触发压缩。
- 响应缓存状态。
- 模型上下文窗口能力。
- RAG 是否启用。
- RAG 是否 ready。
- 最近检索是否失败。
- 是否有上下文注入证据。

首批以已有 `context_status`、`response_cache_status`、`request_preview`、`recent_events` 为主，并允许在 `WorkspaceResponse` 中新增最小 `rag_status` 只读摘要。首批不新增复杂 RAG 命中详情接口。

`rag_status` 的职责是给调试页稳定展示任务级 RAG 状态，不承担完整资料库管理能力。

### 6.6 状态对账

展示关键状态是否一致：

- `TaskRecord.status`
- `pending_review_summary`
- `novel_progress`
- `supervisor_plan`
- 恢复契约字段
- 最近事件阶段

首批状态对账由前端纯函数从 `WorkspaceResponse` 派生。若数据缺失，显示“证据不足”，不直接判定异常。

状态对账至少输出：

- `status`: `ok` / `warning` / `error` / `unknown`
- `items`: 对账项列表，每项包含 `label`、`status`、`summary`、`evidence`
- `conflicts`: 只包含会影响诊断结论的硬冲突

`pending_review_summary` 是首批允许新增的最小后端只读字段，用来避免前端根据状态和事件猜测审核上下文。

### 6.7 最近事件与证据链接

展示最近关键事件摘要：

- 事件时间。
- 事件类型。
- 阶段。
- 简短消息。
- 相关 `md_ref` / `json_ref`。

证据链接包括但不限于：

- `request.json`
- `trace/current.json`
- context history
- artifact index
- 事件引用文件

默认只展示引用与摘要，不展开完整 prompt、完整 raw response 或全文内容。

## 7. 数据来源

首批优先复用现有接口：

- `GET /api/tasks/{task_id}/workspace`
- `GET /api/tasks/{task_id}/events/stream`
- `GET /api/tasks/{task_id}/files/{path}`
- `GET /api/file-text`

核心数据字段：

- `WorkspaceResponse.meta`
- `WorkspaceResponse.recent_events`
- `WorkspaceResponse.active_trace_summary`
- `WorkspaceResponse.request_preview`
- `WorkspaceResponse.context_status`
- `WorkspaceResponse.response_cache_status`
- `WorkspaceResponse.llm_report`
- `WorkspaceResponse.novel_progress`
- `WorkspaceResponse.supervisor_plan`
- `WorkspaceResponse.agent_runs`
- `WorkspaceResponse.auto_review_trace`
- 恢复契约字段

首批不新增后端 debug API。但为了让诊断规则确定、可测试，首批允许在 `WorkspaceResponse` 中补充以下最小只读字段：

### 7.1 `pending_review_summary`

字段建议：

```json
{
  "present": true,
  "review_type": "chapter_pair_review",
  "stage": "waiting_chapter_review",
  "batch_index": 4,
  "revision_count": 1,
  "outline_phase": "",
  "summary": "等待第 5-6 章审核"
}
```

要求：

- 不返回完整待审核正文。
- 不返回完整 prompt。
- 仅返回调试页对账所需的类型、阶段、批次和摘要。
- 当 `task.pending_review` 为空时返回 `present: false`。

### 7.2 `rag_status`

字段建议：

```json
{
  "enabled": true,
  "ready": true,
  "source": "workspace",
  "summary": "RAG 已启用且索引可用",
  "last_query_stage": "drafting",
  "last_error": "",
  "injected": true
}
```

数据来源优先级：

1. `RagService.is_ready()` 与配置开关，用于 `enabled`、`ready`。
2. `recent_events` 中的 RAG/context 相关事件，用于 `last_query_stage`、`last_error`、`injected`。
3. 若无法判断最近检索与注入状态，字段保留为空或 `unknown`，页面显示“暂无最近检索证据”。

要求：

- 不返回完整检索命中文本。
- 不返回完整上下文。
- 不替代设置页的 RAG 索引健康详情。
- 不触发重建或检索。

除上述两个最小字段外，首批不新增调试 API、不新增事件分页、不新增 runtime 聚合接口。

## 8. 前端组件设计

建议新增或抽取：

- `task-run/debug-panel.tsx`
- `task-run/debug-diagnostics.ts`
- `task-run/debug-diagnostics.test.mjs`

`debug-panel.tsx` 负责 UI 展示。

`debug-diagnostics.ts` 负责从 `WorkspaceResponse` 派生诊断：

- 整体健康状态。
- SSE 状态标签。
- LLM 摘要。
- Agent Trace 摘要。
- RAG/上下文摘要。
- 状态对账结果。
- 证据链接列表。

应尽量复用现有：

- `WorkflowOverviewCard`
- `buildWorkflowGraph`
- `buildAgentDispatchGraph`
- `buildThinkingGroups`
- `trace-rounds.mjs`
- `RecoveryDialog`
- `MarkdownContent`

如果现有局部组件不方便复用，先抽取小组件，避免复制大块 UI 逻辑。

## 9. 实时刷新策略

调试页跟随工作台已有刷新机制：

- 初始加载调用 `getWorkspace(taskId)`。
- SSE 收到 `snapshot`、`task.event`、`task.done` 后刷新 workspace。
- SSE 正常终态关闭显示为“正常终止”。
- SSE 异常失败进入重连或手动刷新状态。

首批不新增轮询开关。若 SSE 失败，保留现有手动刷新动作。

## 10. 错误处理

- `WorkspaceResponse` 字段缺失：显示空态，不报错。
- `llm_report` 为空：显示“暂无 LLM usage 数据”。
- `auto_review_trace` 为空：显示“暂无 Agent 审核轨迹”。
- `context_status` / `response_cache_status` 为空：显示“暂无上下文/缓存快照”。
- RAG 未启用或未 ready：显示明确原因，不判定任务失败。
- 证据链接读取失败：显示链接读取失败，不影响其他模块。

## 11. 安全与隐私

- 默认不展示完整 prompt。
- 默认不展示完整 raw response。
- 默认不展示完整上传素材或全文章节。
- 只展示摘要、hash、引用路径和短 preview。
- 若后续增加原始诊断查看，必须受配置开关控制。

## 12. 测试策略

前端单元测试：

- 运行正常任务诊断。
- 等待审核任务诊断。
- `waiting_manual_action` 可恢复异常诊断。
- completed/cancelled/failed 终态诊断。
- `llm_report` 为空时的降级。
- `auto_review_trace` 为空时的降级。
- context/RAG 状态缺失时的降级。
- 状态对账证据不足时不误报异常。
- 诊断优先级：状态不一致优先于可恢复异常，可恢复异常优先于等待用户，等待用户优先于终态/运行正常。
- `pending_review_summary.present=false` 且任务处于等待审核状态时，应输出 `error` 级状态对账冲突。
- `rag_status` 缺失或 `unknown` 时，RAG 模块显示证据不足，不影响整体任务健康结论。

前端构建验证：

- `npm --prefix apps/web test`
- `npm --prefix apps/web run build`

接口 smoke：

- `/api/tasks/{task_id}/workspace`
- `/api/tasks/{task_id}/events/stream`
- `WorkspaceResponse.pending_review_summary`
- `WorkspaceResponse.rag_status`
- 工作台页面可打开并切换到调试标签。

## 13. 后续演进

第二阶段可补：

- 独立 `/debug` 全局页面。
- `GET /api/debug/tasks/{task_id}` 聚合接口。
- `GET /api/debug/tasks/{task_id}/events` 分页过滤接口。
- LLM exchange 列表。
- RAG 命中详情。
- 运行态 `/api/debug/runtime`。

第三阶段与后续计划衔接：

- Supervisor 调度实化后，将队列 job、Agent run、LLM exchange 挂到对应 subtask。
- 可靠任务队列落地后，将 `_active_runs` 替换为 queued/running/leased/retrying/dead_letter 等状态。
- 显式状态转移表落地后，调试页直接展示 `from/to/guard/action/result`，标出非法迁移、缺失事件、状态滞留和重复提交。
