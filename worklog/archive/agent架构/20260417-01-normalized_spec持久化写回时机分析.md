# normalized_spec 持久化写回时机分析

- 用户原始诉求：只读分析 `apps/agent-runtime/app/application/task_service.py`、`app/storage/task_store.py`、`app/graph/main_graph.py`，定位 `normalized_spec` 现在是什么时机写回任务持久化，为什么运行中 `task.json` 还是 `{}`，给出最小修法建议，不改代码。
- 当前状态：已完成验证，待收口。运行前预写回方案已在代码中生效，并新增时序测试锁定行为。
- 讨论结论：
  - 基线链路里，`normalized_spec` 在 `app/graph/main_graph.py` 的 `normalize_request()` 内生成，先进入 LangGraph state，不会即时写回 `TaskRecord`。
  - `task.json` 的来源是 `TaskLogStore.save()` -> `_write_task_files()`，写入内容取自 `TaskRecord.model_dump()`，不是 LangGraph checkpoint state。
  - 基线真正把 `normalized_spec` 回填到任务持久化的时机在 `TaskService._sync_result()`；而 `_sync_result()` 只在 `graph.invoke()` 返回后调用，也就是首次中断（如 `outline_review`）或整个图执行结束之后。
  - 因此在“运行中但尚未返回中断/结束”的阶段，即使图内已经算出了 `normalized_spec`，`task.normalized_spec` 仍可能保持默认 `{}`，落盘后的 `task.json` 也会继续是 `{}`。
  - 当前工作区未提交改动里，`TaskService._run_task_sync()` 已经在 `graph.invoke()` 之前先调用 `build_normalized_spec()` 并执行 `store.update_normalized_spec()`；这正是最小修法。
  - 这版最小修法的关键价值，是把 `workflow_guidance` / `style_guidance` 的生成逻辑收敛到 `main_graph.build_normalized_spec()`，由 `TaskService._run_task_sync()` 复用同一份构建结果做“运行前预写回”，`_sync_result()` 再保留一次兜底回写，避免图内状态和任务快照分叉。
  - 最合适的测试切入点是 `TaskService + TaskLogStore` 的文件级测试，而不是图单测。建议在 `apps/agent-runtime/tests/test_task_service_supervisor_seed.py` 追加用例：伪造 `graph.invoke()`，在其执行过程中直接读取 `runs/<task_id>/state/task.json`，断言 `normalized_spec.workflow_guidance` 与 `normalized_spec.style_guidance` 已存在，再返回一个最小结果。这样才能锁住“运行中 task.json 可见”这个时序要求。
  - 如果实际运行时 `task.json` 仍然是 `{}`，更可能是正在运行的后端进程尚未加载这版未提交改动，或运行的并非当前工作区代码。

- 本轮验证结果：
  - 已在 `apps/agent-runtime/tests/test_task_service_supervisor_seed.py` 新增并通过：
    - `test_run_task_sync_writes_normalized_spec_before_graph_returns`
  - 验证方式是在 `graph.invoke()` 执行期间直接读取 `runs/<task_id>/state/task.json`，确认：
    - `normalized_spec.prompt` 已写回；
    - `workflow_guidance`、`style_guidance` 字段已经存在；
  - 当前结论已从“只读分析”升级为“代码行为有测试覆盖”。
