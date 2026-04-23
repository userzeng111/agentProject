from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
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

from app.graph.checkpointer import _create_checkpointer
from app.graph.utils.spec import build_normalized_spec
from app.graph.utils.helpers import (
    _resolve_model_profile,
    _build_references,
    _outline_instruction,
    _chapter_pair_instruction,
    _planned_chapter_count,
    _normalize_story_plan,
    _chapter_pair_memory_items,
)
from app.graph.nodes.outline import (
    normalize_request as _normalize_request_node,
    prepare_outline_context as _prepare_outline_context_node,
    plan_story as _plan_story_node,
    review_outline as _review_outline_node,
    revise_outline as _revise_outline_node,
    interrupt_outline_review,
)
from app.graph.nodes.chapter import (
    prepare_chapter_pair_context as _prepare_chapter_pair_context_node,
    draft_chapter_pair as _draft_chapter_pair_node,
    review_chapter_pair as _review_chapter_pair_node,
    revise_chapter_pair as _revise_chapter_pair_node,
    accumulate_chapters as _accumulate_chapters_node,
    interrupt_chapter_pair_review,
)
from app.graph.nodes.verification import (
    verify_full_story as _verify_full_story_node,
    review_verification as _review_verification_node,
    fix_verified_issues as _fix_verified_issues_node,
    interrupt_verification_review,
)
from app.graph.nodes.final import (
    assemble_result as _assemble_result_node,
    cancel_task as _cancel_task_node,
)
from app.graph.routers.review import (
    route_after_outline_review,
    route_after_revise_outline,
    route_after_chapter_pair_review,
)
from app.graph.routers.flow import (
    route_after_accumulate,
    route_after_verification_review,
    route_after_fix_issues,
)

logger = logging.getLogger(__name__)


from app.graph.state import WorkflowState


def _trace_round_count(trace: list[dict[str, Any]] | None) -> int:
    return sum(1 for item in (trace or []) if isinstance(item, dict) and item.get("__summary__"))


def _build_auto_review_summary(
    *,
    prev_trace: list[dict[str, Any]],
    decision: ReviewDecision,
    review_type: str,
    revision_count: int,
    batch_index: int | None = None,
) -> dict[str, Any]:
    return {
        "__summary__": True,
        "trace_round": _trace_round_count(prev_trace) + 1,
        "review_type": review_type,
        "revision_count": revision_count,
        "batch_index": batch_index,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "overall_score": decision.overall_score,
        "approved": decision.approved,
        "auto_escalated": decision.auto_escalated,
        "comment": decision.comment,
        "reasoning": decision.reasoning,
        "critical_issues": decision.critical_issues,
        "warnings": decision.warnings,
    }


def build_graph(
    engine: StoryEngine,
    context_manager: ContextManager | None = None,
    model_catalog: ModelCatalogService | None = None,
    history_loader: Callable[[str, str, str], list[dict[str, str]]] | None = None,
    checkpoint_db_path: str | Path | None = None,
    rag_service: Any | None = None,
    novel_skill_service: Any | None = None,
    style_profile_service: Any | None = None,
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
    # 动态 Agent 审核桥接层（与旧 AutoReviewManager 并行，通过配置切换）
    dynamic_review_bridge: Any | None = None
    try:
        from app.settings.config import get_settings
        _settings = get_settings()
        gateway_client = getattr(engine, "gateway_client", None)
        if (
            getattr(_settings, "dynamic_agent_review", False)
            and gateway_client is not None
            and hasattr(gateway_client, "complete_stream_sync")
        ):
            from app.agents.dynamic.bridge import DynamicReviewBridge
            dynamic_review_bridge = DynamicReviewBridge(
                gateway_client=gateway_client,
                default_model=getattr(_settings, "auto_review_auditor_model", "MiniMax-M2.7-highspeed"),
            )
            logger.info("动态 Agent 审核模式已启用")
    except Exception as e:
        logger.warning("动态 Agent 审核初始化失败，使用旧模式: %s", e)
    # 审核执行器：优先使用动态桥接层，否则使用旧 AutoReviewManager
    def _execute_auto_review(payload: ReviewPayload, policy: AutoReviewPolicy):
        """统一的审核执行入口，根据配置选择动态/旧模式。"""
        if dynamic_review_bridge is not None:
            return dynamic_review_bridge.review(payload, policy)
        if auto_review_manager is None:
            raise RuntimeError("自动审核执行器不可用。")
        return auto_review_manager.review(payload, policy)

    auto_review_executor_available = dynamic_review_bridge is not None or auto_review_manager is not None

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
        return interrupt_outline_review(state)

    def _interrupt_chapter_pair_review(state: WorkflowState):
        return interrupt_chapter_pair_review(state)

    def _interrupt_verification_review(state: WorkflowState):
        return interrupt_verification_review(state)

    # ─────────────────────────────────────────────
    # 节点定义（闭包包装，注入依赖）
    # ─────────────────────────────────────────────

    def normalize_request(state: WorkflowState) -> WorkflowState:
        return _normalize_request_node(
            state,
            auto_review=auto_review,
            auto_review_policy=auto_review_policy,
            novel_skill_service=novel_skill_service,
            style_profile_service=style_profile_service,
        )

    def prepare_outline_context(state: WorkflowState) -> WorkflowState:
        return _prepare_outline_context_node(
            state,
            context_manager=active_context_manager,
            model_catalog=active_model_catalog,
            rag_service=rag_service,
        )

    def plan_story(state: WorkflowState) -> WorkflowState:
        return _plan_story_node(state, engine=engine)

    def review_outline(state: WorkflowState) -> WorkflowState:
        return _review_outline_node(
            state,
            auto_review_executor_available=auto_review_executor_available,
            execute_auto_review=_execute_auto_review,
            should_interrupt_manual_review=_should_interrupt_manual_review,
            interrupt_outline_review=_interrupt_outline_review,
            build_auto_review_summary=_build_auto_review_summary,
        )

    def revise_outline(state: WorkflowState) -> WorkflowState:
        return _revise_outline_node(state, engine=engine)

    def prepare_chapter_pair_context(state: WorkflowState) -> WorkflowState:
        return _prepare_chapter_pair_context_node(
            state,
            context_manager=active_context_manager,
            model_catalog=active_model_catalog,
            rag_service=rag_service,
        )

    def draft_chapter_pair(state: WorkflowState) -> WorkflowState:
        return _draft_chapter_pair_node(state, engine=engine)

    def review_chapter_pair(state: WorkflowState) -> WorkflowState:
        return _review_chapter_pair_node(
            state,
            auto_review_executor_available=auto_review_executor_available,
            execute_auto_review=_execute_auto_review,
            should_interrupt_manual_review=_should_interrupt_manual_review,
            interrupt_chapter_pair_review=_interrupt_chapter_pair_review,
            build_auto_review_summary=_build_auto_review_summary,
        )

    def revise_chapter_pair(state: WorkflowState) -> WorkflowState:
        return _revise_chapter_pair_node(state, engine=engine)

    def accumulate_chapters(state: WorkflowState) -> WorkflowState:
        return _accumulate_chapters_node(state)

    def verify_full_story(state: WorkflowState) -> WorkflowState:
        return _verify_full_story_node(state, engine=engine)

    def review_verification(state: WorkflowState) -> WorkflowState:
        return _review_verification_node(
            state,
            auto_review_executor_available=auto_review_executor_available,
            execute_auto_review=_execute_auto_review,
            should_interrupt_manual_review=_should_interrupt_manual_review,
            interrupt_verification_review=_interrupt_verification_review,
            build_auto_review_summary=_build_auto_review_summary,
        )

    def fix_verified_issues(state: WorkflowState) -> WorkflowState:
        return _fix_verified_issues_node(state, engine=engine)

    def assemble_result(state: WorkflowState) -> WorkflowState:
        return _assemble_result_node(state)

    def cancel_task(state: WorkflowState) -> WorkflowState:
        return _cancel_task_node(state)

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
    graph.add_edge("fix_verified_issues", "verify_full_story")
    graph.add_edge("assemble_result", END)
    graph.add_edge("cancel_task", END)

    return graph.compile(checkpointer=_create_checkpointer(checkpoint_db_path))
