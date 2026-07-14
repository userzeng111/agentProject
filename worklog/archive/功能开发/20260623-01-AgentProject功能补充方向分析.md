# AgentProject 功能补充方向分析

## 用户原始诉求

多 agent 并行推进，头脑风暴分析：AgentProject 持续增加功能后，需要先说明当前项目使用的技术以及这些技术在项目中承担的作用，再说明还可以增加哪些补充功能、这些功能可以为项目带来什么价值。

## 当前状态

已完成多 agent 并行只读分析，进入讨论阶段；本轮不修改业务代码。

## 只读分析结论摘要

- 当前项目不只是“小说 Agent Demo”，更准确是“以小说创作为主案例的 Agent 工作流样板平台”。
- 后端已形成 FastAPI + LangGraph + LangChain Prompt + 自定义 LLM 网关 + TaskService + SQLite/文件双持久化 + RAG + 自动/动态多 Agent 审核的运行时。
- 前端已形成 Next.js 14 + React + MUI + React Flow 的任务工作台，覆盖创建、运行、审核、结果、归档、聊天、设置、RAG 重建、模型协议配置和 Agent 流程可视化。
- RAG 子项目已具备 BGE GGUF + llama.cpp + FAISS + SQLite 的本地索引、检索、问答、更新、删除、重建 CLI，并已被后端用于大纲、章节和聊天增强。
- 当前主要短板不在“能否写小说”，而在平台化能力：通用模板、Supervisor 实调度、Agent 级隔离、运行调试中心、评测回归、RAG 管理、可靠任务队列、显式状态转移和多用户边界。

## 候选功能方向

- P0：工作流模板/案例库、Supervisor 调度实化、Agent 级上下文与恢复点、可靠任务队列、显式状态转移表。
- P1：动态编排 UI、Agent 运行调试中心、质量评测面板、RAG 资料库管理、LLM 网关可靠性与成本观测。
- P2：Agent 插件/技能注册、局部修订闭环、导出分享包、多用户/权限/空间隔离、文档站与教程路径。

## 用户优先级确认

- 第一阶段先推进：Agent 运行调试中心。
- 后续补充：Supervisor 调度实化。
- 再后续补充：可靠任务队列 + 显式状态转移表。

## Agent 运行调试中心讨论状态

进入头脑风暴与方案设计阶段；当前需要先确认调试中心的目标用户、入口形态、首批数据范围和页面信息架构。

## Agent 运行调试中心入口选择

- 用户选择：A 方案，嵌入现有任务工作台。
- 首批形态：在任务工作台中新增“调试”标签页或等价区域，聚焦单任务诊断，不先做全局 `/debug` 页面。
- 设计约束：
  - 首批只读诊断，不触发 LLM/RAG 重跑，不改变任务状态。
  - 优先复用现有 `/api/tasks/{task_id}/workspace`、SSE、`llm_report`、`auto_review_trace`、`agent_runs`、`supervisor_plan`、`context_status`、`response_cache_status`。
  - 暂不做完整 APM、Prometheus、队列重构、状态机重构、Supervisor 实调度。

## Agent 运行调试中心信息密度选择

- 用户选择：B 方案，均衡诊断页。
- 首批包含：诊断结论、实时连接、LLM 摘要、Agent Trace 摘要、上下文/RAG、状态对账、证据链接、最近事件。
- 首批不包含：完整日志浏览器、完整 prompt/raw response 展示、跨任务成本报表、复杂向量可视化、一键自动修复。

## 设计规格落盘

- 已落盘设计文档：`docs/superpowers/specs/2026-06-23-agent-debug-center-design.md`
- 规格审阅发现 3 个阻塞问题：诊断结论缺少确定性优先级、`pending_review` 数据源不明确、RAG 诊断数据源不明确。
- 已修复规格：补充诊断优先级表，明确首批允许在 `WorkspaceResponse` 增加 `pending_review_summary` 与 `rag_status` 两个最小只读字段，并补充对应测试要求。
- 规格复审结果：Approved，无阻塞问题。
- 复审建议：实现时统一 `state_check` 命名；RAG 最近检索失败首批可按 `unknown` 降级，后续再补更精确事件。
- 当前阶段：等待用户确认后，进入实施计划。

## Agent 运行调试中心实施计划

- 用户已确认进入下一阶段。
- 已落盘实施计划：`docs/superpowers/plans/2026-06-23-agent-debug-center-implementation.md`
- 计划范围：在现有任务工作台新增只读“调试”标签页；后端仅补充 `WorkspaceResponse.pending_review_summary` 与 `WorkspaceResponse.rag_status` 两个最小摘要字段。
- 执行边界：首批不做全局 `/debug`、事件分页、完整日志浏览器、LLM exchange 全量列表、Supervisor 实调度、可靠任务队列或显式状态转移表。
- 版本门禁：当前仓库未发现 `Cargo.toml`，因此无法执行 Cargo patch +1；进入代码修改前需再次核对。
- 第一轮计划审阅结果：Issues Found。
- 已修订计划：
  - 状态对账扩展到 `pending_review_summary`、`novel_progress`、`supervisor_plan`、恢复契约与最近事件阶段。
  - LLM 诊断补充请求次数、阶段耗时、最近模型、缓存命中、重试/修复和 JSON 解析失败摘要。
  - RAG 摘要补充 context snapshot 注入证据兜底，不只依赖 RAG 事件。
  - Agent Trace 明确复用 `trace-rounds.mjs`，展示最近轮次、成功/失败数量、评分、问题/警告数与裁决。
  - 实时连接识别现有“任务已完成/已取消/失败，事件流已关闭”终态文案。
- 当前状态：实施计划已修订，准备第二轮 plan reviewer 复审；尚未进入业务代码修改。
- 第二轮计划复审结果：Approved，无阻塞问题，无补充建议。
- 当前状态：实施计划已通过审阅，等待用户确认实施方式后再进入代码修改。

## Agent 运行调试中心实施状态

- 用户选择：Subagent-Driven（方案 1）。
- 执行前门禁：
  - `pwd`：`/home/user01/WorkSpace/AgentProject`
  - `git rev-parse --show-toplevel`：`/home/user01/WorkSpace/AgentProject`
  - 当前分支：`uxuiFix`
  - `find . -path '*/Cargo.toml' -print`：无输出，无法执行 Cargo patch +1 版本规则。
  - 当前 `git status --short` 仅显示此前落盘的规格、计划、静态草图和 worklog 未跟踪文件。
- 执行约束：子 agent 不提交代码；提交需等相关工作完成、用户明确同意收口后，先归档再提交。

## Agent 运行调试中心 Task 1 结果

- Task 1：后端 `WorkspaceResponse` 调试摘要字段已完成。
- 已实现：
  - `WorkspaceResponse.pending_review_summary`
  - `WorkspaceResponse.rag_status`
  - 待审核摘要固定字段集合，并避免返回正文、prompt、raw response、`story_plan`、`chapter_pair`、`verification_report`。
  - RAG 摘要支持 ready/not ready/missing，事件优先、明确 `rag-` 来源 snapshot 兜底，并避免普通素材、failed/skipped/status/rebuild 事件误判为已注入。
- 审阅：
  - 规格审阅：最终通过。
  - 代码质量审阅：最终无 Critical/Important，允许继续。
- 主控验证：
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_api_context.py -v`：41 passed。
  - `uv run --project apps/agent-runtime ruff check apps/agent-runtime/app/domain/models.py apps/agent-runtime/app/application/task_service/queries.py apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_api_context.py`：All checks passed。
- 当前状态：进入 Task 2，前端类型与诊断纯函数。

## Agent 运行调试中心 Task 2 结果

- Task 2：前端类型与诊断纯函数已完成。
- 已实现：
  - `PendingReviewSummary`、`RagStatus`、`LlmReport` 类型，并挂入 `WorkspaceResponse`。
  - `debug-diagnostics.mjs` 纯函数派生整体健康、实时连接、LLM、Agent Trace、上下文/RAG、状态对账与证据链接。
  - 状态优先级覆盖：状态不一致、可恢复异常、等待用户、已终止、运行正常、证据不足。
  - `created` 与 `sources_ingested` 归为等待用户；终态连接识别 completed/cancelled/failed/通用结束；`usage_total` 为空时从事件用量兜底。
  - 敏感内容保护测试覆盖 prompt、raw response、RAG 命中文本和事件正文不进入诊断 JSON。
- 审阅：
  - 规格审阅：最终通过。
  - 代码质量审阅：最终通过，无 Critical/Important，允许进入 Task 3。
- 主控验证：
  - `npm --prefix apps/web test -- src/features/task-run/debug-diagnostics.test.mjs`：21/21 passed。
  - `npm --prefix apps/web test`：60/60 passed。
  - `npm --prefix apps/web run lint`：退出码 0。
- 当前状态：进入 Task 3，前端调试面板 UI 与 `TaskRunClient` 接入。

## Agent 运行调试中心 Task 3 结果

- Task 3：前端调试面板 UI 与任务工作台接入已完成。
- 已实现：
  - 新增任务详情页第 5 个“调试”Tab。
  - 新增 `DebugPanel`，展示诊断结论、实时连接、LLM 摘要、Agent Trace、上下文/RAG、状态对账、最近事件与证据链接。
  - 调试面板只读展示诊断，不触发 LLM/RAG 重跑，不直接改变任务状态。
  - “查看恢复方案”只打开现有恢复对话框；仅当推荐恢复动作或可用恢复选项存在时才启用。
- 审阅：
  - 规格审阅：通过。
  - 代码质量审阅：修正恢复按钮启用条件后复审通过。

## 集成验证与本地挂载

- 本地服务已重新启动：
  - 后端：`http://127.0.0.1:8000`
  - 前端：`http://127.0.0.1:3000`
- 串行接口验证：
  - `GET /api/health`：200。
  - `GET /api/dashboard`：200。
  - `GET /api/tasks/task_d13142a712/workspace`：200，顶层包含 `pending_review_summary` 与 `rag_status`。
- 页面验收：
  - 任务页 `http://127.0.0.1:3000/tasks/?id=task_e8427fa731` 可打开。
  - “调试”Tab 可见可点击，模块文案覆盖诊断结论、实时连接、LLM 摘要、Agent Trace、上下文/RAG、状态对账、最近事件与证据链接。
  - 页面文本未发现 `prompt`、`raw_response`、`story_plan`、`chapter_pair`、`verification_report` 或 RAG 命中文本暴露。
- 冒烟验证：
  - `python3 .agents/skills/project-interface-smoke/scripts/run_smoke.py --frontend-url http://127.0.0.1:3000 --backend-url http://127.0.0.1:8000 --timeout 90`：全部通过，收口前复验创建测试任务 `task_c006a89632`。
  - 之前的 smoke timeout 根因收口：当前热启动后可通过；更可能是前端/后端服务当时未 ready、Next 首次编译或请求冷启动导致，不是本次 workspace 字段缺失。
- 最终验证：
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_api_context.py -v`：41 passed。
  - `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：All checks passed。
  - `npm --prefix apps/web test`：60 passed。
  - `npm --prefix apps/web run lint`：退出码 0。
  - `npm --prefix apps/web run build`：退出码 0。
  - `python3 .agents/skills/api-full-test/scripts/run_full_test.py --backend-url http://127.0.0.1:8000 --timeout 90`：19 通过、2 警告、2 失败；收口前复验创建测试任务 `task_7ff1bbca9d`，失败项均为远端域名 CORS（`https://agentproject.pages.dev`、`https://yuegui666.icu`），本地 `http://localhost:3000` 通过。
- CORS 残留项：
  - 后端默认允许源当前包含 runtime origin、本地 3000/3001。
  - 远端域名需要通过 `CORS_ALLOWED_ORIGINS` 或后续配置变更处理；本轮调试中心未改 CORS。
- 版本规则：
  - 复查 `find . -path '*/Cargo.toml' -print` 无输出，因此本轮无法执行 `<子目录>/src/Cargo.toml` patch +1。
- 当前状态：用户已要求完整落盘；准备执行 active -> archive 归档并提交。
