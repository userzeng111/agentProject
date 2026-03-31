# Context Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为小说 Agent 运行时补齐模型能力聚合、上下文管理、上下文压缩、缓存与前端模型能力展示。

**Architecture:** 保持 `TaskService -> Graph -> StoryEngine` 主链不变，在模型调用前新增上下文装配节点；新增 `model_catalog` 聚合网关模型能力，新增 `context/` 管理上下文预算、压缩与缓存，并将上下文快照持久化到 `tasklog/context`。

**Tech Stack:** FastAPI, LangGraph, LangChain, Pydantic, Next.js, TypeScript

---

### Task 1: 后端测试与领域模型扩展

**Files:**
- Create: `apps/agent-runtime/tests/test_model_catalog.py`
- Create: `apps/agent-runtime/tests/test_context_manager.py`
- Modify: `apps/agent-runtime/app/domain/models.py`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 运行 `python -m unittest` 验证失败**
- [ ] **Step 3: 补充模型能力、上下文状态等领域模型**
- [ ] **Step 4: 再次运行测试，直到通过**

### Task 2: 模型能力聚合与 API 扩展

**Files:**
- Create: `apps/agent-runtime/app/llm/model_catalog.py`
- Modify: `apps/agent-runtime/app/llm/story_engine.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Modify: `apps/agent-runtime/app/api/routes.py`
- Modify: `apps/agent-runtime/app/main.py`

- [ ] **Step 1: 写失败测试，要求 `/models` 返回能力画像**
- [ ] **Step 2: 实现 model catalog 聚合层**
- [ ] **Step 3: 调整 TaskService 与 dashboard 模型摘要**
- [ ] **Step 4: 运行后端测试验证通过**

### Task 3: 上下文管理器、压缩与持久化

**Files:**
- Create: `apps/agent-runtime/app/context/models.py`
- Create: `apps/agent-runtime/app/context/cache_store.py`
- Create: `apps/agent-runtime/app/context/compressor.py`
- Create: `apps/agent-runtime/app/context/assembler.py`
- Create: `apps/agent-runtime/app/context/manager.py`
- Modify: `apps/agent-runtime/app/graph/main_graph.py`
- Modify: `apps/agent-runtime/app/storage/task_store.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Modify: `apps/agent-runtime/app/llm/story_engine.py`

- [ ] **Step 1: 写失败测试，要求能生成并落盘上下文快照**
- [ ] **Step 2: 实现上下文预算、装配、压缩与缓存**
- [ ] **Step 3: 将 graph 节点接入 `prepare_outline_context` 与 `prepare_draft_context`**
- [ ] **Step 4: 运行后端测试验证通过**

### Task 4: 前端类型适配与模型能力展示

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/features/task-create/create-task-client.tsx`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`

- [ ] **Step 1: 先让类型检查失败，锁定新字段契约**
- [ ] **Step 2: 实现模型能力展示与上下文状态展示**
- [ ] **Step 3: 运行 `npm exec tsc --noEmit --pretty false` 验证通过**

### Task 5: 全链路验证与文档回写

**Files:**
- Modify: `worklog/active/agent架构/20260331-02-上下文管理器与缓存压缩规划.md`

- [ ] **Step 1: 运行后端单元测试**
- [ ] **Step 2: 运行前端类型检查**
- [ ] **Step 3: 回写 worklog 当前状态与落地结果**
