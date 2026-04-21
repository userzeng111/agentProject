# 正文分步创建与章节持久化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为小说任务接入“目标总章节数 + 分步继续创作 + SQLite 结构化进度追踪 + 本地 md 正文双轨持久化”，并保证恢复、审核、继续创作三条链路闭环。

**Architecture:** 后端以 `TaskRecord` 扩展输入与运行态字段，在 SQLite 中新增 `novel_project / novel_outline_chapter / novel_generation_batch` 三张表承载结构化进度；正文文件仍由 `TaskLogStore` 写入本地 `tasklog/.../artifacts/chapter-xx.md`。前端创建页负责提交总章节数，运行页提供“继续创作”面板；章节审核通过后只推进当前批次，不自动开始下一批。

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, SQLite, unittest, Next.js, React, MUI

---

## 文件边界

- `apps/agent-runtime/app/domain/models.py`
  - 扩展任务输入、任务状态、工作台响应与继续创作请求模型。
- `apps/agent-runtime/app/storage/db_models.py`
  - 定义 SQLite 三张新表。
- `apps/agent-runtime/app/storage/database.py`
  - 初始化迁移与补列逻辑。
- `apps/agent-runtime/app/storage/db_repository.py`
  - 实现小说项目、章节、批次的查询、upsert、原子认领与恢复读模型。
- `apps/agent-runtime/app/storage/task_store.py`
  - 负责章节文件落盘、章节索引与工作台快照拼装。
- `apps/agent-runtime/app/application/task_service.py`
  - 接入创建、继续创作、章节审核推进、恢复判定树。
- `apps/agent-runtime/app/api/routes.py`
  - 暴露继续创作、批次状态、工作台读取接口。
- `apps/agent-runtime/tests/test_api_context.py`
  - 覆盖创建请求/响应新增字段与新接口。
- `apps/agent-runtime/tests/test_task_service_review_resume.py`
  - 覆盖等待审核、等待人工处理的恢复链路。
- `apps/agent-runtime/tests/test_batched_chapter_generation.py`
  - 新增批次幂等、最后一批 `effective_count`、租约接管、审核后阻塞回迁测试。
- `apps/web/src/lib/types.ts`
  - 扩展任务创建、工作台、继续创作、小说进度类型。
- `apps/web/src/lib/api.ts`
  - 新增继续创作与任务进度 API。
- `apps/web/src/features/task-create/create-task-client.tsx`
  - 增加目标总章节数输入与浮动范围展示。
- `apps/web/src/features/task-run/task-run-client.tsx`
  - 增加“继续创作”面板、下一章起点、剩余章节、批次输入与触发。

## 执行顺序

- Task 1 到 Task 4 为强顺序依赖，必须串行执行。
- 只有 Task 4 稳定后，Task 5 前端接入才允许开始。
- Task 6 为最终验证与收口。
- 执行方式虽然使用 subagent / agent team，但这里只允许“按任务串行切换 implementer”，不允许对共享后端核心文件并行改动。

### Task 1: 后端领域模型与数据库结构

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Modify: `apps/agent-runtime/app/storage/db_models.py`
- Modify: `apps/agent-runtime/app/storage/database.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`
- Test: `apps/agent-runtime/tests/test_batched_chapter_generation.py`

- [ ] **Step 1: 写失败测试，锁定创建请求与持久化字段**

```python
def test_create_task_accepts_target_chapter_count_and_range_fields(self) -> None:
    task = self.task_service.create_task(
        TaskCreateRequest(
            prompt="写一个医生男主的都市修罗场",
            creative_mode=CreativeMode.ORIGINAL,
            novel_size=NovelSize.LONG,
            target_chapter_count=100,
            chapter_word_min=2000,
            model_id="test-model",
        )
    )
    self.assertEqual(task.input.target_chapter_count, 100)
    self.assertEqual(task.target_chapter_count, 100)
    self.assertEqual(task.chapter_count_min, 90)
    self.assertEqual(task.chapter_count_max, 110)
```

- [ ] **Step 2: 运行单测确认当前失败**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_api_context tests.test_batched_chapter_generation -v`

Expected: 因缺少 `target_chapter_count`、数据库模型字段或响应字段而失败。

- [ ] **Step 3: 最小实现领域模型与三张新表**

```python
class ContinueDraftRequest(BaseModel):
    requested_chapter_count: int
    continue_request_id: str


class NovelProjectModel(Base):
    __tablename__ = "novel_project"
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    chapter_count_min: Mapped[int] = mapped_column(Integer, default=0)
    chapter_count_max: Mapped[int] = mapped_column(Integer, default=0)
    planned_chapter_count: Mapped[int] = mapped_column(Integer, default=0)
```

- [ ] **Step 4: 运行单测确认模型与建表通过**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_api_context tests.test_batched_chapter_generation -v`

Expected: 新字段相关断言通过，若仍有仓库层/服务层失败，进入下一任务处理。

- [ ] **Step 5: 提交当前最小变更**

```bash
git add apps/agent-runtime/app/domain/models.py \
  apps/agent-runtime/app/storage/db_models.py \
  apps/agent-runtime/app/storage/database.py \
  apps/agent-runtime/tests/test_api_context.py \
  apps/agent-runtime/tests/test_batched_chapter_generation.py
git commit -m "完善章节批次领域模型与数据库结构"
```

### Task 2: 大纲阶段硬校验与初始项目落库

**Files:**
- Modify: `apps/agent-runtime/app/llm/story_engine.py`
- Modify: `apps/agent-runtime/app/graph/main_graph.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Modify: `apps/agent-runtime/app/storage/task_store.py`
- Test: `apps/agent-runtime/tests/test_story_engine_context.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 写失败测试，锁定 `planned_chapter_count` 硬约束**

```python
def test_outline_plan_rejects_planned_count_outside_target_range(self) -> None:
    plan = {
        "working_title": "测试书",
        "logline": "测试",
        "planned_chapter_count": 120,
        "chapter_plan": [{"number": i + 1, "title": f"第{i+1}章", "goal": "推进"} for i in range(100)],
    }
    with self.assertRaises(ValueError):
        validate_story_plan(plan, chapter_count_min=90, chapter_count_max=110)


def test_outline_plan_rejects_count_mismatch_between_plan_and_list(self) -> None:
    plan = {
        "working_title": "测试书",
        "logline": "测试",
        "planned_chapter_count": 10,
        "chapter_plan": [{"number": 1, "title": "第1章", "goal": "推进"}],
    }
    with self.assertRaises(ValueError):
        validate_story_plan(plan, chapter_count_min=8, chapter_count_max=12)
```

- [ ] **Step 2: 运行单测确认当前失败**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_story_engine_context tests.test_api_context -v`

Expected: 因缺少大纲范围校验和初始项目落库而失败。

- [ ] **Step 3: 最小实现大纲校验与大纲通过后的项目初始化**

```python
def validate_story_plan(plan: dict[str, Any], *, chapter_count_min: int, chapter_count_max: int) -> None:
    planned = int(plan.get("planned_chapter_count") or 0)
    chapter_plan = list(plan.get("chapter_plan") or [])
    if planned < chapter_count_min or planned > chapter_count_max:
        raise ValueError("大纲规划章节数超出允许范围。")
    if len(chapter_plan) != planned:
        raise ValueError("大纲章节列表数量与 planned_chapter_count 不一致。")
```

- [ ] **Step 4: 在大纲审核通过时写入 `novel_project` 与 `novel_outline_chapter`**

```python
repository.seed_outline_chapters(task_id=task.id, story_plan=task.story_plan)
repository.upsert_novel_project_from_story_plan(task)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_story_engine_context tests.test_api_context -v`

Expected: 大纲范围校验与初始项目落库测试通过。

- [ ] **Step 6: 提交当前最小变更**

```bash
git add apps/agent-runtime/app/llm/story_engine.py \
  apps/agent-runtime/app/graph/main_graph.py \
  apps/agent-runtime/app/application/task_service.py \
  apps/agent-runtime/app/storage/task_store.py \
  apps/agent-runtime/tests/test_story_engine_context.py \
  apps/agent-runtime/tests/test_api_context.py
git commit -m "补齐大纲阶段章节数硬校验与项目初始化"
```

### Task 3: 仓库层与继续创作批次闭环

**Files:**
- Modify: `apps/agent-runtime/app/storage/db_repository.py`
- Modify: `apps/agent-runtime/app/storage/task_store.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Test: `apps/agent-runtime/tests/test_batched_chapter_generation.py`
- Test: `apps/agent-runtime/tests/test_task_service_review_resume.py`

- [ ] **Step 1: 写失败测试，锁定批次幂等、`effective_count`、租约接管与审核后阻塞**

```python
def test_continue_request_reuses_existing_batch_for_same_continue_request_id(self) -> None:
    first = self.service.continue_task(task.id, ContinueDraftRequest(requested_chapter_count=3, continue_request_id="req-1"))
    second = self.service.continue_task(task.id, ContinueDraftRequest(requested_chapter_count=3, continue_request_id="req-1"))
    self.assertEqual(first.pending_batch.batch_no, second.pending_batch.batch_no)


def test_continue_request_rejects_different_request_id_when_active_batch_exists(self) -> None:
    self.service.continue_task(task.id, ContinueDraftRequest(requested_chapter_count=3, continue_request_id="req-1"))
    with self.assertRaises(ValueError):
        self.service.continue_task(task.id, ContinueDraftRequest(requested_chapter_count=3, continue_request_id="req-2"))


def test_last_batch_uses_effective_count_not_requested_count(self) -> None:
    batch = repository.create_batch(task_id=task.id, requested_count=3, effective_count=1, actual_start_chapter=10)
    repository.mark_chapter_persisted(task.id, 10)
    repaired = service.recover_task(task.id, force=True)
    self.assertEqual(repaired.status, TaskStatus.WAITING_CHAPTER_REVIEW)


def test_recovery_can_take_over_expired_claim_token(self) -> None:
    batch = repository.create_batch(...)
    repository.mark_batch_claimed(task.id, batch.batch_no, claim_token="old-token", claimed_at=utc_now() - timedelta(minutes=30))
    recovered = service.recover_task(task.id, force=True)
    self.assertEqual(recovered.status, TaskStatus.DRAFTING)


def test_approved_chapter_file_drift_forces_waiting_manual_action(self) -> None:
    repository.mark_chapter_approved(task.id, 1, md_ref="tasklog/runs/task_x/artifacts/chapter-01.md", content_hash="abc")
    os.remove(chapter_path)
    recovered = service.recover_task(task.id, force=True)
    self.assertEqual(recovered.status, TaskStatus.WAITING_MANUAL_ACTION)


def test_recovery_backfills_metadata_when_file_exists_but_db_row_missing(self) -> None:
    batch = repository.create_batch(task_id=task.id, requested_count=3, effective_count=3, actual_start_chapter=1)
    write_chapter_file(task.id, 1, "# 第1章\\n正文")
    recovered = service.recover_task(task.id, force=True)
    chapter = repository.get_outline_chapter(task.id, 1)
    self.assertEqual(chapter.status, "drafted")
    self.assertEqual(chapter.artifact_state, "present")


def test_recovery_restarts_safely_when_persisted_count_is_zero(self) -> None:
    batch = repository.create_batch(task_id=task.id, requested_count=3, effective_count=3, actual_start_chapter=4)
    recovered = service.recover_task(task.id, force=True)
    self.assertEqual(recovered.pending_batch.actual_start_chapter, 4)


def test_recovery_continues_from_next_missing_chapter_without_rewriting_persisted_ones(self) -> None:
    batch = repository.create_batch(task_id=task.id, requested_count=3, effective_count=3, actual_start_chapter=4)
    write_chapter_file(task.id, 4, "# 第4章\\n正文")
    repository.mark_chapter_persisted(task.id, 4)
    recovered = service.recover_task(task.id, force=True)
    self.assertEqual(recovered.pending_batch.actual_start_chapter, 4)
    self.assertEqual(recovered.pending_batch.persisted_count, 1)


def test_recovery_blocks_on_checksum_mismatch(self) -> None:
    batch = repository.create_batch(task_id=task.id, requested_count=3, effective_count=3, actual_start_chapter=4, expected_end_chapter=6)
    write_chapter_file(task.id, 4, "# 第4章\\n被篡改正文")
    repository.mark_chapter_persisted(task.id, 4, content_hash="expected-hash", file_size=123)
    recovered = service.recover_task(task.id, force=True)
    self.assertEqual(recovered.status, TaskStatus.WAITING_MANUAL_ACTION)


def test_recovery_blocks_when_batch_consistency_tuple_is_invalid(self) -> None:
    batch = repository.create_batch(task_id=task.id, requested_count=3, effective_count=2, actual_start_chapter=4, expected_end_chapter=8)
    recovered = service.recover_task(task.id, force=True)
    self.assertEqual(recovered.status, TaskStatus.WAITING_MANUAL_ACTION)
```

- [ ] **Step 2: 运行单测确认当前失败**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_batched_chapter_generation tests.test_task_service_review_resume -v`

Expected: 因缺少继续创作服务、批次表查询、`effective_count` 判定、`claim_token` 租约接管和审核后产物漂移阻塞而失败。

- [ ] **Step 3: 最小实现仓库层与服务层**

```python
def acquire_batch_claim(...):
    with get_session() as session:
        project = session.query(NovelProjectModel).filter_by(task_id=task_id, status="ready_for_batch").one()
        project.status = "batch_generating"
        project.active_batch_no = batch.batch_no
        project.active_continue_request_id = continue_request_id
        batch.claim_token = token
        batch.claimed_at = utc_now()
        session.commit()
```

```python
if existing_batch and existing_batch.continue_request_id == continue_request_id:
    return existing_batch
if existing_batch and existing_batch.continue_request_id != continue_request_id:
    raise ValueError("当前已有活动批次，不能开启新的继续创作请求。")
```

```python
def _effective_count(requested: int, remaining: int) -> int:
    return min(requested, remaining)
```

- [ ] **Step 4: 接入租约续持、超时接管、审核后阻塞与人工修复回迁**

```python
if approved and completed_count < planned_count:
    project.status = "ready_for_batch"
elif approved:
    project.status = "waiting_verification_review"
elif not approved:
    batch.status = "rejected"
    project.status = "ready_for_batch"
```

```python
if chapter.status in {"approved", "rejected"} and chapter.artifact_state != "present":
    project.blocked_from_status = project.status
    project.status = "waiting_manual_action"
```

```python
if batch.status in {"waiting_review", "approved", "rejected", "failed"}:
    project.active_batch_no = None
    project.active_continue_request_id = ""
    batch.claim_token = ""
```

```python
if chapter_file_exists and missing_db_metadata:
    repository.backfill_chapter_artifact(
        task_id=task.id,
        chapter_number=chapter_number,
        md_ref=md_ref,
        content_hash=content_hash,
        file_size=file_size,
        status="drafted",
    )
```

```python
if batch.persisted_count == 0:
    resume_from = batch.actual_start_chapter
elif 0 < batch.persisted_count < batch.effective_count:
    resume_from = batch.actual_start_chapter + batch.persisted_count
    do_not_rewrite = list(range(batch.actual_start_chapter, resume_from))
```

```python
if stored_hash != current_hash or stored_file_size != current_file_size:
    chapter.artifact_state = "checksum_mismatch"
    project.blocked_from_status = project.status
    project.status = "waiting_manual_action"
```

```python
expected_end = batch.actual_start_chapter + batch.effective_count - 1
actual_end = None if batch.persisted_count == 0 else batch.actual_start_chapter + batch.persisted_count - 1
if batch.expected_end_chapter != expected_end or batch.actual_end_chapter != actual_end:
    project.blocked_from_status = project.status
    project.status = "waiting_manual_action"
```

- [ ] **Step 5: 运行后端测试确认通过**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_batched_chapter_generation tests.test_task_service_review_resume tests.test_api_context -v`

Expected: 继续创作、恢复、最后一批与人工处理回迁测试全部通过。

- [ ] **Step 6: 提交当前最小变更**

```bash
git add apps/agent-runtime/app/storage/db_repository.py \
  apps/agent-runtime/app/storage/task_store.py \
  apps/agent-runtime/app/application/task_service.py \
  apps/agent-runtime/tests/test_batched_chapter_generation.py \
  apps/agent-runtime/tests/test_task_service_review_resume.py \
  apps/agent-runtime/tests/test_api_context.py
git commit -m "接入正文批次持久化与恢复闭环"
```

### Task 4: API 路由与工作台读模型

**Files:**
- Modify: `apps/agent-runtime/app/api/routes.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Modify: `apps/agent-runtime/app/domain/models.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 写失败测试，锁定继续创作接口与工作台返回结构**

```python
def test_workspace_exposes_novel_progress_and_continue_panel_payload(self) -> None:
    workspace = self.client.get(f"/api/tasks/{task.id}/workspace").json()
    self.assertEqual(workspace["novel_progress"]["next_chapter_number"], 1)
    self.assertEqual(workspace["novel_progress"]["default_batch_size"], 3)


def test_continue_endpoint_returns_400_when_active_batch_exists(self) -> None:
    response = self.client.post(f"/api/tasks/{task.id}/continue", json={"requested_chapter_count": 3, "continue_request_id": "req-2"})
    self.assertEqual(response.status_code, 400)
```

- [ ] **Step 2: 运行单测确认当前失败**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_api_context -v`

Expected: 因缺少 `/continue` 路由或工作台字段不存在而失败。

- [ ] **Step 3: 最小实现 API 与返回类型**

```python
@router.post("/tasks/{task_id}/continue")
def continue_task(task_id: str, payload: ContinueDraftRequest):
    return task_service.continue_task(task_id, payload)
```

- [ ] **Step 4: 运行单测确认接口层通过**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_api_context -v`

Expected: 创建/继续创作/工作台响应相关测试通过。

- [ ] **Step 5: 提交当前最小变更**

```bash
git add apps/agent-runtime/app/api/routes.py \
  apps/agent-runtime/app/application/task_service.py \
  apps/agent-runtime/app/domain/models.py \
  apps/agent-runtime/tests/test_api_context.py
git commit -m "补齐继续创作接口与工作台进度读模型"
```

### Task 5: 前端创建页与继续创作面板

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/features/task-create/create-task-client.tsx`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`

- [ ] **Step 1: 写失败断言或最小 smoke 预期**

```text
创建页必须出现：
- 目标总章节数
- 允许浮动范围

运行页必须出现：
- 本次创建章节数
- 下一章起点
- 剩余未完成章节
- 继续创作按钮

审核页必须满足：
- 当前批次审核通过后只返回“可继续创作”
- 不自动发起下一批正文生成
```

- [ ] **Step 2: 运行现有前端 smoke，记录当前缺口**

Run: `python .agents/skills/project-interface-smoke/scripts/run_smoke.py`

Expected: 页面可访问，但不会出现上述字段或继续创作动作。

- [ ] **Step 3: 最小实现前端类型与 API**

```ts
export interface ContinueDraftPayload {
  requested_chapter_count: number;
  continue_request_id: string;
}

export function continueTask(taskId: string, payload: ContinueDraftPayload) {
  return request<TaskRecord>(`/api/tasks/${taskId}/continue`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
```

- [ ] **Step 4: 创建页接入总章节数与浮动范围**

```tsx
const chapterCountRange = useMemo(() => {
  const target = Number(payload.target_chapter_count || 0);
  return target > 0 ? `${Math.max(1, Math.floor(target * 0.9))}-${Math.max(Math.floor(target * 0.9), Math.ceil(target * 1.1))}` : "";
}, [payload.target_chapter_count]);
```

- [ ] **Step 5: 运行页接入继续创作面板与幂等键复用**

```tsx
<TextField label="本次创建章节数" value={requestedCount} />
<Button onClick={handleContinueDraft}>继续创作</Button>
```

```tsx
const continueRequestIdRef = useRef<string | null>(null);

async function handleContinueDraft() {
  const requestId = continueRequestIdRef.current ?? crypto.randomUUID();
  continueRequestIdRef.current = requestId;
  try {
    await continueTask(taskId, {
      requested_chapter_count: requestedCount,
      continue_request_id: requestId,
    });
  } finally {
    continueRequestIdRef.current = null;
  }
}
```

- [ ] **Step 6: 运行 smoke 确认前端链路可见**

Run: `python .agents/skills/project-interface-smoke/scripts/run_smoke.py`

Expected: 创建页与运行页页面可正常打开，关键资源无 404。

- [ ] **Step 7: 提交当前最小变更**

```bash
git add apps/web/src/lib/types.ts \
  apps/web/src/lib/api.ts \
  apps/web/src/features/task-create/create-task-client.tsx \
  apps/web/src/features/task-run/task-run-client.tsx \
  apps/web/src/features/task-review/task-review-client.tsx
git commit -m "接入目标章节数与继续创作前端面板"
```

### Task 6: 全链路验证

**Files:**
- Test: `apps/agent-runtime/tests/test_api_context.py`
- Test: `apps/agent-runtime/tests/test_task_service_review_resume.py`
- Test: `apps/agent-runtime/tests/test_batched_chapter_generation.py`
- Test: `apps/agent-runtime/tests/test_story_engine_context.py`
- Verify: `.agents/skills/api-full-test/scripts/run_full_test.py`
- Verify: `.agents/skills/project-interface-smoke/scripts/run_smoke.py`

- [ ] **Step 1: 运行后端目标测试集**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_story_engine_context tests.test_api_context tests.test_task_service_review_resume tests.test_batched_chapter_generation -v`

Expected: 全部通过。

- [ ] **Step 2: 运行 API 全量 smoke**

Run: `python .agents/skills/api-full-test/scripts/run_full_test.py`

Expected: `/api/tasks`、`/api/tasks/{id}/continue`、`/api/tasks/{id}/workspace`、`/api/tasks/{id}/review`、`/api/tasks/{id}/result` 均返回符合预期的状态码。

- [ ] **Step 3: 运行前端/路由 smoke**

Run: `python .agents/skills/project-interface-smoke/scripts/run_smoke.py`

Expected: 首页、创建页、运行页、审核页、结果页无静态资源 404。

- [ ] **Step 4: 手工验证关键业务链路**

```text
1. 创建一个 target_chapter_count=20 的任务
2. 审核大纲通过后确认未自动开写
3. 在运行页输入“3”触发继续创作
4. 审核当前批次通过，确认返回 ready_for_batch
5. 将最后一批请求数设为大于剩余章数，确认按 effective_count 完成
6. 人工删除一个已审核章节文件，确认任务切到 waiting_manual_action；修复后可回迁到原状态
```

- [ ] **Step 5: 汇总验证结果并准备收口**

```bash
git status --short
```

Expected: 只剩本次实现相关文件改动，准备进入归档与提交流程。
