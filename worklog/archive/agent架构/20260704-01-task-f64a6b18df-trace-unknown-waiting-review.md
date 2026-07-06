# task_f64a6b18df Agent Trace unknown 与等待审核卡住排查

## 问题标题

task_f64a6b18df Agent Trace unknown 与等待审核卡住排查

## 用户原始诉求

任务 ID：task_f64a6b18df 这个任务现在也有问题，具体问题情况：
Agent Trace出现 unkown问题；
现在卡在等待审核，人工处理，点击之后存在问题，一直提示任务运行中，但是这个任务运行情况不确定，你先进行查找问题；

## 当前状态

已完成只读排查，未修改业务代码或任务数据。结论待用户确认下一步处理方案。

## 初始排查计划

- 核对任务 `task_f64a6b18df` 的持久化数据、事件记录、审核状态与运行中标记。
- 追踪 Agent Trace 中 `unknown` 的来源字段与渲染逻辑。
- 追踪人工审核按钮点击后的前后端接口链路，确认“任务运行中”来自真实运行状态、锁状态还是状态派生错误。
- 对比同类已归档/已修复任务的状态机处理方式，形成根因假设与修复建议。

## 只读排查结论

- 任务落盘目录为 `tasklog/runs/task_f64a6b18df/`，核心文件包括 `task.json`、`state/task.json`、`meta.json`、`events.md`、`events.tail.json`、`trace/current.json`。
- 当前任务持久化状态为 `status=waiting_manual_action`、`current_stage=waiting_manual_action`、`current_unit=null`，不是运行态。
- 最后业务失败发生在 2026-07-04 10:38:22（Asia/Shanghai），后端日志显示后台线程 `task-worker-task_f64a6b18df` 在 LangGraph 节点 `revise_chapter_pair` 调用 K2.7 时收到 403 配额错误，随后转入 `waiting_manual_action`。
- 后台日志已有 `background_task_end status=failed` 与 `background_task_failed`，当前进程列表没有 `task-worker-task_f64a6b18df`；暂未发现任务仍真实运行的证据。
- 已生成的稳定产物存在：`chapters/01.md`、`chapters/02.md`、`chapters/index.json` 与大纲文件均已落盘。
- `auto_review_trace=[]`、`agent_runs=[]`。运行页调试面板的 Agent Trace 状态来自 `debug-diagnostics.mjs`：当 `workspace.auto_review_trace` 为空时显示 `unknown`，不是任务原始 Trace 里写入了 unknown。
- `pending_review.type=outline_review` 残留，但任务状态是 `waiting_manual_action`，不属于可直接人工审核的 `waiting_outline_review / waiting_chapter_review / waiting_verification_review`。
- `/api/tasks/{id}` 可读取任务详情，但 `/api/tasks/{id}/workspace` 与 `/api/tasks/{id}/review` 当前会被 K2.7 小说流兼容性校验挡住，返回 400。
- `tasklog/model_compatibility.json` 中 K2.7 历史报告是 verified，但当前 `/api/models` 列表没有 K2.7，只把它作为默认模型显示；模型目录兼容性覆盖只对网关可见模型生效，导致读取历史任务摘要/恢复预览时仍判定 K2.7 未完成验证。

## 根因假设

1. 原始中断根因：K2.7 调用配额耗尽，正文修订节点 `revise_chapter_pair` 失败，任务被降级为 `waiting_manual_action`。
2. Agent Trace unknown 根因：自动审核 trace 未持久化到当前任务，前端调试面板对空 trace 显示 `unknown`。
3. 人工处理/审核入口异常根因：读接口与恢复预览构造期间对历史任务模型执行强校验；当前 K2.7 不在运行时模型列表中，导致页面或恢复链路被兼容性校验拦截。
4. “任务运行中”提示若再次出现，来源应是后端 `_active_runs` 的内存运行锁判断；目前从持久化状态、日志和进程看，没有真实运行证据，需要进一步复现点击时的接口响应才能确认是否有内存锁残留。

## 待确认处理方案

- 方案 A：只修复代码读路径。让 `get_workspace/get_review` 和恢复预览对历史未验证或当前不可见模型降级展示，不阻塞页面读取，并允许用户在恢复弹窗选择已验证模型。
- 方案 B：修复当前任务数据。将 `task_f64a6b18df` 从已落盘 1、2 章恢复到可继续创作状态，并切换到可用模型继续后续章节。
- 方案 C：组合处理。先做方案 A，验证页面和恢复入口正常后，再对当前任务执行方案 B。
