# Next Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 verification 的边缘截断放大问题，并继续推进 drafting 下一层上下文瘦身，然后用真实 `1章 + 3章` 样本验证是否继续改善。

**Architecture:** 先对 `verification` 的 `non-empty + finish_reason=length` 增加高预算 retry，避免直接进入 repair；再在 `drafting` 阶段继续减少重复上下文与历史回灌负担。所有改动都先写失败测试，再做最小实现，最后跑真实链路样本和文本抽样。

**Tech Stack:** FastAPI, Python 3.11, pytest, Next.js runtime logs already in place, tasklog-based analysis

---

### Task 1: verification 边缘截断最小修复

**Files:**
- Modify: `apps/agent-runtime/app/llm/story_engine.py`
- Test: `apps/agent-runtime/tests/test_story_engine_context.py`

- [x] **Step 1: 写失败测试**
- [x] **Step 2: 跑失败测试确认 `non-empty + finish_reason=length` 仍直接进 repair**
- [x] **Step 3: 最小实现 verification 高预算 retry 策略**
- [x] **Step 4: 跑相关测试确认通过**

### Task 2: drafting 下一层上下文瘦身

**Files:**
- Modify: `apps/agent-runtime/app/settings/config.py`
- Modify: `apps/agent-runtime/app/llm/story_engine.py`
- Modify: `apps/agent-runtime/.env.example`
- Test: `apps/agent-runtime/tests/test_story_engine_context.py`

- [x] **Step 1: 写失败测试**
- [x] **Step 2: 跑失败测试确认当前上下文负担仍偏重**
- [x] **Step 3: 最小实现上下文瘦身**
- [x] **Step 4: 跑相关测试确认通过**

### Task 3: 回归与真实链路测试

**Files:**
- Modify: `worklog/active/backend-performance/20260610-01-下一轮性能优化规划.md`

- [x] **Step 1: 跑后端回归与 ruff**
- [x] **Step 2: 跑真实 `1章` 样本**
- [x] **Step 3: 跑真实 `3章` 样本**
- [x] **Step 4: 输出前后对比与文本抽样结论**
