# 后端性能数据库可观测性第一批修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 rebuild 分支第一批明确性能、数据库、日志与安全边界问题。

**Architecture:** 第一批保留同步 SQLAlchemy 仓储，不引入 AsyncSession；通过配置化 SQLite 参数、SQLAlchemy 查询事件、任务删除单事务清理、日志 traceback 修复、路径约束和诊断落盘边界降低风险。API 全量异步化与 AsyncSession 迁移放到后续批次。

**Tech Stack:** FastAPI、Starlette、SQLAlchemy 2.x、SQLite、pytest、ruff。

---

### Task 1: 日志异常栈保留

**Files:**
- Modify: `apps/agent-runtime/app/observability/logger.py`
- Test: `apps/agent-runtime/tests/test_observability_logger.py`

- [ ] 写失败测试：`logger.exception()` 使用 `_StructuredFormatter` 时应包含 `Traceback`。
- [ ] 运行定向测试并确认失败。
- [ ] 修改 formatter，保留 request/task 上下文同时追加异常栈文本。
- [ ] 运行定向测试确认通过。

### Task 2: 数据库配置与 SQL 耗时日志

**Files:**
- Modify: `apps/agent-runtime/app/settings/config.py`
- Modify: `apps/agent-runtime/app/storage/database.py`
- Modify: `apps/agent-runtime/app/application/task_service/core.py`
- Modify: `apps/agent-runtime/.env.example`
- Test: `apps/agent-runtime/tests/test_database_observability.py`

- [ ] 写失败测试：Settings 可读取 DB 配置项。
- [ ] 写失败测试：`init_db()` 应应用 PRAGMA，并在慢查询超过阈值时记录日志。
- [ ] 实现 `DatabaseSettings` 输入或显式参数，保留旧 `init_db(db_path)` 兼容。
- [ ] 在 engine 注册 `before_cursor_execute/after_cursor_execute`。
- [ ] 日志只输出 SQL 摘要、耗时、参数个数，不输出完整参数。
- [ ] 更新 `.env.example` 占位说明。

### Task 3: 删除任务 DB 关联清理

**Files:**
- Modify: `apps/agent-runtime/app/storage/db_repository.py`
- Modify: `apps/agent-runtime/app/application/task_service/core.py`
- Test: `apps/agent-runtime/tests/test_task_service_cancellation.py`

- [ ] 写失败测试：构造任务索引、项目、章节计划、章节草稿、生成批次后删除任务，所有关联表应无残留。
- [ ] 实现 repository 单事务清理函数。
- [ ] 移除不存在的 `agent_run` 裸 SQL 删除路径。
- [ ] 让删除失败不被静默吞掉。

### Task 4: 路径、上传与诊断落盘边界

**Files:**
- Modify: `apps/agent-runtime/app/main.py`
- Modify: `apps/agent-runtime/app/api/routes.py`
- Modify: `apps/agent-runtime/app/settings/config.py`
- Modify: `apps/agent-runtime/app/application/task_service/runner.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`
- Test: `apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py`

- [ ] 写失败测试：SPA fallback 不能返回静态目录外文件。
- [ ] 写失败测试：上传超过配置大小应返回 413。
- [ ] 写失败测试：JSON 解析失败诊断默认不落完整 `raw_response` 与 `request_messages`。
- [ ] 实现 `resolve()` + `relative_to()` 静态路径约束。
- [ ] 实现上传大小配置和检查。
- [ ] 实现诊断落盘开关、最大字符数和摘要字段。

### Task 5: 验证

**Files:**
- All touched backend files.

- [ ] 运行新增定向测试。
- [ ] 运行后端相关全量 pytest。
- [ ] 运行 ruff。
- [ ] 更新 worklog 执行记录。
