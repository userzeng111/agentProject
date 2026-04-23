# 镜中人固定章节锚点恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让小说任务恢复明确落到章节级固定节点，保证已完成章节不丢失，并按约定装配恢复上下文。

**Architecture:** 在后端恢复合同中补足章节级预览字段，由 `TaskService` 基于小说项目、批次、章节文件与历史快照解析恢复目标；恢复运行态时按“上一章全文 + 目标章计划 + 目标章草稿 + 近 20 章摘要 + 结构化状态卡”装配上下文。前端只负责展示后端给出的明确恢复目标，不再自行猜测章节语义。

**Tech Stack:** Python、FastAPI、Pydantic、SQLAlchemy、pytest、React/TypeScript

---

### Task 1: 失败测试锁定恢复预览语义

**Files:**
- Modify: `apps/agent-runtime/tests/test_task_service_review_resume.py`

- [ ] **Step 1: 写失败测试，覆盖章节级恢复预览**
- [ ] **Step 2: 运行定向 pytest，确认按当前实现失败**
- [ ] **Step 3: 最小实现后端恢复预览字段**
- [ ] **Step 4: 再跑定向 pytest，确认通过**

### Task 2: 失败测试锁定恢复上下文装配

**Files:**
- Modify: `apps/agent-runtime/tests/test_task_service_review_resume.py`
- Modify: `apps/agent-runtime/tests/test_story_engine_context.py`

- [ ] **Step 1: 写失败测试，覆盖恢复第 N 章时带第 N-1 章全文、带近 20 章摘要、优先带目标章草稿**
- [ ] **Step 2: 跑定向 pytest，确认失败原因正确**
- [ ] **Step 3: 最小实现恢复种子装配逻辑**
- [ ] **Step 4: 再跑定向 pytest，确认通过**

### Task 3: 实现后端章节级恢复目标

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Modify: `apps/agent-runtime/app/storage/db_models.py`
- Modify: `apps/agent-runtime/app/storage/db_repository.py`

- [ ] **Step 1: 为恢复预览增加章节号/批次范围/草稿复用字段**
- [ ] **Step 2: 为小说项目增加当前生成章节号持久化字段**
- [ ] **Step 3: 在继续创作与恢复链路中写入/消费该字段**
- [ ] **Step 4: 保持现有恢复模式兼容**

### Task 4: 实现前端恢复预览展示

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/features/task-recovery/recovery-dialog.tsx`

- [ ] **Step 1: 同步前端类型**
- [ ] **Step 2: 把恢复目标展示成章节级文案**
- [ ] **Step 3: 保持旧字段兼容**

### Task 5: 定向验证

**Files:**
- Modify: `worklog/active/功能开发/20260423-04-镜中人固定章节锚点恢复设计.md`

- [ ] **Step 1: 运行后端相关 pytest**
- [ ] **Step 2: 运行前端相关测试或构建**
- [ ] **Step 3: 将实现结果和风险回写 worklog**
