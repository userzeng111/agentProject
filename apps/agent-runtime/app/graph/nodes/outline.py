from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.domain.models import AutoReviewPolicy, ReviewDecision, ReviewPayload
from app.llm.auto_reviewer import AutoReviewManager

from app.graph.state import WorkflowState, MAX_OUTLINE_REVISIONS
from app.graph.utils.spec import build_normalized_spec
from app.graph.utils.helpers import (
    _resolve_model_profile,
    _build_references,
    _outline_instruction,
    _normalize_story_plan,
)


def normalize_request(
    state: WorkflowState,
    *,
    auto_review: bool = False,
    auto_review_policy: dict[str, Any] | None = None,
    novel_skill_service: Any | None = None,
    style_profile_service: Any | None = None,
) -> WorkflowState:
    payload = state["input_payload"]
    task_auto_review = bool(state.get("auto_review", auto_review))
    policy = state.get("auto_review_policy") or auto_review_policy or {}
    return {
        "normalized_spec": build_normalized_spec(
            payload,
            novel_skill_service=novel_skill_service,
            style_profile_service=style_profile_service,
        ),
        "batch_index": 0,
        "chapter_pair_revision_count": 0,
        "verification_revision_count": 0,
        "auto_review": task_auto_review,
        "auto_review_policy": policy,
        "auto_review_trace": [],
    }


def prepare_outline_context(
    state: WorkflowState,
    *,
    context_manager: Any,
    model_catalog: Any,
    rag_service: Any | None = None,
) -> WorkflowState:
    references = _build_references(state)
    if rag_service is not None:
        references.extend(
            rag_service.build_reference_materials(
                rag_service.search_for_story_outline(spec=state["normalized_spec"]),
                prefix="大纲RAG",
            )
        )
    snapshot = context_manager.build_snapshot(
        task_id=state["task_id"],
        stage="planning",
        instruction=_outline_instruction(state["normalized_spec"]),
        model_profile=_resolve_model_profile(
            model_catalog,
            state["normalized_spec"].get("model_id"),
        ),
        references=references,
        memory_items=[],
    )
    return {
        "outline_context_packet": snapshot.packet.model_dump(mode="json"),
        "outline_context_snapshot": snapshot.model_dump(mode="json"),
    }


def plan_story(
    state: WorkflowState,
    *,
    engine: Any,
) -> WorkflowState:
    story_plan = engine.build_story_plan(
        state["normalized_spec"],
        state.get("reference_text", ""),
        context_packet=state.get("outline_context_packet"),
        model=state["normalized_spec"].get("model_id"),
    )
    return {
        "story_plan": _normalize_story_plan(story_plan.model_dump()),
        "outline_revision_count": 0,
    }


def review_outline(
    state: WorkflowState,
    *,
    auto_review_executor_available: bool = False,
    execute_auto_review: Any | None = None,
    should_interrupt_manual_review: Any | None = None,
    interrupt_outline_review: Any | None = None,
    build_auto_review_summary: Any | None = None,
) -> WorkflowState:
    # 自动审核模式
    if state.get("auto_review") and auto_review_executor_available:
        policy = AutoReviewPolicy.model_validate(state.get("auto_review_policy") or {})
        force_manual = False
        try:
            story_plan_dict = state.get("story_plan") or {}
            from app.domain.models import StoryPlan as SP
            sp = SP.model_validate(story_plan_dict)
            payload = ReviewPayload(
                type="outline_review",
                summary="请确认大纲是否可以进入正文起草。",
                story_plan=sp,
                risk_flags=[
                    "demo 版本，大纲以稳定展示工作流为优先。",
                    "若上传了参考小说，系统只提炼风味和设定气质，不直接复刻原文。",
                ],
                revision_count=state.get("outline_revision_count", 0),
            )
            # 注入额外上下文
            payload._mode = state.get("normalized_spec", {}).get("mode", "")
            payload._user_prompt = state.get("normalized_spec", {}).get("prompt", "")
            payload._genre = state.get("normalized_spec", {}).get("genre", "")
            payload._style = state.get("normalized_spec", {}).get("style", "")
            payload._requested_target_words = state.get("normalized_spec", {}).get("requested_target_words", "")
            payload._target_words = state.get("normalized_spec", {}).get("target_words", "")

            decision = execute_auto_review(payload, policy)
            agent_items = [a.model_dump() for a in decision.agent_trace]
            prev_trace = list(state.get("auto_review_trace") or [])
            new_entry = [
                build_auto_review_summary(
                    prev_trace=prev_trace,
                    decision=decision,
                    review_type="outline_review",
                    revision_count=state.get("outline_revision_count", 0),
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
            revision_count=state.get("outline_revision_count", 0),
            review_type="outline_review",
        ):
            review = interrupt_outline_review(state)
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
    # 人工审核模式（保持现有逻辑）
    review = interrupt_outline_review(state)
    approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
    comment = review.get("comment", "") if isinstance(review, dict) else ""
    return {"approved": approved, "review_comment": comment}


def revise_outline(
    state: WorkflowState,
    *,
    engine: Any,
) -> WorkflowState:
    revision_count = state.get("outline_revision_count", 0) + 1
    if revision_count >= MAX_OUTLINE_REVISIONS:
        # 超过上限，自动放行
        return {"approved": True, "review_comment": state.get("review_comment", "")}

    story_plan = engine.build_story_plan(
        state["normalized_spec"],
        state.get("reference_text", ""),
        context_packet=state.get("outline_context_packet"),
        model=state["normalized_spec"].get("model_id"),
        revision_comment=state.get("review_comment", ""),
        original_plan=state.get("story_plan"),
    )
    return {
        "story_plan": _normalize_story_plan(story_plan.model_dump()),
        "outline_revision_count": revision_count,
    }


def interrupt_outline_review(state: WorkflowState):
    return interrupt(
        {
            "type": "outline_review",
            "version": "v1",
            "summary": "请确认大纲是否可以进入正文起草。",
            "story_plan": state["story_plan"],
            "risk_flags": [
                "demo 版本，大纲以稳定展示工作流为优先。",
                "若上传了参考小说，系统只提炼风味和设定气质，不直接复刻原文。",
            ],
            "revision_count": state.get("outline_revision_count", 0),
        }
    )
