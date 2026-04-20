# 问题标题
`waiting_manual_action` 恢复原因前端展示缺失排查

## 用户原始诉求
只读确认当前前端还缺哪些字段来展示 `waiting_manual_action` 的恢复原因。需要检查 `app/domain/models.py`、`app/application/task_service.py`、`web/src/lib/types.ts`、`web/src/features/task-run/task-run-client.tsx`，回答：
1. 后端是否已返回 `error_message`；
2. 前端类型/UI 哪些地方缺展示。

## 当前状态
已完成：缺失项已按排查结论补齐，`waiting_manual_action` 页面可显示自然语言与结构化恢复原因。

## 观察记录
- 后端 `TaskRecord` 已包含 `error_message` 字段，`task_store.set_waiting_manual_action()` 会把传入的恢复阻塞说明写入 `task.error_message`，并在事件里写入 `payload.reason = missing_stable_state`。
- `TaskService.recover_task()` 在无法自动恢复时会调用 `set_waiting_manual_action()`，默认消息为“任务当前无法恢复，缺少可恢复的稳定产物，已转入待人工处理。”。
- `TaskService.get_workspace()` 返回的是 `WorkspaceResponse.meta = TaskSummary`，`TaskService._to_summary()` 当前没有把 `error_message` 带进返回体。
- 前端 `TaskRecord` 类型里有 `error_message`，但 `WorkspaceMeta` 没有该字段；`task-run-client.tsx` 里 `waiting_manual_action` 只展示“恢复任务”按钮和通用摘要，没有专门渲染恢复原因。

## 结果
- 已采用双来源展示：
  - `meta.error_message` 用于自然语言说明
  - `task.recovery.blocked.payload.reason` 用于结构化原因标签
- 已在 `task-run-client.tsx` 的 `waiting_manual_action` 区域补充展示与提示文案。
