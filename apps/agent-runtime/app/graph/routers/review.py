from __future__ import annotations

from app.graph.state import WorkflowState, MAX_OUTLINE_REVISIONS, MAX_CHAPTER_PAIR_REVISIONS

MAX_BATCH_RETRIES = 3


def route_after_outline_review(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"

    phase = state.get("outline_phase", "master")

    if state.get("approved"):
        if phase == "master":
            return "plan_chapter_batch"
        # chapter_batches 阶段：判断是否全部完成
        completed_count = int(state.get("outline_completed_count", 0) or 0)
        total = int(state.get("outline_total_count", 0) or 0)
        if total > 0 and completed_count >= total:
            return "prepare_chapter_pair_context"
        return "plan_chapter_batch"

    # 驳回分支
    if phase == "chapter_batches":
        retry = state.get("outline_batch_retry_count", 0)
        if retry >= MAX_BATCH_RETRIES:
            # 重试超限，退回总纲修订
            return "revise_outline"
        return "plan_chapter_batch"

    # master 阶段原有逻辑
    if state.get("outline_revision_count", 0) >= MAX_OUTLINE_REVISIONS:
        return "prepare_chapter_pair_context"
    return "revise_outline"


def route_after_revise_outline(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"
    return "review_outline"


def route_after_chapter_gate_review(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"
    decision = str(state.get("chapter_gate_decision") or "").strip().lower()
    if decision == "accumulate":
        return "accumulate_chapters"
    return "review_chapter_pair"


def route_after_chapter_pair_review(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "cancel_task"
    if state.get("approved"):
        return "accumulate_chapters"
    # 达到最大修订次数，强制通过，防止死循环
    if state.get("chapter_pair_revision_count", 0) >= MAX_CHAPTER_PAIR_REVISIONS:
        return "accumulate_chapters"
    return "revise_chapter_pair"
