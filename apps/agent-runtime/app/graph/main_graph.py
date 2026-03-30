from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.llm.story_engine import StoryEngine

try:
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:  # pragma: no cover
    from langgraph.checkpoint.memory import InMemorySaver as MemorySaver


class WorkflowState(TypedDict, total=False):
    task_id: str
    input_payload: dict[str, Any]
    reference_text: str
    normalized_spec: dict[str, Any]
    story_plan: dict[str, Any]
    approved: bool
    review_comment: str
    draft_result: dict[str, Any]
    cancelled: bool


def build_graph(engine: StoryEngine):
    def normalize_request(state: WorkflowState) -> WorkflowState:
        payload = state["input_payload"]
        return {
            "normalized_spec": {
                "mode": payload["mode"],
                "prompt": payload["prompt"].strip(),
                "genre": payload.get("genre", "").strip(),
                "style": payload.get("style", "").strip(),
                "target_words": payload.get("target_words", 1800),
                "audience": payload.get("audience", "").strip(),
                "banned": payload.get("banned", "").strip(),
                "title_hint": payload.get("title_hint", "").strip(),
            }
        }

    def plan_story(state: WorkflowState) -> WorkflowState:
        story_plan = engine.build_story_plan(
            state["normalized_spec"], state.get("reference_text", "")
        )
        return {"story_plan": story_plan.model_dump()}

    def review_outline(state: WorkflowState) -> WorkflowState:
        review = interrupt(
            {
                "type": "outline_review",
                "version": "v1",
                "summary": "请确认大纲是否可以进入正文起草。",
                "story_plan": state["story_plan"],
                "risk_flags": [
                    "这是 demo 版本，大纲以稳定展示工作流为优先。",
                    "若上传了参考小说，系统只提炼风味和设定气质，不直接复刻原文。",
                ],
            }
        )
        approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
        comment = review.get("comment", "") if isinstance(review, dict) else ""
        return {"approved": approved, "review_comment": comment}

    def draft_story(state: WorkflowState) -> WorkflowState:
        draft_result = engine.generate_draft(
            state["normalized_spec"],
            state["story_plan"],
            state.get("reference_text", ""),
        )
        return {"draft_result": draft_result.model_dump(), "cancelled": False}

    def cancel_task(state: WorkflowState) -> WorkflowState:
        return {"cancelled": True}

    def route_after_review(state: WorkflowState) -> str:
        return "draft_story" if state.get("approved") else "cancel_task"

    graph = StateGraph(WorkflowState)
    graph.add_node("normalize_request", normalize_request)
    graph.add_node("plan_story", plan_story)
    graph.add_node("review_outline", review_outline)
    graph.add_node("draft_story", draft_story)
    graph.add_node("cancel_task", cancel_task)

    graph.add_edge(START, "normalize_request")
    graph.add_edge("normalize_request", "plan_story")
    graph.add_edge("plan_story", "review_outline")
    graph.add_conditional_edges(
        "review_outline",
        route_after_review,
        {"draft_story": "draft_story", "cancel_task": "cancel_task"},
    )
    graph.add_edge("draft_story", END)
    graph.add_edge("cancel_task", END)

    return graph.compile(checkpointer=MemorySaver())
