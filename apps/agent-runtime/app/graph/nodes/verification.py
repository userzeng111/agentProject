from __future__ import annotations

from typing import Any

from app.domain.models import AutoReviewPolicy, ReviewDecision, ReviewPayload
from app.graph.state import WorkflowState, MAX_VERIFICATION_REVISIONS


def verify_full_story(
    state: WorkflowState,
    *,
    engine: Any,
) -> WorkflowState:
    report = engine.verify_full_story(
        completed_chapters=state.get("completed_chapters") or [],
        story_plan=state.get("story_plan") or {},
        spec=state["normalized_spec"],
        reference_text=state.get("reference_text", ""),
        context_packet=None,
        model=state["normalized_spec"].get("model_id"),
    )
    return {"verification_report": report}


def review_verification(
    state: WorkflowState,
    *,
    auto_review_executor_available: bool = False,
    execute_auto_review: Any | None = None,
    should_interrupt_manual_review: Any | None = None,
    interrupt_verification_review: Any | None = None,
    build_auto_review_summary: Any | None = None,
) -> WorkflowState:
    # 自动审核模式
    if state.get("auto_review") and auto_review_executor_available:
        policy = AutoReviewPolicy.model_validate(state.get("auto_review_policy") or {})
        force_manual = False
        try:
            story_plan_dict = state.get("story_plan")
            sp = None
            if story_plan_dict:
                from app.domain.models import StoryPlan as SP
                sp = SP.model_validate(story_plan_dict)
            payload = ReviewPayload(
                type="verification_review",
                summary="请审核全文一致性验证报告。",
                story_plan=sp,
                verification_report=state.get("verification_report", {}),
                verification_revision_count=state.get("verification_revision_count", 0),
            )
            decision = execute_auto_review(payload, policy)
            agent_items = [a.model_dump() for a in decision.agent_trace]
            prev_trace = list(state.get("auto_review_trace") or [])
            new_entry = [
                build_auto_review_summary(
                    prev_trace=prev_trace,
                    decision=decision,
                    review_type="verification_review",
                    revision_count=state.get("verification_revision_count", 0),
                ),
                *agent_items,
            ]
            trace = prev_trace + new_entry
        except Exception as e:
            decision = ReviewDecision(
                approved=False,
                comment=f"自动审核异常: {e}，请人工介入。",
                reasoning=str(e),
                auto_escalated=True,
                overall_score=0.0,
            )
            trace = list(state.get("auto_review_trace") or [])
            force_manual = True
        if force_manual or should_interrupt_manual_review(
            approved=decision.approved,
            policy=policy,
            revision_count=state.get("verification_revision_count", 0),
            review_type="verification_review",
        ):
            review = interrupt_verification_review(state)
            approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
            comment = review.get("comment", "") if isinstance(review, dict) else ""
            return {
                "approved": approved,
                "review_comment": comment,
                "auto_review_trace": trace,
            }
        return {
            "approved": decision.approved,
            "review_comment": decision.comment,
            "auto_review_trace": trace,
        }
    # 人工审核模式
    review = interrupt_verification_review(state)
    approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
    comment = review.get("comment", "") if isinstance(review, dict) else ""
    return {"approved": approved, "review_comment": comment}


def fix_verified_issues(
    state: WorkflowState,
    *,
    engine: Any,
) -> WorkflowState:
    revision_count = state.get("verification_revision_count", 0) + 1
    if revision_count >= MAX_VERIFICATION_REVISIONS:
        return {"approved": True, "review_comment": state.get("review_comment", "")}

    fixed = engine.fix_verified_issues(
        completed_chapters=state.get("completed_chapters") or [],
        verification_report=state.get("verification_report") or {},
        review_comment=state.get("review_comment", ""),
        story_plan=state.get("story_plan") or {},
        spec=state["normalized_spec"],
        reference_text=state.get("reference_text", ""),
        context_packet=None,
        model=state["normalized_spec"].get("model_id"),
    )
    return {
        "completed_chapters": fixed,
        "verification_revision_count": revision_count,
    }


def interrupt_verification_review(state: WorkflowState):
    from langgraph.types import interrupt
    return interrupt(
        {
            "type": "verification_review",
            "version": "v1",
            "summary": "请审核全文一致性验证报告。",
            "story_plan": state.get("story_plan"),
            "verification_report": state.get("verification_report", {}),
            "verification_revision_count": state.get("verification_revision_count", 0),
        }
    )
