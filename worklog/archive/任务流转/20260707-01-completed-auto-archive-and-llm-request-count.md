# 完成任务自动归档与 LLM 请求计数漏计问题

## 问题标题

完成任务自动归档与 LLM 请求计数漏计问题

## 用户原始诉求

头脑风暴后并设计修复下列功能：

- 现在有任务完成后并没有到已完成内容，而是自动归档了，这个问题需要调整修复。
- LLM 摘要部分里的各个字数有问题；请求计数存在问题，明明是有请求的，但是请求没有计数。

## 当前状态

已按“完成后待用户验证，用户确认后才归档”的语义完成代码修复与自动化验证。用户已确认收口，本文档已从 `worklog/active/` 移动到 `worklog/archive/`，并准备随本次修复提交。

## 初始拆分

- 完成任务自动归档：
  - 查后端 `set_completed` 是否直接写入 archive 存储态。
  - 查 dashboard 是否把 completed 任务仍归入已完成列表。
  - 查前端首页是否因 `storage_state=archive` 优先跳转归档详情，导致用户感知为“已完成内容缺失”。
- LLM 请求计数漏计：
  - 查后端 `llm_report.usage_count` 与请求/交换事件的统计口径。
  - 查前端 `requestCount` 是否只消费 `usage_count/model.usage`，没有用 `context.history.updated/cache.hit/model.response.parse_failed` 兜底。
  - 明确“请求数”应表示模型交互次数，而不是仅表示 token 用量事件数。

## 只读排查结论

### 完成任务自动归档

- `TaskLogStore.save()` 每次保存任务都会调用 `_archive_completed_task()`。
- `_archive_completed_task()` 对 `status=COMPLETED` 且 `storage_state != "archive"` 的任务无条件执行 `tasklog/runs/<task_id> -> tasklog/archive/<task_id>`，并把 `storage_state` 改为 `archive`。
- `TaskService.get_dashboard()` 当前构造 `completed_tasks` 时明确排除 `storage_state == "archive"` 的完成任务，因此自动归档后的完成任务不会出现在首页“已完成”Tab。
- 首页 `resolveTaskHref()` 当前优先判断 `storage_state === "archive"`，所以即使拿到完成任务摘要，也会优先跳 `/archive/detail/?id=...`，不是 `/result/?id=...`。
- 当前运行后端只读验证：`/api/dashboard` 返回 `completed_total=0`，但 `system_summary.archived_runs=12`，符合用户反馈。
- `/api/tasks/{task_id}/result` 已支持读取归档任务结果；问题不是结果不可读，而是列表分类与入口语义不符合“已完成内容”预期。

### LLM 摘要请求计数

- 后端 `_build_llm_report()` 里 `usage_count` 只在事件类型为 `model.usage` 时递增。
- `model.usage` 依赖供应商流式 chunk 返回 usage；如果供应商不返回 usage chunk，系统仍可能有真实模型请求、`context.history.updated`、`timing_details`、`model.response.parse_failed`，但 `usage_count` 仍为 0。
- 前端 `buildLlm()` 把 `report.usage_count` 直接显示成 `requestCount`；当后端返回 `usage_count=0` 时，会压过事件侧兜底统计。
- 因此当前“请求”实际是“token usage 事件数”，不是“模型请求/调用次数”。字段语义错位是主要根因。

## 候选方案

### 方案 A：展示语义最小修复

- 保留底层自动归档文件链路，避免影响 RAG 扫描、归档接口和现有历史数据。
- 后端 dashboard：`completed_tasks` 包含所有 `status=COMPLETED` 的任务，不再排除 `storage_state=archive`。
- 前端首页：任务卡跳转优先按 `status=completed` 进入 `/result/?id=...`，再按 `storage_state=archive` 进入归档详情。
- LLM 摘要：后端新增 `request_count` 表示真实模型调用/尝试次数；保留 `usage_count` 表示用量事件数。
- 前端 `请求` 使用 `request_count`，token 相关仍使用 `usage_total/usage_count`。

优点：改动小，兼容历史归档和 RAG；能直接修复用户可见问题。缺点：底层仍会把完成产物放在 archive 目录，只是 UI 语义改成“完成内容优先”。用户已明确不采用这个语义作为最终目标。

### 方案 B：完成后待验证，用户确认后归档（当前推荐）

- 修改 `TaskLogStore.save()` 或 `_archive_completed_task()`，完成后保留在 `tasklog/runs`，状态仍为 `completed`。
- 首页“已完成”Tab 展示刚完成任务，点击进入 `/result/?id=...` 供用户查看验证。
- 归档变成显式用户动作，例如结果页按钮“确认归档”调用后端归档接口。
- 归档后任务进入 `tasklog/archive` 与 `/archive` 列表。
- 历史已归档任务保持可读，仍可通过 `/result` 和 `/archive/detail` 查看。

优点：完成态与归档态真正分离，符合“用户查看验证后归档”的产品语义。缺点：需要补一个显式归档动作/API，并确认 RAG 只扫描已确认归档内容。

### 方案 C：双入口语义增强

- dashboard 同时返回 `completed_tasks` 与 `archive_tasks`，完成任务即便归档也出现在已完成。
- 首页完成卡进入结果页，同时卡片增加“归档详情”次级入口。
- LLM 摘要同时显示 `请求`、`用量事件`、`交换`。

优点：信息最完整。缺点：UI 改动较方案 A 多，当前需求不一定需要。

## 推荐执行设计

- 采用方案 B。
- 后端：
  - 去掉 `TaskLogStore.save()` 对完成任务的自动归档副作用，或让 `_archive_completed_task()` 只在显式归档 API 中调用。
  - 新增/暴露显式归档方法，例如 `archive_completed_task(task_id)`，只允许 `status=COMPLETED` 且 `draft_result` 存在的任务归档。
  - `get_dashboard()`：`completed_tasks` 展示所有 `TaskStatus.COMPLETED` 且尚未归档的任务；历史已归档任务仍在 `/archive`。
  - `get_result()` 保持可读取 runs 与 archive 两类完成结果，兼容历史任务。
  - `_build_llm_report()`：新增 `request_count`，口径为 `max(usage_count, timing_count, exchange_count - runtime_response_cache_hit_count, parse_failed_request_count)`，其中 cache hit 不算真实供应商请求。
  - 对 `model.response.parse_failed` 的失败模型请求纳入 request 兜底，避免失败请求完全消失。
- 前端：
  - `resolveTaskHref()` 调整优先级：`completed -> resultHref` 先于 `archive -> archiveDetailHref`，兼容历史归档完成任务。
  - 结果页增加“确认归档”动作，成功后跳转 `/archive/detail/?id=...` 或 `/archive`。
  - `debug-diagnostics.mjs`：`requestCount` 优先使用 `report.request_count`；无后端字段时用事件侧 timing/exchange/parse_failed 兜底。
  - 保持 `交换`、`响应缓存命中`、`供应商缓存命中` 现有展示，避免把缓存命中伪装成供应商请求。
- 测试：
  - 后端存储测试：`set_completed()` 后任务仍为 `storage_state=runs`，不会自动进入 archive。
  - 后端归档 API 测试：用户显式归档 completed 任务后，任务移动到 `storage_state=archive`，并出现在 `/api/archive`。
  - 后端 dashboard 测试：未归档 completed 任务出现在 `completed_tasks`；显式归档后不再出现在 `completed_tasks`。
  - 后端 llm_report 测试：只有 `context.history.updated + timing_details`、无 `model.usage` 时 `request_count=1` 且 `usage_count=0`。
  - 后端 llm_report 测试：只有 `model.response.parse_failed` 时 `request_count` 至少为 1。
  - 前端诊断测试：`usage_count=0` 但 `request_count=1` 时请求显示 1；旧事件无 `request_count` 时可兜底。
  - 前端结果页测试：点击“确认归档”调用归档 API，成功后进入归档视图。

## 当前状态

用户已明确完成任务不能直接归档，归档需要用户查看验证后执行。修复已完成并经用户确认收口，当前已归档。

## 执行记录

### 后端完成/归档语义

- `TaskLogStore.save()` 不再在 completed 保存时自动移动到 `tasklog/archive`。
- 新增显式归档链路：`archive_completed_task(task_id)` 和 `POST /api/tasks/{task_id}/archive`。
- completed 任务保留在 `tasklog/runs`，首页 completed 列表可见；显式归档后才进入 `tasklog/archive` 与归档库。
- 结果同步测试改为断言 completed 结果仍写在 `tasklog/runs/<task_id>/result.json`。
- API 测试补充：显式归档后 `runs/<task_id>` 消失，`archive/<task_id>/result.json` 存在。
- 完成态 trace 文案从“已归档”调整为“等待用户确认归档”。

### LLM 摘要请求计数

- 后端 `llm_report` 新增 `request_count`，与 `usage_count` 分离：
  - `usage_count` 表示 token 用量事件数。
  - `request_count` 表示真实模型请求/尝试次数。
- `request_count` 从用量事件、timing/exchange、非响应缓存命中、`model.response.parse_failed` 综合兜底，避免供应商不返回 usage 时请求数为 0。
- 前端 LLM 摘要优先显示 `report.request_count`，旧数据通过 timing/exchange/parse_failed 兜底。

### 前端流转

- 首页任务卡：`completed` 状态优先进入 `/result/?id=<task_id>`，不会被归档态抢到 `/archive/detail`。
- 普通任务卡默认工作台链接统一为 `/p/<task_id>`。
- 结果页新增“确认归档”按钮，仅 completed 且未归档时展示；确认后调用归档 API 并跳转归档详情。
- `WorkspaceMeta` 补充 `storage_state` 类型，修复结果页构建类型错误。
- 归档列表文案改为“用户确认归档后的作品会进入这里”。

### 自动化验证

- 后端：
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_supervisor_seed.py -q`：9 passed。
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_task_service_supervisor_seed.py -q`：34 passed。
  - `uv run --project apps/agent-runtime ruff check ...`：All checks passed。
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/ -q`：406 passed, 1 skipped。
- 前端：
  - `npm test -- src/features/task-dashboard/task-card-state.test.mjs`：4 passed。
  - `npm test`：125 passed。
  - `npm run lint`：通过。
  - `npm run build`：通过，仅保留既有 `metadataBase` 警告。
  - `npm run test:e2e -- e2e/home-create.spec.ts e2e/review-result-archive.spec.ts --project=chromium`：15 passed。
- 启动与冒烟：
  - 已重新启动后端：`http://localhost:8000`。
  - 已重新启动前端：`http://localhost:3000`。
  - `python3 .agents/skills/project-interface-smoke/scripts/run_smoke.py --frontend-url http://localhost:3000 --backend-url http://localhost:8000`：全部冒烟检查通过。
  - smoke 创建的测试任务 `task_60315738d6` 已通过 `DELETE /api/tasks/task_60315738d6` 清理。

### 收口状态

- 用户已确认收口并要求归档提交。
- 已完成的核心验证点：
  - 任务完成后是否留在首页“已完成”而非自动归档。
  - 点击已完成任务是否进入结果页。
  - 结果页“确认归档”是否按预期进入归档库。
  - LLM 摘要“请求”是否能显示真实请求次数。
- 本文档已移动到 `worklog/archive/任务流转/`，`worklog/history.md` 已同步记录。
