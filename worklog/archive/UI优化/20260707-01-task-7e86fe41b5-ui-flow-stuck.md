# task_7e86fe41b5 UI 流转停留原页面问题

## 问题标题

task_7e86fe41b5 UI 流转停留原页面问题

## 用户原始诉求

任务 ID：`task_7e86fe41b5` 遇到问题。需要查看这个任务对应日志，分析为什么整体 UI 流转时出现问题：点击后没有成功跳转而停留在原页面，再次点击提示任务执行。需要从 UI/UX 设计和调用合理性角度进行头脑风暴和全量分析。

## 当前状态

UI 流转修复已完成；LLM 摘要 JSON 解析失败问题已完成复现定位，并按用户最终选择实现修复项 3、4。用户已确认收口，本文档已归档并准备随修复提交。

## 初始排查拆分

- 任务日志与状态机：确认 `task_7e86fe41b5` 当前状态、事件流、是否已触发运行、后端是否拒绝重复执行。
- 前端 UI 流转：确认点击按钮后调用的 API、成功/失败分支、跳转条件、是否吞掉响应或未处理可恢复状态。
- UX 合理性：评估用户点击后的反馈、禁用状态、乐观跳转、重复点击防护和错误提示是否匹配后端真实状态。

## 只读排查结论

### 任务日志事实

- `tasklog/runs/task_7e86fe41b5/events.md` 显示第一次点击已经成功触发后台运行：任务从 `created` 进入 `planning`，随后完成大纲、章节计划审核，并生成第 1-5 章。
- 任务最终在 `2026-07-07T02:06:04Z` 转入 `waiting_manual_action`，原因是模型供应商返回错误：`白鹿的回答出现问题`。
- `events.tail.json` 和当前本地接口响应包含最后的 `task.error_recorded`，可用于定位后台异常细节。
- 当前 `/api/tasks/task_7e86fe41b5/workspace` 响应里 `allowed_actions=["restart_from_input"]`，`recommended_action="restart_from_input"`，说明后端认为该任务应进入恢复/重试流，而不是继续重复运行。
- 当前 `/api/dashboard` 中该任务位于 `failed_tasks`，`running_tasks` 为空。

### 后端调用语义

- `/api/tasks/{task_id}/run` 调用 `TaskService.run_task()`，成功后仅把任务标记为 `planning` 并启动后台线程，然后立即返回任务快照。
- `run_task()` 使用 `_active_runs` 做重复提交防护；后台执行窗口内再次调用会抛出 `任务正在运行中，请勿重复提交。`
- `waiting_manual_action` 被后端视为稳定可恢复状态，但 SSE 终止判定只覆盖 `completed/cancelled/failed`，没有把 `waiting_manual_action` 当作需要收束前端流转的状态。

### 前端流转事实

- 创建任务成功后，`create-task-client.tsx` 会 `router.push(workspaceHref(task.id))`。
- 工作台 `task-run-client.tsx` 的 `handleRun()` 调用 `runTask()` 后只执行 `refreshWorkspace()`，没有任何 `router.push()` 或明确的“已进入后台运行”反馈。
- 因此当用户在原工作台点击“开始执行”时，第一次点击实际已成功排队，但页面仍停留在原视图；如果刷新或 SSE 状态更新不及时，用户会误以为没有生效，再次点击就命中后端防重复提示。
- `handleContinueDraft()` 和 `handleRecover()` 也属于异步后台动作，当前也主要依赖 `refreshWorkspace()`，存在同类 UX 风险。

## 根因判断

当前问题不是“后端没有启动任务”，而是前端动作语义与后端异步语义不匹配：

1. 后端 `run` 是“排队/启动后台任务”语义，不是“同步执行完成”语义。
2. 前端按钮点击后没有稳定的启动反馈、乐观状态切换、重复点击冷却或路由收束。
3. SSE 对 `waiting_manual_action` 缺少终止/收束语义，任务进入人工处理后前端不会获得明确的结束信号。
4. 当前恢复入口存在，但用户必须等工作台刷新到 `waiting_manual_action` 后才能看到；在运行窗口内，重复点击体验仍然会暴露底层防重复错误。

## 候选修复方案

### 方案 A：最小修复

- `handleRun()` 成功后立即 `setWorkspace(nextTask)` 或刷新后展示“任务已进入后台执行”提示。
- 在 `running` 外增加短期 `actionSubmitted` 状态，直到工作台状态变成 `planning/drafting/...` 后再释放，避免重复点击。
- 将后端重复提交错误在前端转译成“任务已在后台执行，请查看实时日志”，不要作为失败感知。

优点：改动小，风险低。缺点：只缓解首屏体验，不能彻底解决所有异步动作流转。

### 方案 B：推荐修复

- 抽象统一的异步任务动作处理：`run/continue/recover/resume` 成功后统一进入“后台已接收”状态。
- 成功响应后立即使用返回的任务快照更新本地工作台状态，并显示不可重复提交的进行中状态。
- 对 `planning/drafting/assembling` 显示运行中面板与实时日志，隐藏原始启动按钮。
- 对 `waiting_manual_action` 显示恢复主 CTA，并解释推荐动作，如“按原始输入重新开始”。
- 前端 SSE 将 `task.recovery.blocked` 或 `waiting_manual_action` 识别为需要刷新并收束的状态。

优点：符合后端异步模型，能覆盖本问题和继续创作/恢复类动作。缺点：需要新增少量状态处理与测试。

### 方案 C：后端契约增强

- 后端动作接口返回更明确的 envelope，例如 `{accepted: true, task, next_route, ui_action}`。
- SSE 增加 `task.blocked` 或 `task.manual_action_required` 终止事件。
- 前端只消费后端给定的下一步路由与 CTA。

优点：契约最清晰。缺点：改动面较大，需要同步调整 API 类型和测试。

## 推荐执行计划

推荐先执行方案 B，并补一个很小的后端 SSE 兼容修复：

1. 前端：让 `runTask()` 成功后用返回的 `TaskRecord` 立即驱动本地状态，显示后台运行反馈，避免停留在“待启动”的视觉状态。
2. 前端：统一处理重复提交错误，将“任务正在运行中”解释为已启动状态，并自动刷新工作台。
3. 前端：在 `waiting_manual_action` 中突出恢复 CTA，避免用户继续寻找“开始执行/继续执行”入口。
4. 后端：SSE 对 `waiting_manual_action` 或 `task.recovery.blocked` 发出收束信号，前端收到后刷新工作台。
5. 测试：补充 `task-run` 状态工具测试和必要的 API/SSE 单元测试，验证运行中、人工处理、重复点击三个路径。

## 当前状态更新

用户选择推荐方案 B 后已进入执行并完成首轮修复。当前未归档，等待用户测试和确认收口。

## 执行记录

### 版本号前置检查

- 按项目规则检查 `<子目录（项目目录）>/src/Cargo.toml`，当前仓库中 `apps/agent-runtime/src/Cargo.toml` 不存在。
- 仓库内仅发现 `apps/agent-runtime/pyproject.toml`，因此本次未执行 Cargo workspace patch 版本递增。

### 已修改范围

- 后端 SSE：
  - `apps/agent-runtime/app/api/routes.py`
  - `apps/agent-runtime/tests/test_task_event_stream.py`
  - `apps/agent-runtime/tests/test_api_context.py`
- 前端任务工作台：
  - `apps/web/src/features/task-run/task-run-client.tsx`
  - `apps/web/src/features/task-run/task-run-state.mjs`
  - `apps/web/src/features/task-run/task-run-state.test.mjs`
  - `apps/web/src/features/task-run/task-action-state.mjs`
  - `apps/web/src/features/task-run/task-action-state.test.mjs`
  - `apps/web/src/lib/types.ts`
- 前端审核页：
  - `apps/web/src/features/task-review/task-review-client.tsx`

### 行为变化

- `run/continue/recover` 成功后，工作台会先用接口返回的 `TaskRecord` 乐观更新本地任务状态，避免按钮仍显示为可再次启动。
- 重复提交类错误会被转译为“任务已在后台执行，请查看实时日志或稍后刷新状态。”，避免用户误认为操作失败。
- `task.recovery.blocked` 与 `waiting_manual_action` 被视为事件流收束状态，前端收到后刷新工作台并关闭事件流。
- 后端 SSE 在任务已经是 `waiting_manual_action` 时会直接发送 `task.done`，`event_type=task.recovery.blocked`，避免长连接继续 keep-alive。
- 审核页的恢复/审核继续重复提交错误也统一转译，并跳转工作台查看运行态。

### 验证记录

- `npm test -- src/features/task-run/task-run-state.test.mjs src/features/task-run/task-action-state.test.mjs`：通过，18/18。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_event_stream.py apps/agent-runtime/tests/test_api_context.py -q`：通过，26/26。
- `npm run lint`：通过。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/app/api/routes.py apps/agent-runtime/tests/test_task_event_stream.py apps/agent-runtime/tests/test_api_context.py`：通过。
- `npm run build`：通过；仅出现既有 `metadataBase` 警告。
- `npm test`：通过，118/118。

### 待用户测试点

- 在新建或待启动任务上点击“开始执行”，确认按钮立即消失或切换为运行态，并出现后台执行提示。
- 在任务执行窗口内重复点击入口，确认不再呈现为失败，而是提示后台已执行并刷新状态。
- 任务进入 `waiting_manual_action` 后，确认页面停止事件流重连并显示恢复方案入口。

## LLM 摘要 JSON 解析失败补充定位

用户测试时发现 LLM 摘要中存在大量 JSON 解析失败。已查看 `task_7e86fe41b5` 的 `model.response.parse_failed` 事件、原始响应诊断文件和 `StoryEngine` 解析路径。

### 事实

- planning 阶段 `outline/outline-repair/outline-retry` 的原始响应多次为 `很抱歉，白鹿无法回答此问题。`，原始响应长度 15，不是 JSON。
- verification 阶段 `chapter-window-gate/chapter-window-gate-repair` 主要有两类失败：
  - `finish_reason=length` 且 `raw_response_chars=0`，即上游结束原因是长度截断但正文为空。
  - 原始响应为 `很抱歉，白鹿无法回答此问题。` 或类似拒答文本。
- 当前 `StoryEngine._complete_stream_json_with_cache()` 会先按 JSON 契约解析，失败后记录 `model.response.parse_failed` 并尝试 repair；repair 仍返回拒答/空响应时继续记录失败。
- `BaseAgent._PROVIDER_ERROR_PATTERNS` 包含 `白鹿的回答出现问题`、`请重试` 等，但未覆盖 `白鹿无法回答此问题`，因此这类拒答会被归类为 JSON 解析失败，而不是更明确的供应商拒答/安全拒答。
- `verify_full_story()` 传入了空截断专用重试参数，但 `verify_chapter_window()` 当前没有传 `empty_truncated_retry_prompt/empty_truncated_retry_max_tokens`，所以章节窗口验证遇到 `finish_reason=length + 空正文` 时不会走更高预算专用重试，只会进入普通 parse failed + repair。

### 结论

这些 JSON 解析失败的根因不是前端 LLM 摘要组件，也不是 JSON parser 自身损坏；主要是模型/供应商在强 JSON 场景下返回了非 JSON 内容或空截断内容。当前系统日志把它们统一记录为 `model.response.parse_failed`，所以 LLM 摘要中失败数量显得很多。

### 后续修复方向

- 扩展供应商错误/拒答关键词，把 `白鹿无法回答此问题` 等纳入供应商错误分类，避免误记为普通 JSON parse failed。
- 给 `verify_chapter_window()` 增加与 `verify_full_story()` 一致的空截断重试参数。
- LLM 摘要 UI 区分“JSON 格式错误”“供应商拒答”“空截断”“repair 失败”，避免把不同根因合并成一个解析失败数字。
- 对低 JSON 稳定性的模型在小说工作流中降级或提示切换模型。

### 2026-07-07 补充复核

- 已并行只读复核任务日志与后端解析路径，`task_7e86fe41b5` 当前共有 24 条 `model.response.parse_failed`。
- 失败原始响应只有两类：
  - planning 的 `outline/outline-repair/outline-retry` 返回 `很抱歉，白鹿无法回答此问题。`，不是 JSON。
  - verification 的 `chapter-window-gate/chapter-window-gate-repair` 多次 `finish_reason=length` 且 `raw_response_chars=0`，正文为空。
- 其中 `finish_reason=length + raw_response_chars=0` 共 14 条，是 LLM 摘要中 JSON 解析失败数量偏高的主要来源。
- 前端 LLM 摘要当前按事件名/文案统计 `model.response.parse_failed`，没有进一步拆分供应商拒答、空截断、普通 JSON 语法错误，因此看起来像“很多 JSON 解析失败”。

### 拒答原因判断

- 供应商没有返回明确拒答类别或错误码，`outline*` 诊断文件只有泛化文本 `很抱歉，白鹿无法回答此问题。`，因此只能基于请求内容和提示词做高概率判断。
- 本任务原始用户要求包含 `妻妾成群`，后续大纲尝试中还出现 `收服美女`、`后宫`、`皇后归心`、`被征服` 等倾向，容易触发免费模型的安全/合规拒答。
- 本任务启用了 `douluodalu` 风格画像，提示词中包含原作名、作者名、世界观/术语和较长参考摘录，也可能触发模型对版权同人、近似续写或指定作者风格模仿的保守拒答。
- `finish_reason=length + raw_response_chars=0` 不是同一种拒答，更像章节验证阶段模型把预算消耗在推理或内部处理上，最终没有输出可解析正文。

### 复现验证计划

- 用户要求重新运行三段提示词和整体任务链，确认拒答/空截断是否仍会复现。
- 本轮只做运行验证与日志分析，不改业务代码。
- 为避免继续改变 `task_7e86fe41b5` 的恢复状态，优先新建同配置复现实验任务，原任务仅作为对照。
- 验证目标：
  - 单独重跑 `outline/outline-repair/outline-retry` 等效提示词，观察是否仍返回 `白鹿无法回答此问题`。
  - 重跑完整任务链，观察 LLM 摘要中 `model.response.parse_failed`、供应商拒答和 `finish_reason=length + raw_response_chars=0` 是否复现。

### 三段提示词重跑结果

- 已使用同一模型 `bailu-2.7-free`，绕过响应缓存，直接重跑大纲阶段三段等效提示词。
- `outline`：`finish_reason=stop`，返回 `很抱歉，白鹿无法回答此问题。`
- `outline-repair`：`finish_reason=stop`，返回 `很抱歉，白鹿无法回答此问题。`
- `outline-retry`：`finish_reason=stop`，返回 `很抱歉，白鹿无法回答此问题。`
- 三次请求耗时均约 1 秒，`reasoning_chars=0`，说明这是模型/供应商当前直接拒答，不是 JSON parser 或前端摘要展示导致。

### 完整任务链复现结果

- 已创建同配置复现实验任务 `task_383e5f91a6`，输入、模型、风格画像与 `task_7e86fe41b5` 保持一致。
- 任务链大纲阶段：
  - `outline` 真实请求复现拒答，原始响应 `很抱歉，白鹿无法回答此问题。`
  - `outline-repair` 真实请求复现拒答，原始响应 `很抱歉，白鹿无法回答此问题。`
  - `outline-retry` 命中旧响应缓存，因此任务链继续执行；如果无缓存，按单独重跑结果大概率会继续拒答。
- 任务链最终状态：`waiting_manual_action`。
- 事件统计：共 82 条事件，`model.response.parse_failed` 共 22 条，`cache.hit` 1 条。
- `model.response.parse_failed` 分布：
  - planning / `outline`：1
  - planning / `outline-repair`：1
  - drafting / `chapter-08`：1
  - verification / `chapter-window-gate`：9
  - verification / `chapter-window-gate-repair`：8
  - verification / `fix-issues`：1
  - verification / `fix-issues-repair`：1
- 诊断文件确认：
  - `chapter-window-gate` 多次为 `finish_reason=length` 且 `raw_response_chars=0`。
  - `chapter-window-gate-repair` 既有空截断，也有 `很抱歉，白鹿无法回答此问题。`
  - `fix-issues` 返回 Markdown 代码围栏包裹的长 JSON，并因 `finish_reason=length` 截断，无法解析。
  - `fix-issues-repair` 为 `finish_reason=length` 且 `raw_response_chars=0`。
- 结论：问题可稳定复现，不是偶发 UI 摘要误报。大纲阶段拒答与提示词内容强相关；章节验证/修复阶段还存在结构化 JSON 输出预算与空截断处理不足。

## 修复项 3、4 执行记录

用户选择执行修复项 3、4：

- 3：给 `verify_chapter_window()` 和 `fix-issues` 增加强结构化 JSON 空截断、截断 JSON 的专用重试与更短输出协议。
- 4：LLM 摘要拆分显示供应商拒答、空截断、截断 JSON、普通 JSON 解析失败，避免全部混在“JSON 解析失败”里。

本轮不处理大纲 prompt 的原创化/合规改写，不处理输入安全改写。

### 版本号前置检查

- 按项目规则再次检查 `<子目录（项目目录）>/src/Cargo.toml`，当前仓库中 `apps/agent-runtime/src/Cargo.toml` 不存在。
- 仓库内对应后端为 Python 项目，因此本轮仍不执行 Cargo workspace patch 版本递增。

### 最终选择与执行范围

- 用户最终选择执行第 3 项和第 4 项。
- 第 3 项：给 `verify_chapter_window()` 和 `fix-issues` 增加强结构化 JSON 空截断、截断 JSON 的专用重试与更短输出协议。
- 第 4 项：LLM 摘要拆分显示供应商拒答、空截断、截断 JSON、普通 JSON 解析失败。
- 本轮未处理第 2 项的提示词安全改写，避免扩大范围。

### 实际修复内容

- 后端 `StoryEngine.verify_chapter_window()`：
  - 复用全文验证的极短 JSON 专用提示。
  - 对 `finish_reason=length|max_tokens` 且响应正文为空的章节窗口验证，先走专用重试，不再先记录普通 JSON 解析失败。
  - 重试预算使用 `_verification_retry_max_tokens()`，优先在模型输出上限内提高预算。
- 后端 `StoryEngine.fix_verified_issues()`：
  - 显式传入 generation `max_tokens`，避免修复补丁请求预算不明确。
  - 新增 `patches` 专用截断重试提示，要求只输出需要改动章节的 `patches` JSON，不输出 Markdown 代码围栏和分析过程。
  - 对非空截断 JSON 与空截断响应都使用同预算专用重试，避免先进入通用 repair 产生额外 `parse_failed`。
- 前端 LLM 摘要：
  - 在 `debug-diagnostics.mjs` 中新增 JSON 解析失败分类统计。
  - 分类顺序：供应商拒答/content_filter、空截断、截断 JSON、普通 JSON 解析失败。
  - 在 `debug-panel.tsx` 的 LLM 摘要区域新增四个指标 chip：`供应商拒答`、`空截断`、`截断 JSON`、`普通 JSON 失败`。

### 本轮验证结果

- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py -k "verify_chapter_window_retries_empty_truncated_response_with_tight_prompt or fix_verified_issues_retries_truncated_json_with_short_patch_prompt" -q`：通过，2/2。
- `npm test -- src/features/task-run/debug-diagnostics.test.mjs`：通过，22/22。
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py -q`：通过，48/48。
- `npm test -- src/features/task-run/debug-diagnostics.test.mjs src/features/task-run/task-run-state.test.mjs src/features/task-run/task-action-state.test.mjs`：通过，40/40。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/app/llm/story_engine.py apps/agent-runtime/tests/test_story_engine_context.py`：通过。
- `npm run lint`：通过。

### 当前状态

- 修复项 3、4 已实现并通过目标与相邻验证。
- 用户已确认收口，本文档已从 `worklog/active/` 移动到 `worklog/archive/`。

### 2026-07-07 测试服务启动记录

- 已启动后端：`http://localhost:8000`，健康检查 `/api/health` 返回 `{"status":"ok"}`。
- 已启动前端：`http://localhost:3000`，首页返回 200。
- 后端日志：`.dev-logs/backend-8000.log`；前端日志：`.dev-logs/web-3000.log`。
- 运行项目接口冒烟检查通过，临时测试任务 ID：`task_6ca3377832`。
