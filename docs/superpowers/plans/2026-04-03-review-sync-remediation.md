# 项目评审同步问题修复计划 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复本轮 code review 中暴露的前后端同步问题，优先收口接口契约、错误态、审核入口和死状态语义。

**Architecture:** 先处理最影响联调稳定性的契约问题，再修前端页面动作与错误态，随后收敛后端状态语义与共享 schema，最后补验证与回归测试。所有改动都围绕现有页面与 API 结构增量修复，不推翻现有任务流。

**Tech Stack:** Next.js 14、React 18、TypeScript、FastAPI、Pydantic、LangGraph、pytest

---

## 文件结构与改动边界

- `apps/web/src/lib/api.ts`
  - 统一前端 API 基地址默认值与引用读取策略。
- `apps/web/src/lib/types.ts`
  - 收口前端本地类型，移除/修正后端未保证字段，补齐真实响应字段。
- `apps/web/src/features/task-run/task-run-client.tsx`
  - 修复工作台错误态、审核入口覆盖、SSE 路径收口与状态展示。
- `apps/web/src/features/task-review/task-review-client.tsx`
  - 修复审核页错误态、轮次字段读取、提交后刷新逻辑与文案。
- `apps/web/src/features/task-result/task-result-client.tsx`
  - 修复结果页错误态与工件引用展示。
- `apps/web/src/features/task-archive/archive-detail-client.tsx`
  - 修复归档详情错误态与结果页/引用联动。
- `apps/web/src/features/task-archive/archive-list-client.tsx`
  - 校准归档列表字段消费，避免依赖后端未保证字段。
- `apps/web/src/app/page.tsx`
  - 校准首页 continue/running/failed 语义与跳转说明。
- `packages/shared-schema/src/schemas.ts`
  - 补齐真实共享状态/载荷，或明确只保留真正共享的稳定模型。
- `apps/agent-runtime/app/domain/models.py`
  - 收口 `TaskCreateRequest`、`TaskRecord`、`ReviewResponse`、归档/结果响应字段。
- `apps/agent-runtime/app/application/task_service.py`
  - 修复 `auto_review` 按任务生效、review/result/archive/workspace 的字段映射与状态语义。
- `apps/agent-runtime/app/storage/task_store.py`
  - 持久化任务级 `auto_review`，清理死语义字段使用，必要时收口索引输出。
- `apps/agent-runtime/app/graph/main_graph.py`
  - 对齐真实可达状态与 review 轮次输出。
- `apps/agent-runtime/app/main.py`
  - 保留全局默认自动审核策略，但允许任务级覆盖。
- `apps/agent-runtime/tests/test_api_context.py`
  - 增补 review/result/archive 相关 API 级测试。
- `apps/agent-runtime/tests/test_task_service_review_resume.py`
  - 增补轮次字段与历史语义测试。
- `apps/agent-runtime/tests/test_task_service_workspace.py`
  - 增补 workspace 状态与 available_tabs 测试。
- `apps/agent-runtime/tests/test_graph_context.py`
  - 修正过期假设，适配 chapter-pair 流程。
- `README.md`
  - 修正文档中的前后端端口、校验方式与实际脚本说明。
- `worklog/active/agent架构/20260403-01-项目代码审查与前后端功能同步核对.md`
  - 记录修复批次推进状态。

---

### Task 1: 收口 API 基地址与页面错误态

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`
- Modify: `apps/web/src/features/task-result/task-result-client.tsx`
- Modify: `apps/web/src/features/task-archive/archive-detail-client.tsx`
- Test: `apps/web` 页面手动回归

- [ ] **Step 1: 写出错误态目标**

  需要覆盖：
  - API 默认地址与 README 一致
  - 首次加载失败时页面显示错误提示与重试入口，不再无限 loading

- [ ] **Step 2: 统一 API 基地址默认值**

  修改 `apps/web/src/lib/api.ts`：

```ts
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8001";
```

- [ ] **Step 3: 为四个详情页补显式加载态与错误态分支**

  每个页面拆成三态：

```ts
if (loading) return <LoadingView />;
if (error && !data) return <ErrorView message={error} onRetry={...} />;
return <ContentView />;
```

- [ ] **Step 4: 给错误页补“重试”按钮**

```ts
<Button variant="outlined" onClick={() => void load()}>
  重新加载
</Button>
```

- [ ] **Step 5: 手动验证**

Run:

```bash
npm --prefix apps/web run dev
```

Expected:
- 关闭后端时，任务页/审核页/结果页/归档详情页都能显示错误提示
- 配置正确后能恢复正常读取

---

### Task 2: 收口审核入口、结果/归档页面动作与文案

**Files:**
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
- Modify: `apps/web/src/features/task-review/task-review-client.tsx`
- Modify: `apps/web/src/features/task-result/task-result-client.tsx`
- Modify: `apps/web/src/features/task-archive/archive-detail-client.tsx`
- Test: `apps/web` 页面手动回归

- [ ] **Step 1: 明确页面动作矩阵**

  目标状态：
  - `waiting_outline_review` -> 显示进入审核
  - `waiting_chapter_review` -> 显示进入审核
  - `waiting_verification_review` -> 显示进入审核
  - `completed` -> 显示查看结果

- [ ] **Step 2: 修复工作台审核入口覆盖**

```ts
const canReview = [
  "waiting_outline_review",
  "waiting_chapter_review",
  "waiting_verification_review",
].includes(workspace.meta.status);
```

- [ ] **Step 3: 修复审核页提交后的刷新策略**

```ts
await router.push(`/review/${taskId}`);
router.refresh();
```

  或直接重新请求 review 数据，避免停留旧内容。

- [ ] **Step 4: 修正文案**

  重点修复：
  - `verification_review` 页按钮文案
  - 结果页/归档页中“引用仅字符串展示”的描述

- [ ] **Step 5: 补结果/归档中的引用查看能力**

  最小实现：

```ts
<Button onClick={() => window.open(targetRef, "_blank")}>查看文件</Button>
```

  或在页面内调用 `fetchTextRef` 弹窗预览。

- [ ] **Step 6: 手动验证**

Expected:
- 三类审核状态都能从工作台进入审核页
- 审核提交后不会停留旧内容
- 结果页/归档页能查看正文/工件引用

---

### Task 3: 收口前后端协议与 review/result/archive 响应字段

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Modify: `apps/web/src/lib/types.ts`
- Modify: `packages/shared-schema/src/schemas.ts`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 先定义“后端实际保证的字段集合”**

  优先统一：
  - `ReviewResponse.revision_count`
  - `ArchiveDetailResponse` 实际字段
  - `ArtifactIndexItem` 是否返回 `json_ref`
  - `ArchiveTaskSummary.entry_refs` 是否保留

- [ ] **Step 2: 后端补真实字段或删掉伪字段**

  推荐策略：
  - `ReviewResponse` 明确增加 `revision_count`
  - `archive/result` 如不打算返回 `json_ref/entry_refs`，前端类型移除

```python
class ReviewResponse(BaseModel):
    ...
    revision_count: int = 0
```

- [ ] **Step 3: `get_review()` 显式映射轮次字段**

```python
return ReviewResponse(
    ...,
    revision_count=review.revision_count,
)
```

- [ ] **Step 4: 收口共享 schema**

  二选一：
  - 补齐真实稳定共享模型
  - 明确共享包只承载 `TaskMode/StoryPlan`，并删掉过期 `TaskStatus`

  本计划更推荐前者，至少让 `TaskStatus` 与真实运行状态一致。

- [ ] **Step 5: 同步前端本地类型**

```ts
export interface ReviewResponse {
  ...
  revision_count?: number;
}
```

- [ ] **Step 6: 运行 API 测试**

Run:

```bash
cd apps/agent-runtime
PYTHONPATH=. pytest tests/test_api_context.py -q
```

Expected:
- review/result/archive 响应字段断言通过

---

### Task 4: 修复任务级 auto_review 与后端死状态语义

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Modify: `apps/agent-runtime/app/storage/task_store.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Modify: `apps/agent-runtime/app/main.py`
- Modify: `apps/agent-runtime/app/graph/main_graph.py`
- Test: `apps/agent-runtime/tests/test_task_service_workspace.py`
- Test: `apps/agent-runtime/tests/test_task_service_review_resume.py`

- [ ] **Step 1: 明确策略**

  推荐行为：
  - 服务级 `auto_review` 作为默认值
  - 任务创建参数 `auto_review` 可覆盖默认值

- [ ] **Step 2: 持久化任务级配置**

```python
task = TaskRecord(
    ...,
    auto_review=payload.auto_review,
)
```

- [ ] **Step 3: 运行图时读取任务级值**

```python
initial_state = {
    ...,
    "auto_review": task.auto_review,
    "auto_review_policy": task.auto_review_policy or self.auto_review_policy,
}
```

- [ ] **Step 4: 收口死状态**

  处理方式二选一：
  - 如果近期不会实现，就从前端分支、dashboard 归类、文案里去掉死状态语义
  - 如果要保留，就补真实可达流程与接口

  当前建议：先收口为“未实现，不对前端承诺”。

- [ ] **Step 5: 修复 `/review` 历史场景下的类型回退**

  不要在 `pending_review is None` 时无脑返回 `outline_review`，至少应返回：
  - 最近一次真实审核类型
  - 或明确的 `history_review`

- [ ] **Step 6: 跑服务层测试**

Run:

```bash
cd apps/agent-runtime
PYTHONPATH=. pytest tests/test_task_service_workspace.py tests/test_task_service_review_resume.py -q
```

Expected:
- `auto_review` 按任务生效
- workspace/review 状态语义稳定

---

### Task 5: 修复首页/归档语义与验证链路

**Files:**
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/features/task-archive/archive-list-client.tsx`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Modify: `README.md`
- Test: `apps/agent-runtime/tests/test_graph_context.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 收口首页 continue/running/failed 语义**

  先决定 `cancelled` 是否继续出现在 continue。

- [ ] **Step 2: 校准归档页描述**

  如果 archive 只承载 completed 任务，前端文案要明确：

```tsx
<Typography>已完成任务会自动归档到这里。</Typography>
```

  并避免给失败/取消任务归档的暗示。

- [ ] **Step 3: 修正文档**

  `README.md` 至少修复：
  - 默认端口
  - lint 当前是交互式初始化，不应写成现成校验手段
  - 推荐使用真实可运行的测试命令

- [ ] **Step 4: 修正过期测试**

  `test_graph_context.py` 需要适配当前 chapter-pair 流程，不再依赖旧 `generate_draft` 假设。

- [ ] **Step 5: 执行回归**

Run:

```bash
cd apps/agent-runtime
PYTHONPATH=. pytest tests/test_graph_context.py tests/test_api_context.py -q
```

Expected:
- 关键 API 与图上下文测试通过

---

### Task 6: 统一验证与收口

**Files:**
- Modify: `worklog/active/agent架构/20260403-01-项目代码审查与前后端功能同步核对.md`
- Test: 前后端联调手工检查

- [ ] **Step 1: 前端检查**

Run:

```bash
npm --prefix apps/web run build
```

Expected:
- 构建通过

- [ ] **Step 2: 后端检查**

Run:

```bash
cd apps/agent-runtime
PYTHONPATH=. pytest -q
```

Expected:
- 至少核心 review/result/archive/workspace 测试通过

- [ ] **Step 3: 手工联调**

  验证最小场景：
  - 创建任务
  - 进入工作台
  - 大纲审核
  - 章节审核
  - 验证审核
  - 结果页
  - 归档页

- [ ] **Step 4: 更新 worklog**

  记录：
  - 已修复项
  - 未修复项
  - 回归结果
  - 剩余风险

- [ ] **Step 5: 提交**

```bash
git add apps/web apps/agent-runtime packages/shared-schema README.md worklog docs/superpowers/plans
git commit -m "修复前后端同步问题与页面错误态"
```
