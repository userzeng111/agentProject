# Recovery Flow Explicitization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make recovery on workspace/review pages explicit, previewable, and action-specific while preserving the current silent state reconciliation strategy.

**Architecture:** Add a backend recovery decision matrix that produces explicit `allowed_actions`, `recovery_options`, and per-action previews without forcing execution during read paths. Then build a shared frontend recovery dialog that consumes those fields on workspace and review pages, defaults to task default model, and supports the secondary `restart_from_input` path with clear consequences.

**Tech Stack:** FastAPI, Pydantic, TaskService/TaskLog persistence, Next.js App Router, MUI, repository unittest suite, `npm run build`

---

## File Structure

### Backend

- Modify: `apps/agent-runtime/app/domain/models.py`
  - Add request/response models for explicit recovery modes and recovery metadata.
- Modify: `apps/agent-runtime/app/api/routes.py`
  - Accept structured recovery payload with `recovery_mode` and `model_id`.
- Modify: `apps/agent-runtime/app/application/task_service.py`
  - Implement recovery decision matrix, read-safe preview generation, explicit recover execution semantics, and reconciliation exposure.
- Test: `apps/agent-runtime/tests/test_task_service_workspace.py`
  - Lock workspace read semantics, reconciliation flags, and recovery preview payloads.
- Test: `apps/agent-runtime/tests/test_task_service_review_resume.py`
  - Lock review read semantics, explicit recover branches, and restart behavior.
- Test: `apps/agent-runtime/tests/test_api_context.py`
  - Lock HTTP payloads for workspace/review/recover.

### Frontend

- Modify: `apps/web/src/lib/types.ts`
  - Add typed recovery metadata and recover request payload.
- Modify: `apps/web/src/lib/api.ts`
  - Send `recovery_mode` + `model_id`.
- Create: `apps/web/src/features/task-recovery/recovery-state.mjs`
  - Pure helper for deriving current recovery option, current preview, and model candidate filtering.
- Create: `apps/web/src/features/task-recovery/recovery-state.test.mjs`
  - Node-level tests for recovery helper logic.
- Create: `apps/web/src/features/task-recovery/recovery-dialog.tsx`
  - Shared MUI dialog used by workspace/review pages.
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
  - Replace coarse “恢复任务” flow with explicit recovery panel + dialog.
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`
  - Add recovery area, explicit dialog, and review-invalidated empty state after restart.

### Documentation / Tracking

- Modify: `worklog/active/功能开发/20260422-07-用户视角功能完善方向梳理.md`
  - Record plan path and move status from design review to implementation planning.

### Notes

- This repo currently has no `Cargo.toml`; the patch version rule in `AGENTS.md` is not applicable to this implementation.
- Do not change unrelated active files in the dirty worktree.

---

### Task 1: Define Backend Recovery Contract

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Test: `apps/agent-runtime/tests/test_task_service_workspace.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: Write the failing backend contract tests**

```python
def test_workspace_exposes_explicit_recovery_contract():
    workspace = service.get_workspace(task.id)
    assert workspace.allowed_actions == ["recover_to_stable", "restart_from_input"]
    assert workspace.recommended_action == "recover_to_stable"
    assert workspace.recovery_options[0]["action"] == "recover_to_stable"
    assert "preview" in workspace.recovery_options[0]

def test_workspace_reconciliation_is_explicit():
    workspace = service.get_workspace(task.id)
    assert workspace.state_reconciled is True
    assert workspace.reconciliation_kind == "stale_review_state"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/agent-runtime
uv run python -m unittest \
  tests.test_task_service_workspace.TaskServiceWorkspaceTests.test_workspace_exposes_explicit_recovery_contract \
  tests.test_api_context.ApiContextIntegrationTests.test_workspace_endpoint_returns_default_and_last_action_model_fields \
  -v
```

Expected: FAIL because `WorkspaceResponse` / HTTP payloads do not yet expose the recovery contract.

- [ ] **Step 3: Add minimal contract models**

Implement in `apps/agent-runtime/app/domain/models.py`:

```python
class RecoveryMode(str, Enum):
    RECOVER_TO_STABLE = "recover_to_stable"
    RESTART_FROM_INPUT = "restart_from_input"


class RecoveryPreview(BaseModel):
    target_stage: str
    target_stage_label: str
    will_resume_generation: bool
    default_model_id: str
    last_action_model_id: str = ""
    allowed_model_ids: list[str] = Field(default_factory=list)
    fallback_actions: list[str] = Field(default_factory=list)


class RecoveryOption(BaseModel):
    action: str
    label: str
    kind: str
    available: bool
    reason_unavailable: str = ""
    preview: RecoveryPreview | None = None


class RecoveryRequest(BaseModel):
    recovery_mode: RecoveryMode = RecoveryMode.RECOVER_TO_STABLE
    model_id: str = ""
```

Also extend `WorkspaceResponse` / `ReviewResponse` with:

```python
allowed_actions: list[str] = Field(default_factory=list)
recommended_action: str = ""
blocked_reason: str = ""
state_reconciled: bool = False
reconciliation_kind: str = ""
reconciliation_summary: str = ""
recovery_options: list[RecoveryOption] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/agent-runtime
uv run python -m unittest \
  tests.test_task_service_workspace.TaskServiceWorkspaceTests.test_workspace_exposes_explicit_recovery_contract \
  tests.test_task_service_workspace.TaskServiceWorkspaceTests.test_workspace_meta_exposes_error_message_for_waiting_manual_action \
  -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/agent-runtime/app/domain/models.py apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_api_context.py
git commit -m "细化恢复链路后端契约模型"
```

---

### Task 2: Implement Recovery Decision Matrix and Read-Safe Semantics

**Files:**
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Test: `apps/agent-runtime/tests/test_task_service_workspace.py`
- Test: `apps/agent-runtime/tests/test_task_service_review_resume.py`

- [ ] **Step 1: Write failing tests for read-path boundaries**

```python
def test_get_workspace_only_reconciles_lightweight_state_without_restart():
    workspace = service.get_workspace(task.id)
    assert workspace.state_reconciled is True
    assert workspace.recommended_action == "recover_to_stable"
    assert store.get(task.id).current_stage != "planning"

def test_get_review_does_not_trigger_restart_from_input():
    review = service.get_review(task.id)
    assert review.recommended_action in {"recover_to_stable", "restart_from_input"}
    assert store.get(task.id).status != TaskStatus.PLANNING
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/agent-runtime
uv run python -m unittest \
  tests.test_task_service_workspace.TaskServiceWorkspaceTests.test_workspace_meta_exposes_error_message_for_waiting_manual_action \
  tests.test_task_service_review_resume.TaskServiceReviewResumeTests.test_recover_task_marks_unrecoverable_task_waiting_manual_action \
  -v
```

Expected: FAIL because current read paths still directly call `recover_task()` and may cross into execute-style recovery.

- [ ] **Step 3: Implement explicit matrix helpers**

Add focused helpers in `apps/agent-runtime/app/application/task_service.py`:

```python
def _reconcile_task_for_read(self, task: TaskRecord) -> tuple[TaskRecord, dict[str, Any]]:
    ...

def _build_recovery_contract(self, task: TaskRecord, *, include_restart: bool) -> dict[str, Any]:
    ...

def _build_recovery_option_for_stable(self, task: TaskRecord) -> dict[str, Any]:
    ...

def _build_recovery_option_for_restart(self, task: TaskRecord) -> dict[str, Any]:
    ...
```

Rules to encode:
- Read paths may only apply lightweight reconciliation (for example stale review-state sync).
- Read paths may not trigger `_retry_task_from_original_input`.
- `recover_to_stable` and `restart_from_input` each carry their own `preview`.
- If no stable target exists, `recover_to_stable.available = false`, while `restart_from_input` may still be available.

Then wire `get_workspace()` and `get_review()` to:
- reconcile for read
- build recovery contract
- return it without executing restart

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/agent-runtime
uv run python -m unittest \
  tests.test_task_service_workspace \
  tests.test_task_service_review_resume \
  -v
```

Expected: PASS for recovery-related assertions

- [ ] **Step 5: Commit**

```bash
git add apps/agent-runtime/app/application/task_service.py apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_task_service_review_resume.py
git commit -m "明确读取链路与恢复决策边界"
```

---

### Task 3: Make `/recover` Explicit and Non-Fallback

**Files:**
- Modify: `apps/agent-runtime/app/api/routes.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`
- Test: `apps/agent-runtime/tests/test_task_service_review_resume.py`

- [ ] **Step 1: Write failing tests for explicit recover semantics**

```python
def test_recover_endpoint_accepts_recovery_mode_and_model_id():
    response = client.post(
        f"/api/tasks/{task.id}/recover",
        json={"recovery_mode": "recover_to_stable", "model_id": "gpt-5.4"},
    )
    assert response.status_code == 200

def test_recover_to_stable_does_not_fallback_to_restart_when_unavailable():
    with self.assertRaisesRegex(ValueError, "当前没有可回填的稳定阶段"):
        service.recover_task(task.id, force=True, model_id="gpt-5.4", recovery_mode="recover_to_stable")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/agent-runtime
uv run python -m unittest \
  tests.test_api_context.ApiContextIntegrationTests.test_recover_endpoint_forwards_action_model_override \
  tests.test_task_service_review_resume.TaskServiceReviewResumeTests.test_recover_task_requeues_planning_with_model_override_when_no_stable_state \
  -v
```

Expected: FAIL because `/recover` does not yet distinguish modes and `recover_to_stable` still falls through to restart behavior.

- [ ] **Step 3: Implement explicit recover mode handling**

Update route signature:

```python
@router.post("/tasks/{task_id}/recover")
def recover_task(task_id: str, payload: RecoveryRequest | None = None):
    ...
```

Update service signature:

```python
def recover_task(
    self,
    task_id: str,
    force: bool = False,
    model_id: str | None = None,
    recovery_mode: str = "recover_to_stable",
) -> TaskRecord:
```

Behavior:
- `recover_to_stable`: attempt stable recovery only; if unavailable, raise `ValueError`
- `restart_from_input`: only explicit restart path may call `_retry_task_from_original_input`
- validate `model_id` against allowed model IDs for the chosen action

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/agent-runtime
uv run python -m unittest tests.test_api_context tests.test_task_service_review_resume -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/agent-runtime/app/api/routes.py apps/agent-runtime/app/application/task_service.py apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_task_service_review_resume.py
git commit -m "显式化恢复模式与恢复接口语义"
```

---

### Task 4: Add Shared Frontend Recovery State Helper

**Files:**
- Create: `apps/web/src/features/task-recovery/recovery-state.mjs`
- Create: `apps/web/src/features/task-recovery/recovery-state.test.mjs`
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: Write failing helper tests**

```javascript
import { derivePrimaryRecoveryAction, resolveRecoveryPreview, filterRecoveryModels } from "./recovery-state.mjs";

test("falls back to view plan when stable recovery unavailable", () => {
  const result = derivePrimaryRecoveryAction({
    recovery_options: [
      { action: "recover_to_stable", available: false },
      { action: "restart_from_input", available: true },
    ],
  });
  expect(result.label).toBe("查看恢复方案");
});

test("filters model catalog by allowed_model_ids", () => {
  const models = [{ id: "gpt-5.4" }, { id: "glm-5.1" }];
  expect(filterRecoveryModels(models, ["glm-5.1"])).toEqual([{ id: "glm-5.1" }]);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
node --test src/features/task-recovery/recovery-state.test.mjs
```

Expected: FAIL because helper file does not exist yet.

- [ ] **Step 3: Implement helper and type additions**

Add frontend types:

```ts
export interface RecoveryPreview { ... }
export interface RecoveryOption { ... }
export interface RecoveryContractFields {
  allowed_actions?: string[];
  recommended_action?: string;
  blocked_reason?: string;
  state_reconciled?: boolean;
  reconciliation_kind?: string;
  reconciliation_summary?: string;
  recovery_options?: RecoveryOption[];
}
```

Implement helper functions:

```javascript
export function derivePrimaryRecoveryAction(recovery) { ... }
export function resolveRecoveryPreview(recovery, action) { ... }
export function filterRecoveryModels(models, allowedModelIds) { ... }
```

Update `recoverTask()` payload type:

```ts
{ recovery_mode?: "recover_to_stable" | "restart_from_input"; model_id?: string }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
node --test src/features/task-recovery/recovery-state.test.mjs
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/task-recovery/recovery-state.mjs apps/web/src/features/task-recovery/recovery-state.test.mjs apps/web/src/lib/types.ts apps/web/src/lib/api.ts
git commit -m "补齐前端恢复状态与请求契约"
```

---

### Task 5: Build Shared Recovery Dialog and Workspace Integration

**Files:**
- Create: `apps/web/src/features/task-recovery/recovery-dialog.tsx`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
- Test: `apps/web/src/features/task-recovery/recovery-state.test.mjs`

- [ ] **Step 1: Add failing helper test for unavailable stable recovery CTA**

```javascript
test("primary CTA uses view-plan label when stable recovery is unavailable", () => {
  const result = derivePrimaryRecoveryAction({
    recommended_action: "restart_from_input",
    recovery_options: [
      { action: "recover_to_stable", available: false },
      { action: "restart_from_input", available: true },
    ],
  });
  expect(result.label).toBe("查看恢复方案");
});
```

- [ ] **Step 2: Run helper test to verify it fails**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
node --test src/features/task-recovery/recovery-state.test.mjs
```

Expected: FAIL until helper/UI contract is aligned.

- [ ] **Step 3: Implement shared dialog and workspace wiring**

Shared dialog responsibilities:
- render action tabs/options
- render per-action preview
- default selected action from `recommended_action`
- default selected model from `default_model_id`
- submit `{ recovery_mode, model_id }`

Workspace page changes:
- replace coarse `恢复任务` button
- render primary CTA from `derivePrimaryRecoveryAction`
- show reconciliation banner when `state_reconciled = true`
- after success, stay on page and refresh workspace

Minimal component contract:

```tsx
<RecoveryDialog
  open={open}
  recovery={workspace}
  models={models}
  onClose={...}
  onConfirm={async ({ recoveryMode, modelId }) => ...}
/>
```

- [ ] **Step 4: Run build to verify integration**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/task-recovery/recovery-dialog.tsx apps/web/src/features/task-run/task-run-client.tsx apps/web/src/features/task-recovery/recovery-state.test.mjs
git commit -m "接入工作台恢复确认面板"
```

---

### Task 6: Integrate Review Page and Invalidated Review Empty State

**Files:**
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`
- Modify: `apps/web/src/features/task-recovery/recovery-dialog.tsx`
- Test: `apps/web/src/features/task-recovery/recovery-state.test.mjs`

- [ ] **Step 1: Add failing helper test for review invalidation state**

```javascript
test("restart_from_input on review page produces invalidated-review state", () => {
  const result = derivePostRecoveryViewState({
    page: "review",
    recoveryMode: "restart_from_input",
    nextStatus: "planning",
  });
  expect(result.kind).toBe("review_invalidated");
});
```

- [ ] **Step 2: Run helper test to verify it fails**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
node --test src/features/task-recovery/recovery-state.test.mjs
```

Expected: FAIL until helper/view-state branch exists.

- [ ] **Step 3: Implement review page integration**

Behavior:
- add dedicated recovery area, not mixed with review approval/rejection actions
- on `recover_to_stable` success:
  - stay on page
  - refresh current review when still valid
- on `restart_from_input` success:
  - stay on same URL
  - render empty state:

```tsx
<Alert severity="info">
  当前审核上下文已失效，任务已按原始输入重新开始。
</Alert>
<Button href={workspaceHref(taskId)}>打开工作台</Button>
```

- [ ] **Step 4: Run build to verify integration**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/web
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/task-review/task-review-client.tsx apps/web/src/features/task-recovery/recovery-dialog.tsx apps/web/src/features/task-recovery/recovery-state.test.mjs
git commit -m "接入审核页恢复面板与失效空态"
```

---

### Task 7: Full Verification and Tracking Update

**Files:**
- Modify: `worklog/active/功能开发/20260422-07-用户视角功能完善方向梳理.md`

- [ ] **Step 1: Run backend regression suite**

Run:

```bash
cd /home/user01/WorkSpace/AgentProject/apps/agent-runtime
uv run python -m unittest \
  tests.test_task_service_workspace \
  tests.test_task_service_review_resume \
  tests.test_api_context \
  -v
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

- [ ] **Step 4: Update worklog status**

Record:
- implemented recovery explicitization
- contract fields added
- workspace/review recovery dialog added
- verification commands and outcomes

- [ ] **Step 5: Commit**

```bash
git add worklog/active/功能开发/20260422-07-用户视角功能完善方向梳理.md
git commit -m "记录恢复链路显式化实施结果"
```

