from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.context.manager import ContextManager
from app.context.models import ModelContextProfile, ReferenceMaterial
from app.domain.models import AutoReviewPolicy, ReviewDecision, ReviewMode, ReviewPayload
from app.llm.auto_reviewer import AutoReviewManager
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    _HAS_SQLITE = True
except ImportError:
    _HAS_SQLITE = False

try:
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:  # pragma: no cover
    from langgraph.checkpoint.memory import InMemorySaver as MemorySaver


def _create_checkpointer(db_path: str | Path | None = None):
    """创建 checkpointer：优先 SQLite 持久化，回退到内存。"""
    if _HAS_SQLITE and db_path:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = __import__("sqlite3").connect(str(db_path), check_same_thread=False)
        return SqliteSaver(conn)
    return MemorySaver()


class WorkflowState(TypedDict, total=False):
    task_id: str
    input_payload: dict[str, Any]
    reference_text: str
    source_assets: list[dict[str, Any]]
    normalized_spec: dict[str, Any]
    outline_context_packet: dict[str, Any]
    outline_context_snapshot: dict[str, Any]
    story_plan: dict[str, Any]
    outline_revision_count: int
    # 章节对
    batch_index: int
    total_chapters: int
    completed_count: int
    chapter_pair_context_packet: dict[str, Any]
    current_chapter_pair: list[dict[str, Any]]
    completed_chapters: list[dict[str, Any]]
    chapter_pair_revision_count: int
    # 验证
    verification_report: dict[str, Any]
    verification_revision_count: int
    # 打断回复
    review_type: str
    review_comment: str
    approved: bool
    cancelled: bool
    # 最终结果
    draft_result: dict[str, Any]
    # 自动审核 [NEW]
    auto_review: bool
    auto_review_policy: dict[str, Any]
    auto_review_trace: list[dict[str, Any]]


MAX_OUTLINE_REVISIONS = 5
MAX_CHAPTER_PAIR_REVISIONS = 5
MAX_VERIFICATION_REVISIONS = 3


def build_graph(
    engine: StoryEngine,
    context_manager: ContextManager | None = None,
    model_catalog: ModelCatalogService | None = None,
    history_loader: Callable[[str, str, str], list[dict[str, str]]] | None = None,
    checkpoint_db_path: str | Path | None = None,
    auto_review: bool = False,
    auto_review_policy: dict[str, Any] | None = None,
):
    active_context_manager = context_manager or ContextManager()
    active_model_catalog = model_catalog
    active_history_loader = history_loader
    # 自动审核编排器
    auto_review_manager: AutoReviewManager | None = AutoReviewManager(
        gateway_client=getattr(engine, "gateway_client", None),
    )

    def _should_interrupt_manual_review(
        *,
        approved: bool,
        policy: AutoReviewPolicy,
        revision_count: int,
        review_type: str,
    ) -> bool:
        if approved:
            return False
        if not policy.allow_self_revisions:
            return True
        return revision_count >= max(policy.get_max_auto_revisions(review_type), 0)

    def _interrupt_outline_review(state: WorkflowState):
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

    def _interrupt_chapter_pair_review(state: WorkflowState):
        return interrupt(
            {
                "type": "chapter_pair_review",
                "version": "v1",
                "summary": "请审核这对章节是否符合大纲要求。",
                "story_plan": state.get("story_plan"),
                "batch_index": state.get("batch_index", 0),
                "chapter_pair": state.get("current_chapter_pair", []),
                "completed_count": state.get("completed_count", 0),
                "total_chapters": state.get("total_chapters", 0),
                "chapter_pair_revision_count": state.get("chapter_pair_revision_count", 0),
            }
        )

    def _interrupt_verification_review(state: WorkflowState):
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

    # ─────────────────────────────────────────────
    # 节点定义
    # ─────────────────────────────────────────────

    def normalize_request(state: WorkflowState) -> WorkflowState:
        payload = state["input_payload"]
        task_auto_review = bool(state.get("auto_review", auto_review))
        policy = state.get("auto_review_policy") or auto_review_policy or {}
        requested_target_words = int(payload.get("target_words", 1800) or 1800)
        return {
            "normalized_spec": {
                "mode": payload["mode"],
                "prompt": payload["prompt"].strip(),
                "genre": payload.get("genre", "").strip(),
                "style": payload.get("style", "").strip(),
                "requested_target_words": requested_target_words,
                "target_words": _normalize_target_words(payload["mode"], requested_target_words),
                "audience": payload.get("audience", "").strip(),
                "banned": payload.get("banned", "").strip(),
                "title_hint": payload.get("title_hint", "").strip(),
                "model_id": payload.get("model_id", payload.get("model", "")).strip(),
            },
            "batch_index": 0,
            "chapter_pair_revision_count": 0,
            "verification_revision_count": 0,
            "auto_review": task_auto_review,
            "auto_review_policy": policy,
            "auto_review_trace": [],
        }

    def prepare_outline_context(state: WorkflowState) -> WorkflowState:
        snapshot = active_context_manager.build_snapshot(
            task_id=state["task_id"],
            stage="planning",
            instruction=_outline_instruction(state["normalized_spec"]),
            model_profile=_resolve_model_profile(
                active_model_catalog,
                state["normalized_spec"].get("model_id"),
            ),
            references=_build_references(state),
            memory_items=[],
        )
        return {
            "outline_context_packet": snapshot.packet.model_dump(mode="json"),
            "outline_context_snapshot": snapshot.model_dump(mode="json"),
        }

    def plan_story(state: WorkflowState) -> WorkflowState:
        story_plan = engine.build_story_plan(
            state["normalized_spec"],
            state.get("reference_text", ""),
            context_packet=state.get("outline_context_packet"),
            model=state["normalized_spec"].get("model_id"),
        )
        return {
            "story_plan": story_plan.model_dump(),
            "outline_revision_count": 0,
        }

    def review_outline(state: WorkflowState) -> WorkflowState:
        # 自动审核模式
        if state.get("auto_review") and auto_review_manager is not None:
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

                decision = auto_review_manager.review(payload, policy)
                trace = [a.model_dump() for a in decision.agent_trace]
            except Exception as e:
                decision = ReviewDecision(
                    approved=False,
                    comment=f"自动审核异常: {e}，请人工介入。",
                    reasoning=str(e),
                    auto_escalated=True,
                    overall_score=0.0,
                )
                trace = []
                force_manual = True
            if force_manual or _should_interrupt_manual_review(
                approved=decision.approved,
                policy=policy,
                revision_count=state.get("outline_revision_count", 0),
                review_type="outline_review",
            ):
                review = _interrupt_outline_review(state)
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
        review = _interrupt_outline_review(state)
        approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
        comment = review.get("comment", "") if isinstance(review, dict) else ""
        return {"approved": approved, "review_comment": comment}

    def revise_outline(state: WorkflowState) -> WorkflowState:
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
            "story_plan": story_plan.model_dump(),
            "outline_revision_count": revision_count,
        }

    def prepare_chapter_pair_context(state: WorkflowState) -> WorkflowState:
        batch_index = state.get("batch_index", 0)
        story_plan = state.get("story_plan") or {}
        chapter_plan = story_plan.get("chapter_plan") or []
        total_chapters = len(chapter_plan)
        completed = state.get("completed_chapters") or []
        completed_count = len(completed)

        snapshot = active_context_manager.build_snapshot(
            task_id=state["task_id"],
            stage="drafting",
            instruction=_chapter_pair_instruction(state["normalized_spec"], state.get("story_plan")),
            model_profile=_resolve_model_profile(
                active_model_catalog,
                state["normalized_spec"].get("model_id"),
            ),
            references=_build_references(state),
            memory_items=_chapter_pair_memory_items(state),
        )
        return {
            "chapter_pair_context_packet": snapshot.packet.model_dump(mode="json"),
            "total_chapters": total_chapters,
            "completed_count": completed_count,
            "batch_index": batch_index,
        }

    def draft_chapter_pair(state: WorkflowState) -> WorkflowState:
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

    def review_chapter_pair(state: WorkflowState) -> WorkflowState:
        # 自动审核模式
        if state.get("auto_review") and auto_review_manager is not None:
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
                    summary="请审核这对章节是否符合大纲要求。",
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
                decision = auto_review_manager.review(payload, policy)
                trace = [a.model_dump() for a in decision.agent_trace]
            except Exception as e:
                decision = ReviewDecision(
                    approved=False,
                    comment=f"自动审核异常: {e}，请人工介入。",
                    reasoning=str(e),
                    auto_escalated=True,
                    overall_score=0.0,
                )
                trace = []
                force_manual = True
            if force_manual or _should_interrupt_manual_review(
                approved=decision.approved,
                policy=policy,
                revision_count=state.get("chapter_pair_revision_count", 0),
                review_type="chapter_pair_review",
            ):
                review = _interrupt_chapter_pair_review(state)
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
        review = _interrupt_chapter_pair_review(state)
        approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
        comment = review.get("comment", "") if isinstance(review, dict) else ""
        return {"approved": approved, "review_comment": comment}

    def revise_chapter_pair(state: WorkflowState) -> WorkflowState:
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
        total_chapters = len((state.get("story_plan") or {}).get("chapter_plan") or [])
        batch_index = state.get("batch_index", 0) + len(current_pair)
        # 安全推进：如果 current_pair 为空则 batch_index 不增加，避免无限循环
        if batch_index >= total_chapters:
            batch_index = total_chapters
        return {
            "completed_chapters": completed_chapters,
            "batch_index": batch_index,
        }

    def verify_full_story(state: WorkflowState) -> WorkflowState:
        report = engine.verify_full_story(
            completed_chapters=state.get("completed_chapters") or [],
            story_plan=state.get("story_plan") or {},
            spec=state["normalized_spec"],
            reference_text=state.get("reference_text", ""),
            context_packet=None,
            model=state["normalized_spec"].get("model_id"),
        )
        return {"verification_report": report}

    def review_verification(state: WorkflowState) -> WorkflowState:
        # 自动审核模式
        if state.get("auto_review") and auto_review_manager is not None:
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
                decision = auto_review_manager.review(payload, policy)
                trace = [a.model_dump() for a in decision.agent_trace]
            except Exception as e:
                decision = ReviewDecision(
                    approved=False,
                    comment=f"自动审核异常: {e}，请人工介入。",
                    reasoning=str(e),
                    auto_escalated=True,
                    overall_score=0.0,
                )
                trace = []
                force_manual = True
            if force_manual or _should_interrupt_manual_review(
                approved=decision.approved,
                policy=policy,
                revision_count=state.get("verification_revision_count", 0),
                review_type="verification_review",
            ):
                review = _interrupt_verification_review(state)
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
        review = _interrupt_verification_review(state)
        approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
        comment = review.get("comment", "") if isinstance(review, dict) else ""
        return {"approved": approved, "review_comment": comment}

    def fix_verified_issues(state: WorkflowState) -> WorkflowState:
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

    def assemble_result(state: WorkflowState) -> WorkflowState:
        completed_chapters = state.get("completed_chapters") or []
        story_plan = state.get("story_plan") or {}
        spec = state["normalized_spec"]

        title = story_plan.get("working_title", "未命名")
        logline = story_plan.get("logline", "")

        if spec.get("mode") == "short_story" and len(completed_chapters) <= 3:
            body = "\n\n".join(str(ch.get("content", "")) for ch in completed_chapters)
        else:
            body = "\n\n".join(
                f"## {ch.get('title', '')}\n{ch.get('content', '')}" for ch in completed_chapters
            )

        draft_result = {
            "title": title,
            "summary": logline,
            "body": body,
            "chapters": [
                {
                    "number": ch.get("number", i + 1),
                    "title": ch.get("title", f"第{i + 1}章"),
                    "summary": ch.get("summary", ""),
                    "content": ch.get("content", ""),
                }
                for i, ch in enumerate(completed_chapters)
            ],
        }
        return {"draft_result": draft_result}

    def cancel_task(state: WorkflowState) -> WorkflowState:
        return {"cancelled": True}

    # ─────────────────────────────────────────────
    # 路由函数
    # ─────────────────────────────────────────────

    def route_after_outline_review(state: WorkflowState) -> str:
        if state.get("approved"):
            return "prepare_chapter_pair_context"
        return "revise_outline"

    def route_after_revise_outline(state: WorkflowState) -> str:
        return "review_outline"

    def route_after_chapter_pair_review(state: WorkflowState) -> str:
        if state.get("approved"):
            return "accumulate_chapters"
        return "revise_chapter_pair"

    def route_after_accumulate(state: WorkflowState) -> WorkflowState:
        batch_index = state.get("batch_index", 0)
        total_chapters = state.get("total_chapters", 0)
        if batch_index < total_chapters:
            return "prepare_chapter_pair_context"
        return "verify_full_story"

    def route_after_verification_review(state: WorkflowState) -> str:
        if state.get("approved"):
            return "assemble_result"
        return "fix_verified_issues"

    def route_after_fix_issues(state: WorkflowState) -> str:
        return "review_verification"

    # ─────────────────────────────────────────────
    # 构建图
    # ─────────────────────────────────────────────

    graph = StateGraph(WorkflowState)
    graph.add_node("normalize_request", normalize_request)
    graph.add_node("prepare_outline_context", prepare_outline_context)
    graph.add_node("plan_story", plan_story)
    graph.add_node("review_outline", review_outline)
    graph.add_node("revise_outline", revise_outline)
    graph.add_node("prepare_chapter_pair_context", prepare_chapter_pair_context)
    graph.add_node("draft_chapter_pair", draft_chapter_pair)
    graph.add_node("review_chapter_pair", review_chapter_pair)
    graph.add_node("revise_chapter_pair", revise_chapter_pair)
    graph.add_node("accumulate_chapters", accumulate_chapters)
    graph.add_node("verify_full_story", verify_full_story)
    graph.add_node("review_verification", review_verification)
    graph.add_node("fix_verified_issues", fix_verified_issues)
    graph.add_node("assemble_result", assemble_result)
    graph.add_node("cancel_task", cancel_task)

    # 边
    graph.add_edge(START, "normalize_request")
    graph.add_edge("normalize_request", "prepare_outline_context")
    graph.add_edge("prepare_outline_context", "plan_story")
    graph.add_edge("plan_story", "review_outline")

    # 大纲审核循环
    graph.add_conditional_edges(
        "review_outline",
        route_after_outline_review,
        {
            "prepare_chapter_pair_context": "prepare_chapter_pair_context",
            "revise_outline": "revise_outline",
        },
    )
    graph.add_edge("revise_outline", "review_outline")

    # 章节对循环
    graph.add_edge("prepare_chapter_pair_context", "draft_chapter_pair")
    graph.add_edge("draft_chapter_pair", "review_chapter_pair")
    graph.add_conditional_edges(
        "review_chapter_pair",
        route_after_chapter_pair_review,
        {
            "accumulate_chapters": "accumulate_chapters",
            "revise_chapter_pair": "revise_chapter_pair",
        },
    )
    graph.add_edge("revise_chapter_pair", "review_chapter_pair")
    graph.add_conditional_edges(
        "accumulate_chapters",
        route_after_accumulate,
        {
            "prepare_chapter_pair_context": "prepare_chapter_pair_context",
            "verify_full_story": "verify_full_story",
        },
    )

    # 验证循环
    graph.add_edge("verify_full_story", "review_verification")
    graph.add_conditional_edges(
        "review_verification",
        route_after_verification_review,
        {
            "assemble_result": "assemble_result",
            "fix_verified_issues": "fix_verified_issues",
        },
    )
    graph.add_edge("fix_verified_issues", "review_verification")
    graph.add_edge("assemble_result", END)
    graph.add_edge("cancel_task", END)

    return graph.compile(checkpointer=_create_checkpointer(checkpoint_db_path))


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────


def _resolve_model_profile(
    model_catalog: ModelCatalogService | None,
    model_id: str | None,
) -> ModelContextProfile:
    fallback_model_id = (model_id or "").strip() or "gpt-5.4"
    if model_catalog is None:
        return ModelContextProfile(
            model_id=fallback_model_id,
            provider="openai_compatible",
            max_input_tokens=128000,
            max_output_tokens=8192,
            reserved_output_tokens=2048,
        )
    profile = model_catalog.get_model_profile(fallback_model_id)
    capabilities = profile.get("capabilities") if isinstance(profile.get("capabilities"), dict) else {}
    context_window = capabilities.get("context_window") if isinstance(capabilities.get("context_window"), dict) else {}
    return ModelContextProfile(
        model_id=str(profile.get("id") or fallback_model_id),
        provider=str(profile.get("provider") or "openai_compatible"),
        max_input_tokens=int(context_window.get("max_input_tokens") or 128000),
        max_output_tokens=int(context_window.get("max_output_tokens") or 8192),
        reserved_output_tokens=min(
            int(context_window.get("max_output_tokens") or 2048),
            int(context_window.get("max_input_tokens") or 128000),
        ),
        supports_runtime_cache=bool(
            (capabilities.get("cache") or {}).get("runtime_context_cache", True)
            if isinstance(capabilities.get("cache"), dict)
            else True
        ),
        profile_version=str((profile.get("metadata") or {}).get("profile_version") or "v1")
        if isinstance(profile.get("metadata"), dict)
        else "v1",
    )


def _build_references(state: WorkflowState) -> list[ReferenceMaterial]:
    source_assets = state.get("source_assets") or []
    references: list[ReferenceMaterial] = []
    for index, asset in enumerate(source_assets):
        if not isinstance(asset, dict):
            continue
        content = str(asset.get("content") or "").strip()
        if not content:
            continue
        references.append(
            ReferenceMaterial(
                source_id=str(asset.get("id") or f"source-{index + 1}"),
                title=str(asset.get("filename") or f"参考素材 {index + 1}"),
                content=content,
                priority=max(100 - index, 1),
                metadata={"media_type": asset.get("media_type")},
            )
        )
    if references:
        return references
    reference_text = str(state.get("reference_text") or "").strip()
    if not reference_text:
        return []
    return [
        ReferenceMaterial(
            source_id="reference-text",
            title="参考素材",
            content=reference_text,
            priority=50,
        )
    ]


def _outline_instruction(spec: dict[str, Any]) -> str:
    return (
        f"模式：{spec.get('mode', '')}\n"
        f"题材：{spec.get('genre', '')}\n"
        f"风格：{spec.get('style', '')}\n"
        f"用户目标字数：{spec.get('requested_target_words', spec.get('target_words', ''))}\n"
        f"目标字数：{spec.get('target_words', '')}\n"
        f"受众：{spec.get('audience', '')}\n"
        f"禁忌：{spec.get('banned', '')}\n"
        f"标题倾向：{spec.get('title_hint', '')}\n"
        f"创作要求：{spec.get('prompt', '')}"
    ).strip()


def _chapter_pair_instruction(spec: dict[str, Any], story_plan: dict[str, Any] | None) -> str:
    title = ""
    logline = ""
    if isinstance(story_plan, dict):
        title = str(story_plan.get("working_title") or "")
        logline = str(story_plan.get("logline") or "")
    return (
        f"模式：{spec.get('mode', '')}\n"
        f"作品标题：{title}\n"
        f"一句话梗概：{logline}\n"
        f"目标字数：{spec.get('target_words', '')}\n"
        f"风格要求：{spec.get('style', '')}\n"
        f"禁忌要求：{spec.get('banned', '')}\n"
        f"正文任务：基于既定大纲连续起草小说正文，每次生成一对章节。"
    ).strip()


def _normalize_target_words(mode: str, requested_target_words: int) -> int:
    if mode == "short_story":
        return max(requested_target_words + 100, 600)
    return requested_target_words


def _chapter_pair_memory_items(state: WorkflowState) -> list[str]:
    story_plan = state.get("story_plan")
    if not isinstance(story_plan, dict):
        return []
    memory_items: list[str] = []
    for note in story_plan.get("world_notes") or []:
        memory_items.append(f"世界观：{note}")
    for note in story_plan.get("character_notes") or []:
        memory_items.append(f"人物：{note}")
    for chapter in story_plan.get("chapter_plan") or []:
        if not isinstance(chapter, dict):
            continue
        memory_items.append(
            f"章节计划：第{chapter.get('number')}章 {chapter.get('title')} - {chapter.get('goal')}"
        )
    return memory_items
