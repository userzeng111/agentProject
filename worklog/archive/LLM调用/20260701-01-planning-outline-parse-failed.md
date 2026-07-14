---
name: planning-outline-parse-failed-20260701
description: 任务 task_d3032f3349 在 planning 阶段 outline 调用时因模型返回 content_filter 空响应导致 JSON 解析失败，记录根因与可选修复方案。
metadata:
  type: project
---

# 问题标题

planning 阶段模型响应 JSON 解析失败：outline

# 用户原始诉求

任务 `task_d3032f3349` 在 planning 阶段出现 `model.response.parse_failed` 事件，提示 outline 模型返回 JSON 无法解析。用户要求检查项目出了什么问题。

# 当前状态

- 已定位到直接原因与根因。
- 已实现两项修复并通过测试：
  1. `content_filter` 空响应优先走专用 repair，避免先产生 `model.response.parse_failed` 事件；repair 失败时错误信息明确提示 `content_filter`。
  2. 所有小说生成 prompt 在最后一条 user 消息中注入中文双引号约束，防止未转义的半角双引号破坏 JSON。
- 测试覆盖：`apps/agent-runtime/tests/test_story_engine_context.py` 44 项全部通过；联合 `test_outline_progress_events.py`、`test_graph_chapter_pair_loop.py` 共 51 项全部通过。
- 待用户确认是否收口（归档 + 提交）。

# 证据链

1. 失败快照：`tasklog/runs/task_d3032f3349/context/planning/outline-raw-response.json`
   - `model`: `K2.7`
   - `finish_reason`: `content_filter`
   - `raw_response_chars`: `0`
   - `raw_response_sha256`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`（空字符串）
   - 解析错误信息：`模型返回的 JSON 无法解析：`

2. 运行日志：`apps/agent-runtime/app/logs/app-2026-07-01.log:126603`
   - 同一次调用 `model=K2.7`, `stage=planning`, `exchange_label=outline`
   - `content_chars=0`, `reasoning_chars=11468`, `finish_reason=content_filter`
   - 说明模型生成了 reasoning，但内容被上游内容安全策略过滤为空。

3. 提示词内容：
   - 使用了 `style_profile_id=wozhenmeixiangchongshengya`（柳岸花又明风格实例）。
   - 风格规则中明确要求大量使用粗口/俚语（如“妈的”“操”“狗日的”）作为“痞气层”。
   - 参考摘要中也包含玄幻打斗、宿舍夜袭等场景描写。

4. 代码路径：
   - 解析逻辑：`app/llm/story_engine.py` `_complete_stream_json_with_cache` 默认调用 `StoryEngine._strip_and_parse_json`（继承自 `BaseAgent._strip_and_parse_json`）。
   - 截断重试仅识别 `{"length", "max_tokens"}`，不包含 `content_filter`。
   - 因此在 `content_filter` 空响应时，系统会先 `parse_failed`，再走 `_emit_parse_failed_exchange` → repair 路径。
   - 本任务中 repair 成功（`outline-repair` 调用 `finish_reason=stop`），所以任务未中断。

5. 影响范围：
   - 同日志中 `K2.7` 在 `logic`、`structure`、`worldbuilding`、`character_arc`、`creativity`、`coherence` 等多个阶段均出现 `finish_reason=content_filter`。
   - 这不是单个任务或单个阶段的偶发问题，而是模型/网关在内容安全策略上的系统性表现。

# 根因判断

**直接原因**：模型返回了空响应且 `finish_reason=content_filter`，JSON 解析器无法解析空字符串。  
**根因**：上游模型/网关（K2.7 所映射的提供商）对输出内容施加了内容安全过滤，触发了过滤的场景包括风格规则中的粗口、俚语、打斗/校园冲突等敏感元素。  
**为什么最终恢复**：当前代码在解析失败后会触发 repair 对话，追加 repair 提示词，再次请求模型，第二次成功生成了可用 JSON。

# 可选修复方向

1. **提升内容过滤的可见性（推荐）**
   - 在 `GatewayClientError`/`model.response.parse_failed` 事件中，当 `finish_reason == "content_filter"` 时给出明确错误信息，而不是笼统的“JSON 无法解析”。
   - 可在 UI/日志中提示用户“模型输出被内容安全策略过滤”，便于排查。

2. **将 content_filter 纳入可重试/可修复策略**
   - 把 `content_filter` 加入 `_TRUNCATED_FINISH_REASONS` 或单独处理，触发与 repair 类似的二次请求，减少显式的 `parse_failed` 事件残留。
   - 也可以在首次检测到 `content_filter` 空响应时直接重试，避免写 `parse_failed` 快照。

3. **调整风格提示词或模型选择**
   - 对 `wozhenmeixiangchongshengya` 这类风格，评估是否将过于直白的粗口示例做“软化”或替换为占位符，降低触发过滤的概率。
   - 或者在创建 `style_remix` 任务时，自动选择对成人/粗口内容更宽容的模型/网关。

4. **保持现状**
   - 当前 repair 机制已能恢复，任务最终可继续。但事件日志里会有噪音，且用户可能误以为任务失败。

# 讨论补充：双引号问题

用户提出疑问：是否可能因模型返回正文使用半角双引号导致 JSON 解析失败？

- 直接原因仍是 `finish_reason=content_filter` 且返回为空，不存在任何字符（包括引号）。
- 我提取了最终成功返回的 outline JSON 并逐字段检查：所有字符串值中均未出现未转义的 ASCII 双引号。
- 当前 prompt 里并未明确要求“正文/摘要必须使用中文引号”。JSON 语法本身要求键和字符串用半角双引号包裹；若正文里出现半角双引号且未转义，确实会破坏 JSON，但这是潜在风险，不是本次根因。
- 若用户希望消除该风险，可在 prompt 或风格规则中增加“正文引号使用中文双引号（“”）”的约束。



待用户确认方向后，再进入代码修改阶段。当前不改动任何代码。
