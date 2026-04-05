from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.domain.models import (
    DependencyEdge,
    SubtaskRecord,
    SubtaskStatus,
    SupervisorPlan,
    TaskCreateRequest,
)


class SupervisorState(TypedDict, total=False):
    task_id: str
    input_payload: dict[str, Any]
    supervisor_plan: dict[str, Any]


_STORY_SUBTASK_SPECS: list[tuple[str, str]] = [
    ("reference_analysis", "参考资料分析"),
    ("outline_planning", "大纲规划"),
    ("chapter_writing", "章节写作"),
    ("chapter_review", "章节审核"),
    ("full_verification", "全文验证"),
    ("result_assembly", "结果装配"),
]


def build_initial_supervisor_plan(payload: TaskCreateRequest) -> SupervisorPlan:
    subtasks: list[SubtaskRecord] = []
    dependencies: list[DependencyEdge] = []

    for index, (kind, title) in enumerate(_STORY_SUBTASK_SPECS):
        subtasks.append(
            SubtaskRecord(
                kind=kind,
                title=title,
                status=SubtaskStatus.READY if index == 0 else SubtaskStatus.BLOCKED,
                payload={"task_mode": payload.mode.value},
            )
        )

    for upstream, downstream in zip(subtasks, subtasks[1:]):
        dependencies.append(
            DependencyEdge(
                upstream_subtask_id=upstream.id,
                downstream_subtask_id=downstream.id,
            )
        )

    return SupervisorPlan(
        planner_version="v1",
        subtasks=subtasks,
        dependencies=dependencies,
        metadata={"task_mode": payload.mode.value},
    )


def _decompose_task(state: SupervisorState) -> SupervisorState:
    payload = TaskCreateRequest.model_validate(state["input_payload"])
    plan = build_initial_supervisor_plan(payload)
    return {"supervisor_plan": plan.model_dump(mode="json")}


def build_supervisor_graph():
    graph = StateGraph(SupervisorState)
    graph.add_node("decompose_task", _decompose_task)
    graph.add_edge(START, "decompose_task")
    graph.add_edge("decompose_task", END)
    return graph.compile()
