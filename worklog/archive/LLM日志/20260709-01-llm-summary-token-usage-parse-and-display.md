# LLM 摘要 token 用量解析与展示缺失

## 问题标题

LLM 摘要 token 用量解析与展示缺失

## 用户原始诉求

用户反馈：每个任务调试界面的 LLM 摘要中，输入 token、输出 token、缓存、总 token 等内容很多没有正常显示，字段明显偏少。需要按照真实模型接口回传解析并统计，因为这是任务级调试信息，需要针对这些 token 做统计。

## 当前状态

已完成代码修复与相关验证，等待用户在界面测试确认。当前不归档。

## 初始分析方向

- 确认模型网关返回的 usage 原始结构是否被完整保存，包括 OpenAI 兼容字段、Responses/Anthropic 风格字段、缓存命中字段与推理 token 字段。
- 确认后端 LLM 摘要聚合是否只统计了少数字段，导致 input/output/cache/total 缺失或为 0。
- 确认前端调试界面是否字段命名不一致，导致后端已有数据但未展示。
- 设计任务级 token 统计口径：单次请求明细、任务总计、缓存命中与缓存 token 计数需要可追溯到真实接口回传。

## 只读排查结论

- 后端 `llm_report` 当前只聚合 `input_tokens`、`output_tokens`、`total_tokens`、`cached_tokens`、`cache_read_input_tokens` 五个扁平字段，无法覆盖真实接口常见的嵌套 usage 字段。
- 真实日志样本中已出现 `prompt_tokens_details.cached_tokens`、`completion_tokens_details.reasoning_tokens`、`usage_source`、`usage_semantic`、`claude_cache_creation_5_m_tokens`、`claude_cache_creation_1_h_tokens` 等字段，但当前摘要不会完整统计。
- OpenAI 兼容流式解析只在没有 `choices` 的 chunk 中读取顶层 `usage`；如果网关把 `usage` 放在带 `choices` 的 chunk 上，会出现 usage 丢失风险。
- OpenAI 兼容流式请求当前未看到显式默认注入 `stream_options.include_usage=true`，可能导致部分模型网关不返回 usage。
- 前端 `normalizeTokens()` 与类型定义同样只覆盖少量字段；调试面板把 `cachedTokens || cacheReadInputTokens` 合并显示，会隐藏缓存命中与缓存读取的区别。
- `task_68472f411a` 当前日志未检索到 `model.usage` 事件，说明部分任务的问题不只是展示层，还包括调用链路是否稳定落 usage。
- 当前仓库未发现 `Cargo.toml`，版本号 patch 递增规则在本仓库当前状态下没有可执行目标文件。

## 建议修复方案

1. 后端采集层：OpenAI 兼容流式请求默认补充 `stream_options.include_usage=true`，并在解析流式 chunk 时保留带 `choices` chunk 上的顶层 `usage`。
2. 后端标准化层：把真实接口 usage 统一解析为任务统计字段，包括输入、输出、总量、缓存命中、缓存读取、缓存创建、推理 token，并保留必要的来源字段用于追溯。
3. 后端聚合层：扩展 `usage_total`、`by_model`、`by_stage`、`latest_usage` 的 token 字段；供应商缓存命中判断同时覆盖缓存命中、缓存读取和缓存创建。
4. 前端展示层：扩展 `LlmUsageSummary`、`normalizeTokens()`、事件兜底统计和调试面板，把缓存命中、缓存读取、缓存创建、推理 token 分开展示，避免合并吞字段。
5. 测试验证：先补失败测试，再实现修复；覆盖后端 workspace 聚合、协议流式 usage 解析、前端诊断归一化与展示数据。

## 风险与边界

- 不改变模型调用业务语义，只增强 usage 采集、标准化、聚合与展示。
- 历史任务如果完全没有 `model.usage` 事件，无法凭空还原真实 token，只能通过已有事件兜底显示；新任务应通过采集层修复稳定落 usage。
- 已有未提交改动较多，执行时需只修改本问题相关文件，避免覆盖其他任务变更。

## 执行结果

- 后端 OpenAI 兼容流式请求默认带上 `stream_options.include_usage=true`，并保留带 `choices` chunk 上的 `usage`。
- 后端 LLM 摘要聚合扩展为输入、输出、总量、缓存命中、缓存读取、缓存创建、推理 token 七类统计，并兼容真实接口中的嵌套 usage 字段。
- 前端调试诊断扩展 token 归一化，支持事件兜底解析真实接口 usage；LLM 摘要面板分开展示缓存命中、缓存读取、缓存创建与推理 token。
- 已补后端与前端回归测试，覆盖真实 provider usage 字段、非零字段优先、缓存创建拆分字段和 UI 展示不再合并缓存字段。

## 追加反馈

- 用户要求 usage 显示需要和真实接口回传一模一样。
- 当前理解：任务级汇总仍保留标准化统计字段，便于跨模型累计；同时在单次/最新 usage 明细中保留接口原始 usage，不改名、不丢字段。除核心统计外的 `usage_source`、`usage_semantic`、`prompt_tokens_details`、`completion_tokens_details`、`input_token_details`、Claude 缓存创建拆分字段等放入 `details` 明细对象中，供调试追溯。
- 需确认用户提到的 `devices` 是否实际指 `details`；当前代码中未发现与 LLM 摘要相关的 `devices` 字段。

## 验证记录

- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_protocol_adapter.py apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_story_engine_context.py -q`：100 passed。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/app/application/task_service/queries.py apps/agent-runtime/app/llm/protocols.py apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_protocol_adapter.py`：All checks passed。
- `npm test -- src/features/task-run/debug-diagnostics.test.mjs`：27 passed。
- `npx eslint src/features/task-run/debug-diagnostics.mjs src/features/task-run/debug-diagnostics.test.mjs src/features/task-run/debug-panel.tsx src/lib/types.ts`：通过。
- `git diff --check`：通过。

## 全量验证记录

- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q`：413 passed，1 skipped，4 subtests passed；保留 FastAPI `on_event` 既有弃用警告。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：All checks passed。
- `npm --prefix apps/web test`：128 passed。
- `npm --prefix apps/web run lint`：通过。
- `npm --prefix apps/web run build`：通过；保留 Next.js `metadataBase` 既有警告。
- `python3 .agents/skills/project-interface-smoke/scripts/run_smoke.py --frontend-url http://localhost:3000 --backend-url http://localhost:8000`：全部冒烟检查通过。
- `python3 .agents/skills/api-full-test/scripts/run_full_test.py --backend-url http://localhost:8000 --frontend-url http://localhost:3000 --allow-gateway-unavailable --timeout 60`：19 通过，2 个任务阶段预期警告，0 失败。
- 服务确认：`http://localhost:8000/api/health` 返回 `{"status":"ok"}`，`http://localhost:3000/` 返回 200。

## 2026-07-09 追加反馈：task_0472d31d26 token 仍显示 0

- 用户反馈 `task_0472d31d26` 的 LLM 摘要仍显示输入、输出、总 token 为 0。
- 复查后端 `/api/tasks/task_0472d31d26/workspace`：`request_count=17`、`usage_count=0`、`usage_missing_count=17`、`usage_status=missing`，`usage_total` 为 0。
- 复查落盘事件：`tasklog/runs/task_0472d31d26/events.md` 只有 `context.history.updated=15` 与 `trace.summary=18`，没有 `model.usage` 事件；历史任务没有真实供应商 usage，本地无法反推真实接口 token。
- 前端源码在 `usage_status=missing` 且 `usage_missing_count>0` 时会把 token 显示为“未上报”，并展示“历史任务无法从本地消息记录反推真实接口 token”的警告。
- 已重启前端 dev server，排除旧 bundle。浏览器实测 `http://localhost:3000/p/task_0472d31d26/`：显示“用量上报缺失：17”“用量状态：missing”，输入/输出/总 token 均显示“未上报”。
- 新后端验证任务 `task_93db8308f7` 已落真实 usage：`usage_count=16`、`usage_missing_count=0`、`usage_status=complete`、`input_tokens=211837`、`output_tokens=108521`、`total_tokens=320358`。浏览器实测同样显示非零 token。
- 结论：旧任务 token 不是仍未修复，而是旧运行日志没有真实 usage；当前修复已避免把缺失误读为真实 0，新任务可正常统计真实 token。

## 2026-07-09 追加验证记录

- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：All checks passed。
- `npm --prefix apps/web test`：129 passed。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q`：413 passed，1 skipped，4 subtests passed；保留 FastAPI `on_event` 既有弃用警告。
- `npm --prefix apps/web run lint`：通过。
- `npm --prefix apps/web run build`：通过；保留 Next.js `metadataBase` 既有警告。
- `python3 .agents/skills/project-interface-smoke/scripts/run_smoke.py --frontend-url http://localhost:3000 --backend-url http://localhost:8000`：全部冒烟检查通过，创建测试任务 `task_f53766488a`。
- `python3 .agents/skills/api-full-test/scripts/run_full_test.py --backend-url http://localhost:8000 --frontend-url http://localhost:3000 --allow-gateway-unavailable --timeout 60`：19 通过，2 个任务阶段预期警告，0 失败，创建测试任务 `task_4d5ac677f8`。

## 2026-07-09 白鹿 API usage 采集方式再分析

- 用户指出白鹿 API 平台 `https://bailucode.com/api_platform/`，质疑是否是接收 JSON 解析不全或方法不对。
- 当前环境实际调用基础地址为 `https://bailucode.com/openapi/v1`，控制台页面不是模型调用接口；调用链路走 OpenAI 兼容 `/chat/completions`。
- 白鹿控制台页面当前未能直接获取到内部 API 文档内容；后续判断以本地实际调用代码和已落盘响应事件为准。
- 当前 OpenAI 流式请求构造已默认注入 `stream_options.include_usage=true`，支持标准的“最后一个空 choices usage chunk”，也支持带 choices 的 chunk 顶层 `usage`。
- 新任务 `task_93db8308f7` 已证明白鹿当前流式链路会返回并落盘 OpenAI 兼容 usage：示例 payload 包含 `prompt_tokens`、`completion_tokens`、`total_tokens`、`model`、`finish_reason`。
- 仍存在方法层风险：非流式 `complete()` / `complete_json()` 目前只返回文本或解析后的 JSON，未携带响应体里的 `usage`；如果流式失败 fallback 到非流式，即使白鹿非流式响应含 usage，也会被丢弃。
- 仍存在诊断层不足：正常成功响应不会保存原始 SSE chunk 或原始响应 JSON；只有解析失败时保存 raw response 诊断。缺 usage 时无法事后区分“白鹿没回 usage”和“我们解析/落事件丢了”。
- 建议下一步设计：增加一次可控的白鹿最小探针，分别请求 `stream=true + include_usage` 与 `stream=false`，只记录 usage 结构、chunk 类型和字段路径，不保存正文；同时扩展非流式 usage 采集与受开关控制的 usage 原始诊断。
