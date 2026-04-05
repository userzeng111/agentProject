# 多Agent Supervisor 架构第一阶段落地计划 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不替换现有小说生成主链路的前提下，落地第一阶段 Supervisor 骨架：显式的规划模型、子任务/Agent 运行记录、可持久化的初始拆解结果，以及最小可运行的 supervisor planning 入口。

**Architecture:** 第一阶段只补“规划层骨架”，不接真实调度执行。先新增 `SupervisorPlan` 作为唯一真相，收拢 `subtasks/dependencies/planner_version`；再提供纯函数 planner 和最小 graph adapter；最后由 `TaskService.create_task()` 调用 planner 注入 seed 计划，并让 `TaskLogStore` 能持久化/重载这些字段。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、LangGraph、unittest

---

## 本阶段明确范围

### 本阶段要做
- 为任务增加 `SupervisorPlan`、`SubtaskRecord`、`AgentRunRecord`
- 提供可预测的小说任务初始拆解器
- 提供最小 `build_supervisor_graph()` 规划入口
- 在 `create_task()` 时写入初始 supervisor seed
- 让持久化与重载支持新字段，并验证旧快照兼容

### 本阶段明确不做
- 不切换现有 `main_graph` 为真实 supervisor 调度
- 不实现 agent 级上下文隔离与缓存命名空间
- 不实现 agent 级 trace / resume / checkpoint
- 不实现真实 worker 路由、预算治理、聚合器裁决
- 不修改现有 API/UI 响应结构

---

## 文件结构与改动边界

- `apps/agent-runtime/app/domain/models.py`
  - 新增 `SubtaskStatus`、`AgentRunStatus`、`DependencyEdge`、`SubtaskRecord`、`AgentRunRecord`、`SupervisorPlan`
  - 为 `TaskRecord` 增加 `supervisor_plan` 字段
- `apps/agent-runtime/app/graph/supervisor_graph.py`
  - 新增纯函数 planner：`build_initial_supervisor_plan()`
  - 新增最小 graph adapter：`build_supervisor_graph()`
- `apps/agent-runtime/app/application/task_service.py`
  - 在 `create_task()` 中调用 planner 写入 seed
  - 仅负责调用与保存，不拼接 planner 内部细节
- `apps/agent-runtime/app/storage/task_store.py`
  - 新增 `upsert_subtask()`、`append_agent_run()`、`list_subtasks()`
  - 验证新字段持久化与 legacy 快照兼容
- `apps/agent-runtime/tests/test_supervisor_models.py`
  - 覆盖模型默认值、序列化和 legacy 兼容
- `apps/agent-runtime/tests/test_supervisor_planner.py`
  - 覆盖纯函数 planner 的阶段顺序与不变量
- `apps/agent-runtime/tests/test_supervisor_graph.py`
  - 覆盖 graph compile / invoke 合同
- `apps/agent-runtime/tests/test_task_service_supervisor_seed.py`
  - 覆盖 `create_task()` 自动写入 seed
- `apps/agent-runtime/tests/test_task_store_supervisor.py`
  - 覆盖 supervisor 持久化、重载与 legacy 兼容
- `worklog/active/agent架构/20260405-01-多agent任务流与架构合理性评审.md`
  - 记录实现进展

---

### Task 1: 为 Supervisor 补齐模型与唯一真相结构

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Create: `apps/agent-runtime/tests/test_supervisor_models.py`

- [ ] **Step 1: 写失败测试，只验证模型层能力**

```python
def test_task_record_defaults_supervisor_plan_to_none():
    task = TaskRecord(...)
    assert task.supervisor_plan is None


def test_task_record_accepts_legacy_snapshot_without_supervisor_fields():
    task = TaskRecord.model_validate({...legacy payload...})
    assert task.supervisor_plan is None
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_supervisor_models -v
```

Expected:
- 因 `TaskRecord` 尚无 `supervisor_plan` 字段与相关模型而失败

- [ ] **Step 3: 最小实现 supervisor 领域模型**

```python
class SubtaskStatus(str, Enum): ...
class AgentRunStatus(str, Enum): ...

class DependencyEdge(BaseModel):
    upstream_subtask_id: str
    downstream_subtask_id: str
    kind: str = "finish_to_start"


class SubtaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("subtask"))
    kind: str
    title: str
    status: SubtaskStatus = SubtaskStatus.PENDING
    assigned_agent: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRunRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("agentrun"))
    subtask_id: str
    agent_name: str
    role: str
    status: AgentRunStatus = AgentRunStatus.PENDING


class SupervisorPlan(BaseModel):
    planner_version: str = "v1"
    subtasks: list[SubtaskRecord] = Field(default_factory=list)
    dependencies: list[DependencyEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: 给 `TaskRecord` 增加单一 `supervisor_plan` 字段**

```python
supervisor_plan: SupervisorPlan | None = None
agent_runs: list[AgentRunRecord] = Field(default_factory=list)
```

- [ ] **Step 5: 重新运行测试确认转绿**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_supervisor_models -v
```

Expected:
- 模型测试通过

---

### Task 2: 先实现纯函数 planner，不掺 LangGraph 接线

**Files:**
- Create: `apps/agent-runtime/app/graph/supervisor_graph.py`
- Create: `apps/agent-runtime/tests/test_supervisor_planner.py`

- [ ] **Step 1: 写失败测试，定义初始拆解结果与结构不变量**

```python
def test_build_initial_supervisor_plan_returns_ordered_story_subtasks():
    plan = build_initial_supervisor_plan(payload)
    assert [item.kind for item in plan.subtasks] == [...]


def test_build_initial_supervisor_plan_sets_only_first_subtask_ready():
    statuses = [item.status.value for item in plan.subtasks]
    assert statuses == ["ready", "blocked", "blocked", "blocked", "blocked", "blocked"]


def test_build_initial_supervisor_plan_builds_unique_ids_and_linear_dependencies():
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_supervisor_planner -v
```

Expected:
- 因 `build_initial_supervisor_plan()` 不存在而失败

- [ ] **Step 3: 写最小实现**

```python
def build_initial_supervisor_plan(payload: TaskCreateRequest) -> SupervisorPlan:
    ...
    return SupervisorPlan(
        planner_version="v1",
        subtasks=subtasks,
        dependencies=dependencies,
        metadata={"task_mode": payload.mode.value},
    )
```

- [ ] **Step 4: 固定第一阶段小说业务拆解规则**

顺序固定为：
- `reference_analysis`
- `outline_planning`
- `chapter_writing`
- `chapter_review`
- `full_verification`
- `result_assembly`

规则：
- 仅首节点 `ready`
- 其余节点 `blocked`
- 依赖为线性 `finish_to_start`

- [ ] **Step 5: 重新运行测试确认转绿**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_supervisor_planner -v
```

Expected:
- planner 测试通过

---

### Task 3: 再实现最小 graph adapter，明确 compile / invoke 合同

**Files:**
- Modify: `apps/agent-runtime/app/graph/supervisor_graph.py`
- Create: `apps/agent-runtime/tests/test_supervisor_graph.py`

- [ ] **Step 1: 写失败测试，验证 graph 的最小 planning 合同**

```python
def test_supervisor_graph_invocation_returns_supervisor_plan():
    graph = build_supervisor_graph()
    result = graph.invoke({"task_id": "task-1", "input_payload": payload.model_dump(mode="json")})
    assert "supervisor_plan" in result
    assert result["supervisor_plan"]["planner_version"] == "v1"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_supervisor_graph -v
```

Expected:
- 因 `build_supervisor_graph()` 或 `SupervisorState` 合同未实现而失败

- [ ] **Step 3: 定义最小 state 与节点输出**

```python
class SupervisorState(TypedDict, total=False):
    task_id: str
    input_payload: dict[str, Any]
    supervisor_plan: dict[str, Any]


def decompose_task(state: SupervisorState) -> SupervisorState:
    payload = TaskCreateRequest.model_validate(state["input_payload"])
    plan = build_initial_supervisor_plan(payload)
    return {"supervisor_plan": plan.model_dump(mode="json")}
```

- [ ] **Step 4: 编译最小图**

```python
graph = StateGraph(SupervisorState)
graph.add_node("decompose_task", decompose_task)
graph.add_edge(START, "decompose_task")
graph.add_edge("decompose_task", END)
```

- [ ] **Step 5: 重新运行测试确认转绿**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_supervisor_graph -v
```

Expected:
- graph 合同测试通过

---

### Task 4: 让 TaskService 只调用 planner 并写入 seed

**Files:**
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Create: `apps/agent-runtime/tests/test_task_service_supervisor_seed.py`

- [ ] **Step 1: 写失败测试，验证 `create_task()` 自动写入 `supervisor_plan`**

```python
def test_create_task_seeds_supervisor_plan():
    task = service.create_task(...)
    assert task.supervisor_plan is not None
    assert task.supervisor_plan.planner_version == "v1"
    assert task.supervisor_plan.subtasks[0].status.value == "ready"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_task_service_supervisor_seed -v
```

Expected:
- 因 `create_task()` 未注入 `supervisor_plan` 而失败

- [ ] **Step 3: 在 `TaskService.create_task()` 中调用 planner**

```python
task = self.store.create_task(payload)
task.supervisor_plan = build_initial_supervisor_plan(payload)
task = self.store.save(task)
```

- [ ] **Step 4: 保持服务层边界干净**

要求：
- `TaskService` 不拼 `planner_version`
- `TaskService` 不手工序列化依赖
- `TaskService` 只调用 planner 并保存结果

- [ ] **Step 5: 重新运行测试确认转绿**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_task_service_supervisor_seed -v
```

Expected:
- seed 测试通过

---

### Task 5: 补真正的持久化与 legacy 兼容测试

**Files:**
- Modify: `apps/agent-runtime/app/storage/task_store.py`
- Create: `apps/agent-runtime/tests/test_task_store_supervisor.py`

- [ ] **Step 1: 写失败测试，验证保存后重建 store 仍能读到 supervisor 字段**

```python
store.append_agent_run(task.id, agent_run)
reloaded_store = TaskLogStore(root_dir=...)
reloaded_task = reloaded_store.get(task.id)
assert reloaded_task.supervisor_plan is not None
assert len(reloaded_task.agent_runs) == 1
```

- [ ] **Step 2: 写失败测试，验证 legacy `task.json` 仍可加载**

```python
legacy_payload = {... no supervisor fields ...}
write task.json manually
reloaded_store = TaskLogStore(root_dir=...)
task = reloaded_store.get(task_id)
assert task.supervisor_plan is None
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_task_store_supervisor -v
```

Expected:
- 因缺少辅助接口或重载逻辑兼容问题而失败

- [ ] **Step 4: 写最小实现**

```python
def upsert_subtask(self, task_id: str, subtask: SubtaskRecord) -> TaskRecord: ...
def append_agent_run(self, task_id: str, agent_run: AgentRunRecord) -> TaskRecord: ...
def list_subtasks(self, task_id: str) -> list[SubtaskRecord]: ...
```

要求：
- 继续复用 `save()` 落盘
- 不引入第二套任务快照格式

- [ ] **Step 5: 重新运行测试确认转绿**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest tests.test_task_store_supervisor -v
```

Expected:
- 持久化与 legacy 兼容测试通过

---

### Task 6: 跑新增测试与现有回归测试

**Files:**
- Test: `apps/agent-runtime/tests/test_supervisor_models.py`
- Test: `apps/agent-runtime/tests/test_supervisor_planner.py`
- Test: `apps/agent-runtime/tests/test_supervisor_graph.py`
- Test: `apps/agent-runtime/tests/test_task_service_supervisor_seed.py`
- Test: `apps/agent-runtime/tests/test_task_store_supervisor.py`
- Test: `apps/agent-runtime/tests/test_task_store_context.py`
- Test: `apps/agent-runtime/tests/test_task_service_workspace.py`
- Test: `apps/agent-runtime/tests/test_graph_context.py`
- Modify: `worklog/active/agent架构/20260405-01-多agent任务流与架构合理性评审.md`

- [ ] **Step 1: 跑新增测试**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest \
  tests.test_supervisor_models \
  tests.test_supervisor_planner \
  tests.test_supervisor_graph \
  tests.test_task_service_supervisor_seed \
  tests.test_task_store_supervisor -v
```

- [ ] **Step 2: 跑回归测试**

Run:

```bash
cd apps/agent-runtime && .venv/bin/python -m unittest \
  tests.test_task_store_context \
  tests.test_task_service_workspace \
  tests.test_graph_context -v
```

- [ ] **Step 3: 更新 worklog**

记录：
- 第一阶段 supervisor 骨架已落地
- 当前只完成 planning seed，不替换主执行流
- agent 级上下文隔离/缓存/trace 仍为下一阶段事项

- [ ] **Step 4: 收口前不主动提交**

说明：
- 本仓库要求提交前先获得用户明确授权
- 提交前还必须执行 `pwd`、`git rev-parse --show-toplevel`、`git remote -v`、`git status --short`
- 本计划到测试与 worklog 为止，不默认写提交命令

