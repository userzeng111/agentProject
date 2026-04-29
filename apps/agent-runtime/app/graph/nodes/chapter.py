from __future__ import annotations

from typing import Any

from app.domain.models import AutoReviewPolicy, ReviewDecision, ReviewPayload
from app.observability import get_logger
from app.graph.state import WorkflowState, MAX_CHAPTER_PAIR_REVISIONS

logger = get_logger(__name__)
from app.graph.utils.spec import _chapter_batch_size
from app.graph.utils.helpers import (
    _resolve_model_profile,
    _build_references,
    _chapter_pair_instruction,
    _planned_chapter_count,
    _normalize_story_plan,
    _chapter_pair_memory_items,
)


def prepare_chapter_pair_context(
    state: WorkflowState,
    *,
    context_manager: Any,
    model_catalog: Any,
    rag_service: Any | None = None,
) -> WorkflowState:
    batch_index = state.get("batch_index", 0)
    story_plan = _normalize_story_plan(state.get("story_plan") or {})
    total_chapters = _planned_chapter_count(story_plan)
    completed = state.get("completed_chapters") or []
    completed_count = len(completed)
    batch_size = _chapter_batch_size(
        state["normalized_spec"],
        completed_count=completed_count,
        total_chapters=total_chapters,
    )
    references = _build_references(state)
    if rag_service is not None:
        try:
            chapter_result = rag_service.search_for_story_chapter(
                spec=state["normalized_spec"],
                story_plan=state.get("story_plan"),
                batch_index=batch_index,
                batch_size=batch_size,
                completed_chapters=completed,
            )
        except TypeError:
            chapter_result = rag_service.search_for_story_chapter(
                spec=state["normalized_spec"],
                story_plan=state.get("story_plan"),
                batch_index=batch_index,
                completed_chapters=completed,
            )
        references.extend(
            rag_service.build_reference_materials(
                chapter_result,
                prefix="章节RAG",
            )
        )

    snapshot = context_manager.build_snapshot(
        task_id=state["task_id"],
        stage="drafting",
        instruction=_chapter_pair_instruction(state["normalized_spec"], state.get("story_plan")),
        model_profile=_resolve_model_profile(
            model_catalog,
            state["normalized_spec"].get("model_id"),
        ),
        references=references,
        memory_items=_chapter_pair_memory_items(state),
    )
    return {
        "story_plan": story_plan,
        "chapter_pair_context_packet": snapshot.packet.model_dump(mode="json"),
        "total_chapters": total_chapters,
        "completed_count": completed_count,
        "batch_index": batch_index,
        "current_batch_size": batch_size,
    }


def draft_chapter_pair(
    state: WorkflowState,
    *,
    engine: Any,
) -> WorkflowState:
    batch_index = state.get("batch_index", 0)
    completed_chapters = state.get("completed_chapters") or []
    chapter_pair = engine.generate_chapter_pair(
        state["normalized_spec"],
        state.get("story_plan") or {},
        batch_index,
        completed_chapters,
        state.get("reference_text", ""),
        context_packet=state.get("chapter_pair_context_packet"),
        model=state["normalized_spec"].get("model_id"),
        progress_callback=getattr(engine, "progress_callback", None),
    )
    return {
        "current_chapter_pair": [ch.model_dump() for ch in chapter_pair],
        "chapter_pair_revision_count": 0,
    }


def review_chapter_pair(
    state: WorkflowState,
    *,
    auto_review_executor_available: bool = False,
    execute_auto_review: Any | None = None,
    should_interrupt_manual_review: Any | None = None,
    interrupt_chapter_pair_review: Any | None = None,
    build_auto_review_summary: Any | None = None,
) -> WorkflowState:
    # 自动审核模式
    if state.get("auto_review") and auto_review_executor_available:
        logger.info("章节审核节点: auto_review=%s, executor_available=%s", state.get("auto_review"), auto_review_executor_available)
        policy = AutoReviewPolicy.model_validate(state.get("auto_review_policy") or {})
        force_manual = False
        try:
            story_plan_dict = state.get("story_plan")
            sp = None
            if story_plan_dict:
                from app.domain.models import StoryPlan as SP
                sp = SP.model_validate(story_plan_dict)
            chapters = state.get("current_chapter_pair") or []
            payload = ReviewPayload(
                type="chapter_pair_review",
                summary="请审核本批章节是否符合大纲要求。",
                story_plan=sp,
                batch_index=state.get("batch_index", 0),
                chapter_pair=chapters,
                completed_count=state.get("completed_count", 0),
                total_chapters=state.get("total_chapters", 0),
                chapter_pair_revision_count=state.get("chapter_pair_revision_count", 0),
            )
            payload._user_prompt = state.get("normalized_spec", {}).get("prompt", "")
            payload._completed_summaries = [
                f"{ch.get('title', '')}:{ch.get('summary', '')}"
                for ch in (state.get("completed_chapters") or [])
            ]
            decision = execute_auto_review(payload, policy)
            agent_items = [a.model_dump() for a in decision.agent_trace]
            prev_trace = list(state.get("auto_review_trace") or [])
            new_entry = [
                build_auto_review_summary(
                    prev_trace=prev_trace,
                    decision=decision,
                    review_type="chapter_pair_review",
                    revision_count=state.get("chapter_pair_revision_count", 0),
                    batch_index=state.get("batch_index", 0),
                ),
                *agent_items,
            ]
            trace = prev_trace + new_entry
        except Exception as e:
            logger.error("章节审核节点: auto_review 异常: %s", e, exc_info=True)
            decision = ReviewDecision(
                approved=False,
                comment=f"自动审核异常: {e}，请人工介入。",
                reasoning=str(e),
                auto_escalated=True,
                overall_score=0.0,
            )
            trace = list(state.get("auto_review_trace") or [])
            force_manual = True
        # auto_review 达到修订上限时自动强制通过，避免中断到人工审核
        if not decision.approved and policy.allow_self_revisions and not force_manual:
            max_revisions = max(policy.get_max_auto_revisions("chapter_pair_review"), 0)
            if state.get("chapter_pair_revision_count", 0) >= max_revisions:
                logger.warning(
                    "章节审核节点: auto_review 达到修订上限 %d，自动强制通过",
                    max_revisions,
                )
                return {
                    "approved": True,
                    "review_comment": decision.comment or "自动审核达到修订上限，强制通过。",
                    "auto_review_trace": trace,
                }
        if force_manual or should_interrupt_manual_review(
            approved=decision.approved,
            policy=policy,
            revision_count=state.get("chapter_pair_revision_count", 0),
            review_type="chapter_pair_review",
        ):
            review = interrupt_chapter_pair_review(state, comment=decision.comment if force_manual else "")
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
    review = interrupt_chapter_pair_review(state)
    approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
    comment = review.get("comment", "") if isinstance(review, dict) else ""
    return {"approved": approved, "review_comment": comment}


def revise_chapter_pair(
    state: WorkflowState,
    *,
    engine: Any,
) -> WorkflowState:
    revision_count = state.get("chapter_pair_revision_count", 0) + 1
    if revision_count >= MAX_CHAPTER_PAIR_REVISIONS:
        return {"approved": True, "review_comment": state.get("review_comment", "")}

    revised_pair = engine.revise_chapter_pair(
        current_pair=state.get("current_chapter_pair") or [],
        revision_comment=state.get("review_comment", ""),
        spec=state["normalized_spec"],
        story_plan=state.get("story_plan") or {},
        completed_chapters=state.get("completed_chapters") or [],
        reference_text=state.get("reference_text", ""),
        context_packet=state.get("chapter_pair_context_packet"),
        model=state["normalized_spec"].get("model_id"),
    )
    return {
        "current_chapter_pair": [ch.model_dump() for ch in revised_pair],
        "chapter_pair_revision_count": revision_count,
    }


def accumulate_chapters(state: WorkflowState) -> WorkflowState:
    current_pair = state.get("current_chapter_pair") or []
    completed_chapters = list(state.get("completed_chapters") or [])
    completed_chapters.extend(current_pair)
    total_chapters = _planned_chapter_count(state.get("story_plan") or {})
    batch_index = state.get("batch_index", 0) + len(current_pair)
    # 安全推进：如果 current_pair 为空则 batch_index 不增加，避免无限循环
    if batch_index >= total_chapters:
        batch_index = total_chapters
    return {
        "completed_chapters": completed_chapters,
        "batch_index": batch_index,
    }


def interrupt_chapter_pair_review(state: WorkflowState, comment: str = ""):
    from langgraph.types import interrupt
    return interrupt(
        {
            "type": "chapter_pair_review",
            "version": "v1",
            "summary": comment or "请审核本批章节是否符合大纲要求。",
            "story_plan": state.get("story_plan"),
            "batch_index": state.get("batch_index", 0),
            "chapter_pair": state.get("current_chapter_pair", []),
            "completed_count": state.get("completed_count", 0),
            "total_chapters": state.get("total_chapters", 0),
            "chapter_pair_revision_count": state.get("chapter_pair_revision_count", 0),
        }
    )
