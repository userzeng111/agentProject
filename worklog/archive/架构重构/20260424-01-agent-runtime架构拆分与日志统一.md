# agent-runtime 架构拆分与日志统一

## 用户原始诉求

将项目功能性进行分离：
1. 后端业务层、Agent 架构、RAG 内容、前端显示各自独立互不干扰
2. 保持 DRY 设计
3. 所有 Python 代码支持 OLD/logger.py 日志模块，用于追溯运行问题
4. 采用 subagent 团队模式并行处理

## 当前状态：已完成并验证通过

### 已实施修改
1. **新增工作流引擎抽象层**（`app/workflow/`）
   - `callbacks.py`：定义 `WorkflowCallbacks` 回调注册表，15个节点全部接口化
   - `engine.py`：`NovelWorkflowEngine` 封装 LangGraph 图构建，提供 `start/resume/get_state/update_state`
   - `__init__.py`：统一导出

2. **重构 `app/graph/main_graph.py` 为兼容层**
   - 提取 `build_default_callbacks()`：闭包注入 engine/rag_service 等依赖，返回 `WorkflowCallbacks`
   - `build_graph()` 同时兼容旧签名（传 engine 等参数）与新签名（传 callbacks），内部委托给 `NovelWorkflowEngine`
   - 替换日志导入为 `get_logger`

3. **解耦 TaskService 与工作流引擎**
   - `core.py`：`self.graph` → `self.workflow_engine`（`NovelWorkflowEngine` 实例）
   - `runner.py`：`self.graph.invoke()` → `self.workflow_engine.start/resume()`
   - `recovery.py`：`self.graph.update_state()` → `self.workflow_engine.update_state()`

4. **API 层 chat 端点解耦**
   - 新增 `app/services/chat_service.py`：封装 gateway_client + RAG 增强逻辑
   - `routes.py`：chat 端点改为调用 `chat_service.chat_stream/chat_completions`
   - `main.py`：组装 `ChatService` 并注入路由

5. **日志统一**
   - `app/observability/logger.py`：合并 `TimedRotatingFileHandler`（按天轮转、保留7天）+ `_StructuredFormatter`（request_id/task_id 追踪）
   - `main.py` 添加 `init_logging()` 调用
   - 全局替换 23 个文件的 `import logging` → `from app.observability import get_logger`

### 验证结果
- `uv run pytest`：142 个测试全部通过（0 失败）
- 修复了重构引入的 7 个回归测试失败：
  - `test_chat_completions_uses_updated_runtime_default_model_when_request_model_missing`：为 `ChatService` 增加 `default_model_resolver` 回调，恢复旧行为
  - `test_outline_reject_can_resume_from_planning_status` 等 6 个 TaskService 测试：在 `TaskServiceCoreMixin` 的 `graph` setter 中增加 `_FakeEngineAdapter`，兼容旧式 `FakeGraph` 注入

## 版本变更

0.1.3 → 0.1.4（已更新 `pyproject.toml`）
