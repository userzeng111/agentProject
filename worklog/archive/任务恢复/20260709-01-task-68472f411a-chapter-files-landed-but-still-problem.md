# task_68472f411a 章节文件已落盘但仍出现问题分析

## 问题标题

task_68472f411a 章节文件已落盘但仍出现问题分析

## 用户原始诉求

用户反馈：任务 `task_68472f411a` 的章节文件不是已经落盘了吗，为什么还有这种问题，需要综合分析。

## 当前状态

已确认任务目录 `tasklog/runs/task_68472f411a` 存在，且 `chapters/01-08` 的 `.json`、`.md` 以及 `chapters/index.json` 均已落盘；已完成恢复链路修复实现，正在进行验证与实际任务恢复确认。

## 初始风险与约束

- 不直接修改代码，先完成证据链分析。
- 需要区分“文件已落盘”和“系统元数据/任务状态已确认可继续”是否一致。
- 需要避免把未提交的第十三批后端修复误回退或混入本次分析之外的修改。

## 2026-07-09 综合分析结论

- 文件层面确认正常：
  - `tasklog/runs/task_68472f411a/chapters/01-08.json` 与 `01-08.md` 均存在且非空。
  - `chapters/index.json` 是 8 条列表，数量与实际章节文件一致。
  - `/api/tasks/task_68472f411a/chapters` 可返回 8 章正文，说明章节读取接口链路可用。
- 任务状态仍阻塞：
  - `task.json`、`state/task.json`、`meta.json`、`tasks_index` 均显示 `status/current_stage=waiting_manual_action`。
  - 错误信息为：`运行失败：模型返回的 JSON 无法解析：很抱歉，白鹿无法回答此问题。`
  - `trace/current.json` 显示后台异常收束在待人工处理状态。
- 直接失败点不是章节文件缺失，而是最终验证修复链路：
  - 第 8 章已生成后，进入 `full-story-verification`，验证报告成功返回，指出莫离关系、雪皇后转变、天律手段等问题。
  - 随后进入 `fix-issues`，模型 `bailu-2.7-free` 返回 `很抱歉，白鹿无法回答此问题。`，原始响应 14 字符，不是 JSON。
  - `fix-issues-repair` 再次请求仍返回同样拒答，导致 `model.response.parse_failed`，随后 `task.recovery.blocked` 与 `task.error_recorded`。
- DB 元数据确实与文件层不一致：
  - `novel_project` 无该任务记录。
  - `novel_generation_batch` 无该任务记录。
  - `novel_outline_chapter` 有 8 条，但均为 `status=outline_planned`、`artifact_state=pending`，`md_ref/json_ref/content_hash` 为空，`file_size=0`。
  - `novel_chapter_plan_batch` 有第 1 批计划且已 approved。
- 结果态未生成：
  - `task.json` 顶层 `story_plan=None`、`draft_result=None`。
  - 代码路径中只有工作流走到 `assemble_result` 并由 `TaskService` 调用 `set_completed()` 后才会产生 `draft_result` 和完成态。
  - 当前任务在 `fix_verified_issues` 抛错前没有走到 `assemble_result`，因此不会进入已完成内容。

## 根因判断

这是两个问题叠加：

1. 直接导致 UI 停在问题状态的是 `verification/fix-issues` 阶段模型拒答，结构化 JSON 修复结果无法解析，任务被转入 `waiting_manual_action`。
2. 章节文件虽然已落盘，但 DB 中章节 artifact 元数据没有同步回填，且 `draft_result` 没有生成；所以系统不能仅凭磁盘文件存在就判定任务已完成。

## 后续修复方向

- 短期恢复：受控调用恢复到稳定章节态，确认能基于 `chapters/index.json` 与 `chapters/NN.json` 重建 `story_plan`、`novel_project`、章节 artifact 元数据，并回到可继续或可重试验证状态。
- 模型失败处理：`fix-issues` 遇到明确拒答/非 JSON 时，不应直接把已完整落盘的 8 章任务留在不可用状态；可考虑换模型重试、跳过修复进入人工验证、或生成“待人工确认但可查看结果”的中间状态。
- 数据修复：需要一个显式 backfill/repair 路径，扫描已存在的章节 JSON/MD，补齐 `novel_outline_chapter.md_ref/json_ref/content_hash/file_size/artifact_state`，避免 DB 长期显示 pending。
- 完成态兜底：当章节数量已达到计划数量且文件索引完整，但 `draft_result` 缺失时，应提供从章节文件重建 `draft_result` 的恢复能力，避免“正文已在磁盘但结果页不可达”。

## 2026-07-09 修复执行记录

- 新增回归测试覆盖两个入口：
  - `recover_task(force=True)` 在大纲历史存在且章节文件已连续完整时，应直接恢复为 `completed`，并回填 `novel_project` 与 `novel_outline_chapter` artifact 元数据。
  - `_mark_failed_unless_stable()` 在后台异常发生但章节文件已连续完整时，应直接重建 `draft_result` 并完成任务，而不是转入待人工处理。
- 实现共享恢复逻辑：
  - 恢复链路读取章节时，历史快照缺失可回退读取 `chapters/NN.json`。
  - 当连续章节数达到 `story_plan.planned_chapter_count` 时，使用已落盘章节重建 `DraftResult`、artifacts，并调用 `store.set_completed()`。
  - 同步创建/更新 `novel_project`，回填每章 `md_ref/json_ref/content_hash/file_size/artifact_state`，并将项目状态更新为 `completed`。
- 已通过验证：
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_recovery_chapter_progress.py -q`
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_batched_chapter_generation.py -q`

## 当前待确认

- 已对真实任务 `task_68472f411a` 执行 `recover_task(force=True)`：
  - 任务状态已从 `waiting_manual_action` 恢复为 `completed`。
  - `draft_result` 已重建，章节数为 8。
  - `novel_project` 已创建，状态为 `completed`，`completed_chapter_count=8`，`next_chapter_number=9`。
  - 8 条 `novel_outline_chapter` 均已回填 `md_ref/json_ref/content_hash/file_size/artifact_state=present`。
  - `result.json`、`result.md`、`artifacts/index.json` 已生成。
- 后端 8000 已重启，API 验证：
  - `/api/health` 返回 200。
  - `/api/tasks/task_68472f411a` 返回 `status=completed` 且包含 `draft_result`。
  - `/api/tasks/task_68472f411a/chapters` 返回 8 章。
  - `/api/tasks/task_68472f411a/result` 返回 200。
- 前端 3000 保持运行，首页与 `/result/?id=task_68472f411a` 返回 200。
- 本问题尚未归档，需用户测试确认后再按流程收口。
