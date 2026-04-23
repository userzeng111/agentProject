from __future__ import annotations

from app.graph.state import WorkflowState, MAX_VERIFICATION_REVISIONS


def route_after_accumulate(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"
    batch_index = state.get("batch_index", 0)
    total_chapters = state.get("total_chapters", 0)
    if batch_index < total_chapters:
        return "prepare_chapter_pair_context"
    return "verify_full_story"


def route_after_verification_review(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"
    if state.get("approved"):
        return "assemble_result"
    # 达到最大修订次数，强制通过，防止死循环
    if state.get("verification_revision_count", 0) >= MAX_VERIFICATION_REVISIONS:
        return "assemble_result"
    return "fix_verified_issues"


def route_after_fix_issues(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"
    return "review_verification"
