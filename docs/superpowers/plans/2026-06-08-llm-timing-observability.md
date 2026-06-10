# LLM Timing Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为小说创作主链路补齐前后端、网关与代理的耗时观测能力，并在 `1 章 + 3 章` 样本上输出可对账的最慢步骤结论。

**Architecture:** 以后端 `gateway_client` 作为 LLM 主事实源，前端只补统一请求关联能力，本地反向代理仅采 HTTP 元数据做交叉验证。首期展示走日志和 `tasklog` 聚合，不新增诊断面板。

**Tech Stack:** FastAPI, httpx, Next.js 14, Node fetch, Python pytest, Node test runner

---

### Task 1: 后端 LLM 步骤耗时事实源

**Files:**
- Modify: `apps/agent-runtime/app/llm/gateway_client.py`
- Modify: `apps/agent-runtime/app/llm/story_engine.py`
- Modify: `apps/agent-runtime/app/agents/base.py`
- Modify: `apps/agent-runtime/app/application/task_service/runner.py`
- Modify: `apps/agent-runtime/app/application/task_service/queries.py`
- Test: `apps/agent-runtime/tests/test_gateway_timing_observability.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 跑失败测试确认缺少 `stage/exchange_label/first_token_ms/duration_ms/attempt` 聚合**
- [ ] **Step 3: 最小实现后端日志与任务聚合**
- [ ] **Step 4: 跑后端测试确认通过**

### Task 2: 前端统一请求关联日志

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
- Test: `apps/web/src/lib/api.test.mjs`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 跑失败测试确认拿不到 `X-Request-ID` 与请求耗时**
- [ ] **Step 3: 最小实现前端结构化请求日志**
- [ ] **Step 4: 跑前端测试确认通过**

### Task 3: 本地反向代理辅助采样

**Files:**
- Create: `apps/agent-runtime/scripts/llm_timing_proxy.py`
- Create: `apps/agent-runtime/tests/test_llm_timing_proxy.py`
- Modify: `apps/agent-runtime/.env.example`
- Modify: `worklog/active/backend-performance/20260608-01-后端链路耗时与最长LLM步骤观测设计.md`

- [ ] **Step 1: 写失败测试**
- [ ] **Step 2: 跑失败测试确认代理日志缺失 HTTP 元数据**
- [ ] **Step 3: 最小实现代理采样脚本与配置说明**
- [ ] **Step 4: 跑代理测试确认通过**

### Task 4: 样本验证与结果记录

**Files:**
- Modify: `worklog/active/backend-performance/20260608-01-后端链路耗时与最长LLM步骤观测设计.md`

- [ ] **Step 1: 跑 `1 章` 样本并记录对账结果**
- [ ] **Step 2: 跑 `3 章` 样本并记录对账结果**
- [ ] **Step 3: 总结最慢步骤、首 token 最慢步骤与代理偏差**
- [ ] **Step 4: 补充验证命令与残余风险**
