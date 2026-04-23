# Model Refresh Contract Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify model refresh behavior across task-related pages so users always refresh manually, always see refresh status near the selector, and are forced to reselect when the current model becomes invalid.

**Architecture:** Reuse the existing `/api/models?refresh=true` contract and build a shared frontend refresh-state pattern rather than changing backend cache policy. Normalize the four task-related pages around the same refresh entrypoint, the same status presentation, and the same “invalid means blocked, never auto-fallback” rule.

**Tech Stack:** Next.js App Router, React, MUI, existing frontend API client, existing backend model catalog metadata, `node --test`, `npm run build`

---

## File Structure

### Shared Frontend Utilities

- Modify: `apps/web/src/lib/types.ts`
  - Add a small shared `ModelRefreshState` type for task pages.
- Create: `apps/web/src/features/task-models/model-refresh-state.mjs`
  - Pure helper for formatting refresh status and validating selected models.
- Create: `apps/web/src/features/task-models/model-refresh-state.test.mjs`
  - Node-level tests for refresh-state helper behavior.

### Page Integrations

- Modify: `apps/web/src/app/page.tsx`
  - Normalize homepage model refresh display to the same contract wording used on task pages.
- Modify: `apps/web/src/features/task-create/create-task-client.tsx`
  - Add manual refresh button, refresh status display, and invalid-selection blocking.
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
  - Replace ad hoc refresh messaging with unified status display and explicit blocking.
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`
  - Replace ad hoc refresh messaging with unified status display and explicit blocking.

### Tracking

- Modify: `worklog/active/功能开发/20260422-07-用户视角功能完善方向梳理.md`
  - Record plan path and implementation scope for the model refresh batch.

### Notes

- This plan intentionally does not touch chat page model refresh.
- This plan intentionally does not change backend TTL policy in `ModelCatalogService`.
- Avoid any automatic fallback to task default model or first available model after refresh.

---

### Task 1: Add Shared Model Refresh Helper

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Create: `apps/web/src/features/task-models/model-refresh-state.mjs`
- Create: `apps/web/src/features/task-models/model-refresh-state.test.mjs`

- [ ] **Step 1: Write the failing helper tests**

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import {
  formatModelRefreshStatus,
  isCurrentSelectionValid,
  resolveSelectionAfterRefresh,
} from "./model-refresh-state.mjs";

test("invalid current selection stays invalid after refresh", () => {
  const result = resolveSelectionAfterRefresh({
    currentModelId: "gpt-5.4",
    availableModels: [{ id: "glm-5.1" }],
  });
  assert.equal(result.selectedModelId, "");
  assert.equal(result.invalidated, true);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject
node --test apps/web/src/features/task-models/model-refresh-state.test.mjs
```

Expected: FAIL because helper file does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add shared type to `apps/web/src/lib/types.ts`:

```ts
export interface ModelRefreshState {
  loading: boolean;
  error: string;
  fetchedAt?: string;
  cacheAgeSeconds?: number;
  cacheTtlSeconds?: number;
  cached?: boolean;
}
```

Create helper in `apps/web/src/features/task-models/model-refresh-state.mjs`:

```javascript
export function isCurrentSelectionValid(modelId, models) { ... }
export function resolveSelectionAfterRefresh({ currentModelId, availableModels }) { ... }
export function formatModelRefreshStatus(meta) { ... }
```

Rules:
- invalid selection clears to `""`
- never auto-fallback to first available
- missing cache metadata still yields a stable display string

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject
node --test apps/web/src/features/task-models/model-refresh-state.test.mjs
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/types.ts apps/web/src/features/task-models/model-refresh-state.mjs apps/web/src/features/task-models/model-refresh-state.test.mjs
git commit -m "提炼任务页模型刷新共享状态"
```

---

### Task 2: Normalize Homepage Refresh Status

**Files:**
- Modify: `apps/web/src/app/page.tsx`
- Test: `apps/web/src/features/task-models/model-refresh-state.test.mjs`

- [ ] **Step 1: Extend helper test for refresh status formatting**

```javascript
test("formatModelRefreshStatus exposes fetched time and cache age", () => {
  const text = formatModelRefreshStatus({
    fetchedAt: "2026-04-23T10:00:00Z",
    cacheAgeSeconds: 12,
    cacheTtlSeconds: 300,
    cached: true,
  });
  assert.match(text, /12/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject
node --test apps/web/src/features/task-models/model-refresh-state.test.mjs
```

Expected: FAIL until formatter handles metadata.

- [ ] **Step 3: Update homepage integration**

In `apps/web/src/app/page.tsx`:
- keep existing refresh button
- replace ad hoc cache copy with helper-driven status string
- keep homepage as global default-model page only
- ensure wording matches task pages:
  - refresh button label
  - “最近拉取时间 / 当前缓存年龄 / 当前是否命中缓存”

- [ ] **Step 4: Run build to verify it passes**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/page.tsx apps/web/src/features/task-models/model-refresh-state.test.mjs
git commit -m "统一首页模型刷新状态展示"
```

---

### Task 3: Add Create Page Refresh Button and Blocking

**Files:**
- Modify: `apps/web/src/features/task-create/create-task-client.tsx`
- Modify: `apps/web/src/features/task-models/model-refresh-state.mjs`
- Test: `apps/web/src/features/task-models/model-refresh-state.test.mjs`

- [ ] **Step 1: Write failing helper test for invalidation behavior**

```javascript
test("create page must block submit after selected model disappears", () => {
  const result = resolveSelectionAfterRefresh({
    currentModelId: "gpt-5.4",
    availableModels: [{ id: "glm-5.1" }],
  });
  assert.equal(result.invalidated, true);
  assert.equal(result.selectedModelId, "");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject
node --test apps/web/src/features/task-models/model-refresh-state.test.mjs
```

Expected: FAIL until helper covers this case.

- [ ] **Step 3: Integrate create page**

In `apps/web/src/features/task-create/create-task-client.tsx`:
- extract `loadModels(refresh = true)`
- add `刷新模型` button near model selector
- add refresh status line below selector
- if current `payload.model_id` disappears after refresh:
  - clear `payload.model_id`
  - show warning
  - block submit
- do not auto-fallback to first available model after refresh

- [ ] **Step 4: Run build to verify it passes**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/task-create/create-task-client.tsx apps/web/src/features/task-models/model-refresh-state.mjs apps/web/src/features/task-models/model-refresh-state.test.mjs
git commit -m "为创建页接入模型刷新与失效阻断"
```

---

### Task 4: Normalize Workspace Page Refresh Status

**Files:**
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
- Modify: `apps/web/src/features/task-models/model-refresh-state.mjs`
- Test: `apps/web/src/features/task-models/model-refresh-state.test.mjs`

- [ ] **Step 1: Add failing helper test for fail-close display**

```javascript
test("formatModelRefreshStatus shows failure message when refresh errors", () => {
  const text = formatModelRefreshStatus({ error: "读取模型列表失败" });
  assert.match(text, /失败/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject
node --test apps/web/src/features/task-models/model-refresh-state.test.mjs
```

Expected: FAIL until helper includes error formatting.

- [ ] **Step 3: Integrate workspace page**

In `apps/web/src/features/task-run/task-run-client.tsx`:
- keep manual refresh button
- replace local ad hoc model refresh handling with shared refresh state
- show refresh status under the action model selector
- if refresh invalidates current model:
  - clear selection
  - show explicit warning
  - keep `开始执行` / `继续创作` disabled
- keep recovery dialog logic unchanged except using the same refresh-state wording where relevant

- [ ] **Step 4: Run build to verify it passes**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/task-run/task-run-client.tsx apps/web/src/features/task-models/model-refresh-state.mjs apps/web/src/features/task-models/model-refresh-state.test.mjs
git commit -m "统一工作台模型刷新契约"
```

---

### Task 5: Normalize Review Page Refresh Status

**Files:**
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`
- Modify: `apps/web/src/features/task-models/model-refresh-state.mjs`
- Test: `apps/web/src/features/task-models/model-refresh-state.test.mjs`

- [ ] **Step 1: Add failing helper test for invalid model reselect requirement**

```javascript
test("invalid selected model requires manual reselect", () => {
  assert.equal(isCurrentSelectionValid("gpt-5.4", [{ id: "glm-5.1" }]), false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject
node --test apps/web/src/features/task-models/model-refresh-state.test.mjs
```

Expected: FAIL until helper clearly exposes validity state.

- [ ] **Step 3: Integrate review page**

In `apps/web/src/features/task-review/task-review-client.tsx`:
- keep manual refresh button in selector area
- add refresh status below selector
- if current review action model becomes invalid:
  - clear selection
  - show explicit warning
  - block all approve/reject buttons
- keep recovery dialog and invalidated-review flow unchanged

- [ ] **Step 4: Run build to verify it passes**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/task-review/task-review-client.tsx apps/web/src/features/task-models/model-refresh-state.mjs apps/web/src/features/task-models/model-refresh-state.test.mjs
git commit -m "统一审核页模型刷新契约"
```

---

### Task 6: Verification and Tracking Update

**Files:**
- Modify: `worklog/active/功能开发/20260422-07-用户视角功能完善方向梳理.md`

- [ ] **Step 1: Run helper tests**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject
node --test apps/web/src/features/task-models/model-refresh-state.test.mjs
```

Expected: PASS

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
npm run build
```

Expected: PASS

- [ ] **Step 3: Run runtime smoke checks**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject
curl http://127.0.0.1:8000/api/health
curl -I http://127.0.0.1:3000
```

Expected: `{"status":"ok"}` and `HTTP/1.1 200 OK`

- [ ] **Step 4: Update worklog**

Record:
- model refresh contract scope
- manual refresh button unification
- invalid selection blocking
- verification commands and outcomes

- [ ] **Step 5: Commit**

```bash
git add worklog/active/功能开发/20260422-07-用户视角功能完善方向梳理.md
git commit -m "记录模型刷新契约统一实施结果"
```

