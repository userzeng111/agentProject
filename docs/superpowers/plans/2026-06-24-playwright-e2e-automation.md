# Playwright E2E Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Playwright-based front-end/back-end automation flow that covers current user-facing branches, API contracts, and the `a27c48b` Agent debug center regression surface.

**Architecture:** Add Playwright Test to `apps/web`, with a config that starts/reuses FastAPI on `127.0.0.1:8000` and Next.js on `127.0.0.1:3000`. Split coverage into API smoke, real backend page checks, mocked UI branch checks, and last-commit regression checks so slow LLM/RAG paths are not part of the default E2E suite.

**Tech Stack:** Playwright Test, Next.js 14, FastAPI, existing node test runner, existing pytest/ruff validation.

---

### Task 1: Install And Configure Playwright

**Files:**
- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/e2e/README.md`

- [ ] **Step 1: Install Playwright Test**

Run: `npm --prefix apps/web install --save-dev @playwright/test`

Expected: `apps/web/package.json` and `apps/web/package-lock.json` include `@playwright/test`.

- [ ] **Step 2: Add scripts**

Add scripts:

```json
"test:e2e": "playwright test",
"test:e2e:ui": "playwright test --ui",
"test:e2e:trace": "playwright test --trace on"
```

- [ ] **Step 3: Add config**

Create `apps/web/playwright.config.ts` with:
- `testDir: "./e2e"`
- Chromium desktop and mobile projects
- `baseURL: "http://127.0.0.1:3000"`
- trace on first retry
- screenshot only on failure
- two `webServer` entries for FastAPI and Next.js
- `reuseExistingServer: !process.env.CI`

- [ ] **Step 4: Verify RED/GREEN config**

Run: `npm --prefix apps/web run test:e2e -- --list`

Expected: command runs and lists zero tests or newly added tests after later tasks.

### Task 2: Build E2E Helpers

**Files:**
- Create: `apps/web/e2e/helpers/api.ts`
- Create: `apps/web/e2e/helpers/fixtures.ts`
- Create: `apps/web/e2e/helpers/assertions.ts`

- [ ] **Step 1: API helper**

Implement helpers:
- `apiBase()`
- `createDraftTask(request)`
- `deleteTaskIfAllowed(request, taskId)`
- `uploadTextAsset(request, taskId, filename, content)`
- `expectJsonOk(response, label)`
- `expectNoSensitiveText(locatorOrPage)`

- [ ] **Step 2: Fixture helper**

Implement mock helpers:
- `mockCommonCatalogRoutes(page)`
- `mockTaskWorkspace(page, workspace)`
- `mockArchiveRoutes(page)`
- `mockChatStream(page, chunks)`
- fixture builders for `created`, `sources_ingested`, `waiting_manual_action`, `failed`, `cancelled`, `completed`, `running`, `state_conflict`.

- [ ] **Step 3: Verify helper imports**

Run: `npm --prefix apps/web run test:e2e -- --list`

Expected: no TypeScript import errors.

### Task 3: API Baseline Suite

**Files:**
- Create: `apps/web/e2e/api-smoke.spec.ts`

- [ ] **Step 1: Write API tests first**

Cover:
- health/models/dashboard/style-profiles
- settings/rag and settings/protocols read
- create task -> read task -> workspace -> supervisor -> chapters -> artifacts
- upload UTF-8 text asset and verify task status can be read
- invalid `file-text`
- invalid task file path
- CORS local origin

- [ ] **Step 2: Run API E2E**

Run: `npm --prefix apps/web run test:e2e -- e2e/api-smoke.spec.ts --project=chromium`

Expected: initially expose any missing assumptions; after implementation pass.

### Task 4: Real Backend Navigation And Debug Center Suite

**Files:**
- Create: `apps/web/e2e/navigation.spec.ts`
- Create: `apps/web/e2e/task-workspace-debug.spec.ts`
- Create: `apps/web/e2e/last-commit-regression.spec.ts`

- [ ] **Step 1: Navigation tests**

Cover:
- `/`, `/create`, `/archive`, `/settings`
- created task `/tasks/?id=<task_id>`
- archive detail if archive list has items

- [ ] **Step 2: Debug center regression**

For a created task:
- open `/tasks/?id=<task_id>`
- click `调试`
- assert modules: `诊断结论`, `实时连接`, `LLM 摘要`, `Agent Trace`, `上下文/RAG`, `状态对账`, `最近事件`, `证据链接`
- assert workspace API has `pending_review_summary` and `rag_status`
- assert sensitive field names/text do not appear in debug area
- assert refresh triggers another workspace request

- [ ] **Step 3: Run real backend page tests**

Run: `npm --prefix apps/web run test:e2e -- e2e/navigation.spec.ts e2e/task-workspace-debug.spec.ts e2e/last-commit-regression.spec.ts --project=chromium`

Expected: pass without triggering LLM generation.

### Task 5: Mocked UI Branch Suite

**Files:**
- Create: `apps/web/e2e/task-state-branches.spec.ts`
- Create: `apps/web/e2e/review-result-archive.spec.ts`
- Create: `apps/web/e2e/chat-settings.spec.ts`

- [ ] **Step 1: Task states**

Use route fixtures to cover:
- created
- sources_ingested
- planning/drafting/assembling
- waiting_outline_review
- ready_for_batch
- waiting_chapter_review
- waiting_verification_review
- waiting_manual_action recoverable
- failed
- cancelled
- completed
- debug state conflict

- [ ] **Step 2: Review/result/archive**

Use route fixtures to cover:
- review page without id and with review payload
- result page empty/result payload
- archive list and archive detail tabs

- [ ] **Step 3: Chat/settings**

Use route fixtures to cover:
- chat new conversation, send disabled/enabled, streamed assistant response/error
- settings RAG available/unavailable, rebuild confirm cancel, protocol table display

- [ ] **Step 4: Run branch tests**

Run: `npm --prefix apps/web run test:e2e -- e2e/task-state-branches.spec.ts e2e/review-result-archive.spec.ts e2e/chat-settings.spec.ts --project=chromium`

Expected: pass with mocked network; no LLM/RAG side effects.

### Task 6: Full Verification And Worklog

**Files:**
- Modify: `worklog/active/功能开发/20260624-02-Playwright自动化测试流程建设.md`

- [ ] **Step 1: Run full E2E**

Run: `npm --prefix apps/web run test:e2e -- --project=chromium`

Expected: pass.

- [ ] **Step 2: Run existing checks**

Run:
- `npm --prefix apps/web test`
- `npm --prefix apps/web run lint`
- `npm --prefix apps/web run build`
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_api_context.py -v`
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`

Expected: pass.

- [ ] **Step 3: Update worklog**

Record:
- coverage matrix
- commands and results
- failures fixed
- `a27c48b` regression outcome
- known excluded slow lanes

- [ ] **Step 4: Report**

Report changed files, verification evidence, residual risks, and local run command.
