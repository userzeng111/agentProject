from __future__ import annotations

from app.graph.state import WorkflowState, MAX_OUTLINE_REVISIONS, MAX_CHAPTER_PAIR_REVISIONS


def route_after_outline_review(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"
    if state.get("approved"):
        return "prepare_chapter_pair_context"
    # 达到最大修订次数，强制通过，防止死循环
    if state.get("outline_revision_count", 0) >= MAX_OUTLINE_REVISIONS:
        return "prepare_chapter_pair_context"
    return "revise_outline"


def route_after_revise_outline(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"
    return "review_outline"


def route_after_chapter_pair_review(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"
    if state.get("approved"):
        return "accumulate_chapters"
    # 达到最大修订次数，强制通过，防止死循环
    if state.get("chapter_pair_revision_count", 0) >= MAX_CHAPTER_PAIR_REVISIONS:
        return "accumulate_chapters"
    return "revise_chapter_pair"
