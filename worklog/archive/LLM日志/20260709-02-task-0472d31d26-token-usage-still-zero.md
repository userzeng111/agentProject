# LLM 摘要 token 仍为 0 与白鹿 usage 采集复核

## 问题标题

LLM 摘要 token 仍为 0 与白鹿 usage 采集复核

## 用户原始诉求

用户反馈任务 `task_0472d31d26` 的 LLM 摘要中输入 tokens、输出 tokens、总 tokens 等仍显示为 0，并追问 `https://bailucode.com/api_platform/` 是否收集不到、是否是接收到的 JSON 解析不全或方法不对。

## 当前状态

进行中。先按系统调试流程核对白鹿 OpenAI 兼容接口 usage 返回形态、后端协议解析、非流式 fallback、任务事件持久化、`llm_report` 聚合与前端展示链路。

## 初步判断

- 不能仅凭前端显示 0 判断白鹿接口不返回 usage。
- 需要区分三类问题：供应商实际不返回 usage、后端协议适配器没有解析到 usage、后端已解析但没有写入 `model.usage` 或 `llm_report` 聚合字段。
- 当前重点复核嵌套 usage、非流式 JSON 补全 usage、流式 fallback 后 usage 事件是否落盘。

## 复核结论

- 已检查 `tasklog/runs/task_0472d31d26/task.json`：该历史任务有 15 个 `context.history.updated` 事件和 17 条 timing 调用记录，但没有任何 `model.usage` 事件。
- 该任务前端 token 显示 0 的直接原因是历史运行时没有落盘 usage，后端只能给出 `usage_status=missing` 与全 0 的 `usage_total`。
- 不应伪造历史任务真实 token；本地消息历史无法可靠反推供应商接口统计。
- 对白鹿最小真实探针显示：`bailu-2.7-free` 的非流式与流式接口都返回 usage；项目网关 `complete_stream_sync()` 也能拿到末尾 usage chunk，字段包含 `prompt_tokens`、`completion_tokens`、`total_tokens`。

## 修复方案

- 扩展 OpenAI 兼容协议 usage 解析：支持顶层 `usage`、`response.usage`、`choices[0].usage`、`choices[0].delta.usage`、`choices[0].message.usage`。
- 非流式 JSON fallback 改为使用带 metadata 的补全结果；有 usage 时通过 progress callback 落 `model.usage`。
- `llm_report` 聚合补充读取 `payload.usage` 嵌套字段，避免已落盘但包了一层导致 token 聚合为 0。
- 网关在收到 usage 时输出受性能日志开关控制的诊断日志，记录 `usage_source_path` 与关键 token 字段，方便追查供应商返回路径。
- 审查后补强：usage 与 `finish_reason` 同在末尾 chunk 时也计入 `usage_chunk_count` 并输出 usage 诊断日志，避免性能日志误判没有收到 usage。

## 验证记录

- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_protocol_adapter.py apps/agent-runtime/tests/test_story_engine_context.py apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_performance_observability.py apps/agent-runtime/tests/test_gateway_empty_response_retry.py -q`：126 passed。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q`：420 passed, 1 skipped。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`：All checks passed。
- `npm --prefix apps/web test`：129 passed。
- `npm --prefix apps/web run lint`：通过。
- `python3 .agents/skills/project-interface-smoke/scripts/run_smoke.py --frontend-url http://localhost:3000 --backend-url http://localhost:8000`：全部冒烟检查通过。
- `python3 .agents/skills/api-full-test/scripts/run_full_test.py --backend-url http://localhost:8000 --frontend-url http://localhost:3000 --allow-gateway-unavailable --timeout 60`：19 通过，2 个预期警告，0 失败。
- 当前代码白鹿真实流式探针：`bailu-2.7-free` 返回 1 个 usage chunk，`usage_source_path=usage`，`prompt_tokens`、`completion_tokens`、`total_tokens` 均非零。

## 当前状态

代码修复、审查修复、自动化验证与运行态重启已完成，等待用户界面复测。历史任务 `task_0472d31d26` 没有真实 usage 事件，预期应显示“用量上报缺失/未上报”，不能补出真实 token；新任务应能在收到供应商 usage 后统计真实 token。

## 2026-07-10 真实接口复核

- 使用当前 `.env` 中的白鹿网关配置进行最小真实流式调用时，默认模型 `mimo-v2.5-pro` 返回 HTTP 400：`Model mimo-v2.5-pro does not exist`。白鹿 `/models` 实测返回 34 个模型，列表中不包含该默认模型；该问题发生在模型校验阶段，尚未进入 usage 解析。
- 改用白鹿模型列表中存在的 `bailu-2.7-free` 复测：流式接口返回 HTTP 200，并通过 `stream_options.include_usage=true` 收到顶层 `usage`。运行时已发出 1 条 `model.usage` 事件，值为 `prompt_tokens=41`、`completion_tokens=49`、`total_tokens=90`、`usage_source_path=usage`。
- 同一模型的非流式接口也返回 HTTP 200，解析到 `prompt_tokens=309`、`completion_tokens=16`、`total_tokens=325`、`usage_source_path=usage`。
- 将真实流式 event payload 输入 LLM 摘要聚合器后，结果为 `input_tokens=41`、`output_tokens=49`、`total_tokens=90`，说明供应商字段到 UI 摘要字段的映射已生效。
- 结论：usage JSON 解析、事件生成和摘要 token 映射已验证成功；当前默认模型配置与白鹿实际模型列表不一致，会在解析前阻断新任务。未经用户确认，不修改默认模型配置。
