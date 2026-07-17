# StoryEngine 严格 JSON 解析缺失

## 用户原始诉求

当前任务提示“需要人工处理”，运行失败：`'StoryEngine' object has no attribute '_parse_strict_json'`；恢复面板同时显示任务正在后台执行，需定位并修复运行异常。

## 当前状态

已收口。实现与验证已完成，随本批修复归档并提交。

## 定位结论与拟议方案

- 受影响任务为 `task_4db3ce9787`。总纲生成和自动审核均成功；在 `plan_chapter_batch` 节点、`StoryEngine.build_chapter_plan_batch()` 的第 638 行失败。
- 该方法调用了不存在的 `self._parse_strict_json()`。`StoryEngine` 与其父类均未定义此方法；现有公共解析入口是父类 `BaseAgent._strip_and_parse_json()`。这是章节分批大纲路径被启用后首次实际触达的遗留调用。
- 失败发生在模型响应已解析并已记录用量、上下文链之后，和模型可用性、RAG、审核耗时无关。现有测试使用 Fake 引擎，未覆盖真实 `StoryEngine` 的该分支。
- 恢复提示中的“任务正在后台执行”来自异常线程尚未执行 `finally` 清理时的短暂保护。当前只读查询已确认活动运行标记释放，任务处于 `waiting_manual_action`，可执行“回填最近稳定阶段”；不是持久的恢复状态错误。
- 拟以现有解析入口替换遗留调用，并新增真实 `StoryEngine.build_chapter_plan_batch()` 回归测试，覆盖数组响应，防止缺失私有方法或批次数组转换再次导致任务中断。修复部署后可对该任务执行“回填最近稳定阶段”，回到待大纲审核并继续批次流程。

## 实施结果

- 章节批次响应已兼容实际模型返回的 `{\"chapters\": [...]}`，直接提取已解析的章节数组，不再调用不存在的 `_parse_strict_json`。
- 增加真实 `StoryEngine.build_chapter_plan_batch()` 回归测试，覆盖该包装响应向 `ChapterPlan` 的转换。
- 修复已 amend 到当前提交 `25270d4`。

## 验证结果

- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py apps/agent-runtime/tests/test_outline_windowing.py -q`：55 项通过。
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/app/llm/story_engine.py apps/agent-runtime/tests/test_story_engine_context.py`：通过。
- `git diff --check`：通过。
