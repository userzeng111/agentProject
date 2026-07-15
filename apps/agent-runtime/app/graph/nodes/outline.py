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
from app.llm.story_engine import get_progress_callback
from app.observability import get_logger

logger = get_logger(__name__)


def _outline_review_unit_id(state: WorkflowState) -> str:
    return "outline-chapter-batches" if state.get("outline_phase") == "chapter_batches" else "outline"


def _emit_outline_review_progress(
    state: WorkflowState,
    *,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    callback = get_progress_callback()
    if callback is None:
        return
    callback(
        {
            "event_type": event_type,
            # 自动审核仍在工作流执行中，不能伪装成可由用户提交的人工审核态。
            "stage": "planning",
            "unit_id": _outline_review_unit_id(state),
            "message": message,
            "payload": {
                "summary": message,
                "display_level": "public",
                "workflow_step": "outline_auto_review",
                "outline_phase": state.get("outline_phase", "master"),
                **(payload or {}),
            },
        }
    )


def _finalize_chapter_plan_batch_review(
    state: WorkflowState,
    decision: ReviewDecision,
) -> dict[str, Any]:
    if state.get("outline_phase") != "chapter_batches":
        return {}

    story_plan = state.get("story_plan") or {}
    batch_index = int(state.get("outline_batch_index", 0) or 0)
    batch_size = int(state.get("outline_batch_size", 20) or 20)
    total = int(
        state.get("outline_total_count")
        or story_plan.get("planned_chapter_count")
        or len(story_plan.get("chapter_plan") or [])
        or 0
    )
    current_batch = state.get("current_batch_chapter_plans") or []
    effective_count = len(current_batch)
    batch_no = (batch_index // batch_size) + 1

    try:
        from app.storage import db_repository

        if decision.approved:
            db_repository.mark_chapter_plan_batch_approved(state["task_id"], batch_no)
        else:
            db_repository.mark_chapter_plan_batch_rejected(state["task_id"], batch_no)
    except Exception as exc:
        logger.warning("章节计划批次审核结果写入失败（不阻断主流程）: %s", exc)

    if not decision.approved:
        return {}

    if total <= 0 or effective_count <= 0:
        raise ValueError("章节计划批次为空，不能进入正文生成。")

    expected_numbers = list(range(batch_index + 1, batch_index + effective_count + 1))
    actual_numbers = [int(item.get("number") or 0) for item in current_batch if isinstance(item, dict)]
    if actual_numbers != expected_numbers:
        raise ValueError("章节计划批次编号不连续，不能进入正文生成。")

    merged_story_plan = dict(story_plan)
    existing_plans = {
        int(item.get("number") or 0): item
        for item in (merged_story_plan.get("chapter_plan") or [])
        if isinstance(item, dict) and int(item.get("number") or 0) > 0
    }
    for item in current_batch:
        if isinstance(item, dict):
            existing_plans[int(item["number"])] = dict(item)
    merged_story_plan["chapter_plan"] = [existing_plans[number] for number in sorted(existing_plans)]
    merged_story_plan["planned_chapter_count"] = max(
        int(merged_story_plan.get("planned_chapter_count") or 0),
        total,
        len(merged_story_plan["chapter_plan"]),
    )

    completed_count = min(total, batch_index + effective_count)
    return {
        "story_plan": merged_story_plan,
        "outline_completed_count": completed_count,
        "outline_batch_retry_count": 0,
    }


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
    planned_count = int(plan_dict.get("planned_chapter_count") or 0)
    if planned_count <= 0:
        retry_plan = engine.build_story_plan(
            state["normalized_spec"],
            state.get("reference_text", ""),
            context_packet=state.get("outline_context_packet"),
            model=state["normalized_spec"].get("model_id"),
            revision_comment=(
                "上一版大纲缺少有效 planned_chapter_count。"
                "请明确给出正整数的 planned_chapter_count，并保留所有既有世界观与人物设定。"
            ),
            original_plan=plan_dict,
        )
        plan_dict = _normalize_story_plan(retry_plan.model_dump())
        planned_count = int(plan_dict.get("planned_chapter_count") or 0)
    if planned_count <= 0:
        raise ValueError(
            f"大纲缺少有效章节总数：当前 {planned_count} 章。"
        )
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
    callback = get_progress_callback()
    if callback is not None:
        callback(
            {
                "event_type": "outline.chapter_plan_batch.started",
                "stage": "planning",
                "unit_id": "outline-chapter-batches",
                "message": f"开始规划第 {batch_no} 批章节计划。",
                "payload": {
                    "summary": f"开始规划第 {batch_no} 批章节计划。",
                    "display_level": "public",
                    "workflow_step": "chapter_plan_batch",
                    "outline_phase": "chapter_batches",
                    "batch_no": batch_no,
                    "start_chapter": batch_index + 1,
                    "end_chapter": batch_index + effective_size,
                },
            }
        )
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

    if callback is not None:
        callback(
            {
                "event_type": "outline.chapter_plan_batch.completed",
                "stage": "planning",
                "unit_id": "outline-chapter-batches",
                "message": f"第 {batch_no} 批章节计划已生成，等待审核。",
                "payload": {
                    "summary": f"第 {batch_no} 批章节计划已生成，等待审核。",
                    "display_level": "public",
                    "workflow_step": "chapter_plan_batch",
                    "outline_phase": "chapter_batches",
                    "batch_no": batch_no,
                    "start_chapter": batch_index + 1,
                    "end_chapter": batch_index + effective_size,
                    "effective_count": effective_size,
                },
            }
        )

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
        _emit_outline_review_progress(
            state,
            event_type="outline.review.started",
            message=(
                "自动审核开始：正在审核章节计划批次。"
                if state.get("outline_phase") == "chapter_batches"
                else "自动审核开始：正在审核总纲。"
            ),
        )
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
        _emit_outline_review_progress(
            state,
            event_type="outline.review.completed",
            message=(
                f"自动审核完成：{'通过' if decision.approved else '未通过'}，评分 {decision.overall_score or 0:.1f}。"
            ),
            payload={
                "approved": decision.approved,
                "score": decision.overall_score,
                "auto_escalated": decision.auto_escalated,
                "critical_issue_count": len(decision.critical_issues or []),
                "warning_count": len(decision.warnings or []),
            },
        )
        # auto_review 达到修订上限时自动强制通过，避免中断到人工审核
        if not decision.approved and policy.allow_self_revisions and not force_manual:
            max_revisions = max(policy.get_max_auto_revisions("outline_review"), 0)
            if state.get("outline_revision_count", 0) >= max_revisions:
                logger.warning(
                    "大纲审核节点: auto_review 达到修订上限 %d，自动强制通过",
                    max_revisions,
                )
                batch_updates = _finalize_chapter_plan_batch_review(
                    state,
                    decision.model_copy(update={"approved": True}),
                )
                return {
                    "approved": True,
                    "review_comment": decision.comment or "自动审核达到修订上限，强制通过。",
                    "auto_review_trace": trace,
                    **batch_updates,
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
            batch_updates = _finalize_chapter_plan_batch_review(
                state,
                decision.model_copy(update={"approved": approved}),
            )
            return {
                "approved": approved,
                "review_comment": comment,
                "auto_review_trace": trace,
                **batch_updates,
            }
        batch_updates = _finalize_chapter_plan_batch_review(state, decision)
        return {
            "approved": decision.approved,
            "review_comment": decision.comment,
            "auto_review_trace": trace,
            **batch_updates,
        }
    # 人工审核模式（保持现有逻辑）
    review = interrupt_outline_review(state)
    approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
    comment = review.get("comment", "") if isinstance(review, dict) else ""
    batch_updates = _finalize_chapter_plan_batch_review(
        state,
        ReviewDecision(approved=approved, comment=comment, reasoning="人工审核结果"),
    )
    return {"approved": approved, "review_comment": comment, **batch_updates}


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
