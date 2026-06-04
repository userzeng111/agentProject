# 第二批性能埋点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补充后台任务、服务层、存储、数据库、LLM、RAG 与 checkpoint 的可定位性能日志。

**Architecture:** 新增轻量 `app.observability.performance` 工具，统一输出 `event status duration_ms key=value` 风格日志；各业务模块只在关键边界加 span，不改变业务流程。测试以 fake gateway / fake RAG backend / 临时 tasklog 和 SQLite 为主，不触发真实 LLM。

**Tech Stack:** FastAPI 后端、Python logging、SQLAlchemy SQLite、pytest、unittest mock。

---

### Task 1: 统一性能日志工具

**Files:**
- Create: `apps/agent-runtime/app/observability/performance.py`
- Test: `apps/agent-runtime/tests/test_performance_observability.py`

- [x] 写失败测试：`performance_span` 正常和异常时记录 `event/status/duration_ms`。
- [x] 实现 `performance_span()`、`log_performance()` 和字段格式化。
- [x] 运行定向测试。

### Task 2: 后台任务、服务层和 TaskStore I/O 埋点

**Files:**
- Modify: `apps/agent-runtime/app/application/task_service/core.py`
- Modify: `apps/agent-runtime/app/application/task_service/runner.py`
- Modify: `apps/agent-runtime/app/storage/task_store.py`
- Test: `apps/agent-runtime/tests/test_performance_observability.py`

- [x] 写失败测试：后台 runner 记录 `background_task_start/end` 且日志上下文包含 `task_id`。
- [x] 写失败测试：`TaskLogStore.save()` 记录 `task_store_save` 和 `task_store_io`。
- [x] 实现最小埋点，不改变任务状态语义。
- [x] 运行定向测试。

### Task 3: DB、LLM、RAG 与 checkpoint 埋点

**Files:**
- Modify: `apps/agent-runtime/app/storage/database.py`
- Modify: `apps/agent-runtime/app/llm/gateway_client.py`
- Modify: `apps/agent-runtime/app/rag/service.py`
- Modify: `apps/agent-runtime/app/rag/rebuild_service.py`
- Modify: `apps/agent-runtime/app/graph/checkpointer.py`
- Test: `apps/agent-runtime/tests/test_performance_observability.py`

- [x] 写失败测试：`get_session()` 记录 `db_session`。
- [x] 写失败测试：同步流式 LLM 完成时记录 `llm_stream_sync_metrics` 的 chunk/finish_reason。
- [x] 写失败测试：RAG search 记录 `rag_search`。
- [x] 实现最小埋点。
- [x] 运行定向测试。

### Task 4: 验证

**Files:**
- Update: `worklog/active/backend-performance/20260603-01-rebuild性能数据库异步化分析.md`

- [x] 运行新增定向测试。
- [x] 运行相关后端测试文件。
- [x] 运行后端全量测试。
- [x] 运行 Ruff。
- [x] 按需运行项目 smoke。
- [x] 更新 worklog 验证记录。
