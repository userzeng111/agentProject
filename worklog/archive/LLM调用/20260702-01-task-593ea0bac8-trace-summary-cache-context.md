# task_593ea0bac8 Agent Trace、LLM摘要缓存与上下文窗口观测问题

## 问题标题

task_593ea0bac8 Agent Trace、LLM摘要缓存与上下文窗口观测问题

## 用户原始诉求

多agent并行推进，头脑风暴思考下列问题：

- 任务 ID：task_593ea0bac8 在调试界面看到 Agent Trace 存在问题。
- LLM摘要也存在问题，需要记载对应日志，方便查找修复问题。
- LLM摘要现在缓存命中为 0，需要思考如何修复。
- 模型上下文窗口现在写死，需要确认能否从模型请求接口直接拿到模型上下文窗口相关信息；能拿到则使用接口值，不能拿到则使用默认值。

## 当前状态

已完成 B 方案观测与当前失败链路修复，并按用户要求归档。模型上下文窗口接口优先留作后续 C 方案。

## 初始拆分

- Agent Trace 观测链路：确认调试界面展示字段、后端记录字段、任务运行日志之间的缺口。
- LLM摘要与缓存命中：确认摘要生成、缓存 key、命中统计、日志记录的实际链路。
- 模型上下文窗口：确认模型目录、模型请求接口、默认上下文窗口配置的来源与可替换点。

## 只读调查进展

- 任务 `task_593ea0bac8` 当前停在 `waiting_manual_action`。`trace/current.json` 只保留当前状态、阶段、最近消息，不包含可回放的详细 Agent Trace。
- `events.md` 显示失败链路为：
  - `chapter-window-gate` 首次验证 `finish_reason=length` 且空正文，随后 repair 成功。
  - `chapter-pair-revision` 与 `chapter-pair-revision-repair` 均 `finish_reason=length`，原始响应为空，最终进入可恢复异常。
- `model.usage` 事件显示 `chapter-pair-revision` 输出 token 达到 `10000`，但 `content_chars=0`，推断大量预算消耗在 reasoning/thinking，正式 JSON content 没输出。
- LLM 摘要面板不是单独的 LLM 摘要调用，而是基于任务事件动态汇总的 `llm_report`。当前 `cache_hit_count` 统计运行时响应缓存 `cache.hit`，不统计 Provider Prompt Cache 的 `cached_tokens`。
- `task_593ea0bac8` 的 usage 中 repair 请求已有 `prompt_tokens_details.cached_tokens=4096/5376`，说明供应商 prompt cache 实际有命中；界面显示“缓存命中 0”主要是统计口径问题。
- 响应缓存 key 包含完整 `request_messages`、`max_tokens`、`request_options`。章节 prompt 使用随机 boundary，天然会扰动 key，不宜期望章节最终响应缓存高命中。
- 当前公开模型目录能力来自本地注册表与 `apps/agent-runtime/data/model_capabilities.json`。低层 `GET /models` 原始响应理论上能拿到上游私有字段，但 `ModelCatalogService._build_model_item()` 目前只保留 `id/object/owned_by`，未映射 `context_length/max_context/context_window/max_tokens` 等字段。
- 标准 OpenAI `GET /models` 文档只保证模型 id、object、created、owned_by，不保证上下文窗口字段；因此只能优先使用网关私有字段，缺失时回退本地配置和保守默认值。

## 初步根因假设

1. Agent Trace 问题：调试面板的 Agent Trace 更偏向自动审核 `auto_review_trace` 汇总，而任务运行链路的 `trace.summary`、`model.response.parse_failed`、`model.usage` 没有统一成可检索的诊断 trace；`trace/current.json` 粒度过粗。
2. LLM 摘要问题：前端标题“LLM 摘要”容易让人理解成“模型生成摘要”，实际是事件汇总；`cache_hit_count` 命名也掩盖了响应缓存、上下文缓存、供应商 prompt cache 三种口径差异。
3. 缓存命中为 0：最可能是统计口径导致。Provider Prompt Cache 已通过 usage 命中 token 表现出来，但未被计入命中次数；响应缓存因随机 boundary、动态上下文和首轮任务特性不易命中。
4. 上下文窗口写死：本地画像和 JSON 配置是主来源；接口值即使返回也未进入模型目录标准化能力，导致“能拿到但没用上”。

## 待讨论方案方向

- 观测优先：补齐日志与诊断字段，拆分缓存口径，保证下次类似失败能直接定位到 finish_reason、reasoning/content 字符数、raw response hash、cache 类型和能力来源。
- 行为修复：对结构化 JSON 步骤增加空正文且 `length/max_tokens` 的专用重试策略，降低或限制推理消耗，并为 `chapter-pair-revision` 增加类似 verification 的极短 JSON 重试提示。
- 能力来源修复：在模型目录合并阶段标准化上游 raw context 字段，优先接口值，其次本地模型配置/画像，最后保守默认值，并在前端展示能力来源。

## 已选方案

用户选择 B：观测 + 当前失败链路修复。

执行计划文档已创建：

- `docs/superpowers/plans/2026-07-02-task-593ea0bac8-llm-observability-retry.md`

本计划纳入：

- `chapter-pair-revision` 空正文且 `length/max_tokens` 的专用重试。
- LLM 调试面板缓存口径拆分。
- 结构化日志与事件诊断增强。

本计划不纳入：

- 模型上下文窗口“接口能力字段优先”的完整实现；该部分属于更大范围 C 方案，保留为后续可选批次。

## 计划审查记录

- 已启动只读计划审查子代理。
- 审查结论为“需修改”，指出：
  - 提交前 Git 核对应放在归档之后。
  - 诊断日志任务需要失败测试。
  - 响应缓存日志范围应明确只覆盖流式路径或同步覆盖非流式路径。
  - 手工核对应给出可执行方式。
- 已修订执行计划：
  - Task 5 补充日志失败测试。
  - 明确本批只覆盖当前失败链路使用的流式响应缓存。
  - Task 6 的 task_593ea0bac8 核对改为可执行测试命令。
  - Task 7 调整为先归档，再提交前 Git 核对。

## 执行记录

- 已回收两个只读子代理：
  - 后端审查确认既有 diff 未覆盖 `chapter-pair-revision` 空正文 `length/max_tokens` 专用 retry，本批已补齐。
  - 前端审查给出 `llm_report` 新字段到诊断面板的映射，本批已采用。
- 未发现 `<子目录（项目目录）>/src/Cargo.toml` 或根级 Cargo workspace，本次无 Cargo patch 版本号可更新。
- 后端已实现：
  - `chapter-pair-revision` 遇到空正文且 `finish_reason=length/max_tokens` 时，先用章节修订专用 JSON-only retry；允许同预算重试一次，避免直接进入通用 repair。
  - 空正文截断 retry warning 日志补充 `content_chars`、`reasoning_chars`、`stage`、`exchange_label`、`finish_reason`、预算信息，不记录正文。
  - `llm_report` 新增 `runtime_response_cache_hit_count` 与 `provider_prompt_cache_hit_count`，旧 `cache_hit_count` 保持兼容语义。
  - 流式结构化 JSON 路径增加响应缓存查询/写入 debug 日志。
  - `ContextManager.build_snapshot()` 增加上下文缓存查询 debug 日志，记录 hit/miss、stage、model、cache key 和引用/记忆计数，不记录正文。
- 前端已实现：
  - `LlmReport` 类型增加响应缓存命中与供应商 prompt cache 命中字段。
  - 调试诊断可从后端 report 或事件兜底派生两类缓存命中。
  - 调试面板把“缓存命中”改为“响应缓存命中”，新增“供应商缓存命中”，保留“缓存 tokens”。
- 同时保留工作区中此前已有的 `content_filter` 空响应 repair 与中文引号约束改动；本批未回退该既有改动。

## 验证记录

- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py::StoryEngineContextTests::test_revise_chapter_pair_retries_reasoning_only_length_before_generic_repair apps/agent-runtime/tests/test_story_engine_context.py::StoryEngineContextTests::test_verify_full_story_retries_reasoning_only_length_without_generic_repair apps/agent-runtime/tests/test_story_engine_context.py::StoryEngineContextTests::test_verify_full_story_retries_non_empty_length_before_repair -q`：通过，3 passed。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_task_service_workspace.py -q`：通过，46 passed。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_context_manager.py apps/agent-runtime/tests/test_story_engine_context.py -q`：通过，57 passed。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_context_manager.py -q`：通过，103 passed。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：通过，All checks passed。
- `cd apps/web && npm test -- src/features/task-run/debug-diagnostics.test.mjs`：通过，21 passed。
- `cd apps/web && npm run lint`：通过。

## 未处理项

- 模型上下文窗口“接口能力字段优先”属于 C 方案，涉及模型目录字段标准化和能力来源展示。本批按用户已选 B 方案只处理观测与当前失败链路修复，未修改模型目录合并逻辑。
- 当前问题已按用户要求从 `worklog/active/` 移动到 `worklog/archive/`，并同步更新索引。
