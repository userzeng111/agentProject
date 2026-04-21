# 问题标题
novel_skill_service 主链路最小接入建议

# 用户原始诉求
你负责只读提出主链路最小接入建议，不改代码。范围：`main_graph.py`、`task_service.py`、`main.py`、`api/routes.py`、`story_engine.py`。目标：基于新增 `novel_skill_service`，指出最少需要改哪些函数和字段，才能让 `workflow_guidance + style_guidance` 一起进入运行时。不要修改文件，只输出精确建议。

# 当前状态
进行中：已完成主链路只读分析，确认当前运行时只有 `style_guidance` 真正进入 `StoryEngine` 提示词；`workflow_guidance` 尚未进入任务归一化和 prompt 消费链路。待输出按文件、函数、字段粒度的最小接入建议。

# 当前结论
- 需要围绕 `TaskCreateRequest -> TaskService._initial_state -> graph.normalize_request -> normalized_spec -> StoryEngine` 这条链路做最小透传。
- 目前 `style_guidance` 已在 `main_graph.py` 中进入 `normalized_spec`，并被 `story_engine.py` 的 `_style_requirements()` 消费。
- `workflow_guidance` 仍需在任务归一化和上下文装配阶段显式写入运行时状态，否则只存在于服务层但不会进入 LLM prompt。
