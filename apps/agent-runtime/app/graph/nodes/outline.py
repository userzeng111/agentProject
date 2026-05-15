from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.domain.models import AutoReviewPolicy, ReviewDecision, ReviewPayload
from app.graph.state import WorkflowState, MAX_OUTLINE_REVISIONS
from app.graph.utils.helpers import (
    _resolve_model_profile,
    _build_references,
    _outline_instruction,
    _normalize_story_plan,
)
from app.graph.utils.spec import build_normalized_spec
from app.observability import get_logger

logger = get_logger(__name__)


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
    generate_chapter_plan: bool = True,
) -> WorkflowState:
    story_plan = engine.build_story_plan(
        state["normalized_spec"],
        state.get("reference_text", ""),
        context_packet=state.get("outline_context_packet"),
        model=state["normalized_spec"].get("model_id"),
    )
    plan_dict = _normalize_story_plan(story_plan.model_dump())
    if not generate_chapter_plan:
        plan_dict["chapter_plan"] = []
    return {
        "story_plan": plan_dict,
        "outline_revision_count": 0,
        "outline_phase": "master",
        "outline_total_count": plan_dict.get("planned_chapter_count", 0),
        "outline_batch_index": 0,
        "outline_batch_size": 20,
        "outline_completed_count": 0,
        "outline_batch_retry_count": 0,
    }


def plan_chapter_batch(
    state: WorkflowState,
    *,
    engine: Any,
    default_batch_size: int = 20,
) -> WorkflowState:
    story_plan_dict = state.get("story_plan") or {}
    # 使用已确认章节数作为下一批起始位置（兼容纯图执行无 checkpoint 同步场景）
    batch_index = state.get("outline_completed_count", 0)
    batch_size = state.get("outline_batch_size", default_batch_size)
    total = story_plan_dict.get("planned_chapter_count", 0)

    effective_size = min(batch_size, max(total - batch_index, 0))
    if effective_size <= 0:
        return {
            "current_batch_chapter_plans": [],
            "outline_phase": "chapter_batches",
        }

    existing_chapter_plan = story_plan_dict.get("chapter_plan", [])
    # 若总纲已携带完整 chapter_plan，直接切片避免重复调用 LLM
    if existing_chapter_plan and len(existing_chapter_plan) >= batch_index + effective_size:
        from app.domain.models import ChapterPlan
        batch_plans = [
            ChapterPlan.model_validate(ch)
            for ch in existing_chapter_plan[batch_index : batch_index + effective_size]
        ]
    else:
        batch_plans = engine.build_chapter_plan_batch(
            spec=state["normalized_spec"],
            story_plan=story_plan_dict,
            batch_index=batch_index,
            batch_size=effective_size,
            confirmed_chapter_plans=existing_chapter_plan[:batch_index],
            model=state["normalized_spec"].get("model_id"),
        )

    from app.storage import db_repository
    batch_no = (batch_index // batch_size) + 1
    try:
        db_repository.create_chapter_plan_batch(
            task_id=state["task_id"],
            batch_no=batch_no,
            start_chapter=batch_index + 1,
            end_chapter=batch_index + effective_size,
            requested_count=batch_size,
            effective_count=effective_size,
            status="waiting_review",
        )
        for plan in batch_plans:
            db_repository.upsert_outline_chapter_plan(
                task_id=state["task_id"],
                chapter_number=plan.number,
                title=plan.title,
                goal=plan.goal,
                outline_batch_no=batch_no,
                status="outline_planned",
            )
    except Exception as e:
        logger.warning("章节计划批次数据库写入失败（测试环境可忽略）: %s", e)

    return {
        "current_batch_chapter_plans": [p.model_dump(mode="json") for p in batch_plans],
        "outline_phase": "chapter_batches",
        "outline_batch_index": batch_index,
        "outline_batch_retry_count": state.get("outline_batch_retry_count", 0) + 1,
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
        logger.info("大纲审核节点: auto_review=%s, executor_available=%s", state.get("auto_review"), auto_review_executor_available)
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
            logger.error("大纲审核节点: auto_review 异常: %s", e, exc_info=True)
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
            max_revisions = max(policy.get_max_auto_revisions("outline_review"), 0)
            if state.get("outline_revision_count", 0) >= max_revisions:
                logger.warning(
                    "大纲审核节点: auto_review 达到修订上限 %d，自动强制通过",
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
            revision_count=state.get("outline_revision_count", 0),
            review_type="outline_review",
        ):
            review = interrupt_outline_review(state, comment=decision.comment if force_manual else "")
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


def interrupt_outline_review(state: WorkflowState, comment: str = ""):
    phase = state.get("outline_phase", "master")
    story_plan = state.get("story_plan") or {}

    outline_batch = {
        "phase": phase,
        "completed_count": state.get("outline_completed_count", 0),
        "total_count": story_plan.get("planned_chapter_count", 0),
        "batch_index": state.get("outline_batch_index", 0),
        "batch_size": state.get("outline_batch_size", 20),
    }
    if phase == "chapter_batches":
        outline_batch["current_batch_plans"] = state.get("current_batch_chapter_plans", [])

    return interrupt(
        {
            "type": "outline_review",
            "version": "v1",
            "summary": comment or "请确认大纲内容。",
            "story_plan": story_plan,
            "risk_flags": [
                "demo 版本，大纲以稳定展示工作流为优先。",
                "若上传了参考小说，系统只提炼风味和设定气质，不直接复刻原文。",
            ],
            "revision_count": state.get("outline_revision_count", 0),
            "outline_batch": outline_batch,
        }
    )
