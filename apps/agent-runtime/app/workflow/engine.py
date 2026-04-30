"""工作流引擎实现。

将 LangGraph 图构建逻辑封装为 NovelWorkflowEngine，
通过 WorkflowCallbacks 注入节点实现，实现编排与业务解耦。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph.checkpointer import _create_checkpointer
from app.graph.routers.flow import (
    route_after_accumulate,
    route_after_verification_review,
)
from app.graph.routers.review import (
    route_after_chapter_pair_review,
    route_after_outline_review,
)
from app.graph.state import WorkflowState
from app.workflow.callbacks import WorkflowCallbacks


def _trace_round_count(trace: list[dict[str, Any]] | None) -> int:
    """统计已完成的审核轮数。"""
    return sum(
        1
        for item in (trace or [])
        if isinstance(item, dict) and item.get("__summary__")
    )


def _build_auto_review_summary(
    *,
    prev_trace: list[dict[str, Any]],
    decision: Any,
    review_type: str,
    revision_count: int,
    batch_index: int | None = None,
) -> dict[str, Any]:
    """构建自动审核摘要记录。"""
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


def _should_interrupt_manual_review(
    *,
    approved: bool,
    policy: Any,
    revision_count: int,
    review_type: str,
) -> bool:
    """判断当前审核是否应中断并转人工。"""
    if approved:
        return False
    if not policy.allow_self_revisions:
        return True
    return revision_count >= max(policy.get_max_auto_revisions(review_type), 0)


def _interrupt_outline_review(state: WorkflowState):
    """大纲审核中断处理。"""
    from app.graph.nodes.outline import interrupt_outline_review

    return interrupt_outline_review(state)


def _interrupt_chapter_pair_review(state: WorkflowState):
    """章节对审核中断处理。"""
    from app.graph.nodes.chapter import interrupt_chapter_pair_review

    return interrupt_chapter_pair_review(state)


def _interrupt_verification_review(state: WorkflowState):
    """验证审核中断处理。"""
    from app.graph.nodes.verification import interrupt_verification_review

    return interrupt_verification_review(state)


class NovelWorkflowEngine:
    """小说工作流引擎。

    负责构建并编译 LangGraph 状态图，提供启动、恢复、状态查询等公共方法。
    所有节点逻辑通过 ``WorkflowCallbacks`` 注入，引擎本身不依赖具体业务服务。
    """

    def __init__(
        self,
        callbacks: WorkflowCallbacks,
        checkpoint_db_path: str | Path | None = None,
    ):
        self.callbacks = callbacks
        self.graph = self._build_graph(callbacks, checkpoint_db_path)

    def _build_graph(
        self,
        callbacks: WorkflowCallbacks,
        checkpoint_db_path: str | Path | None = None,
    ):
        """构建并编译工作流图。"""
        graph = StateGraph(WorkflowState)

        # 注册所有节点
        node_names = [
            "normalize_request",
            "prepare_outline_context",
            "plan_story",
            "review_outline",
            "revise_outline",
            "prepare_chapter_pair_context",
            "draft_chapter_pair",
            "review_chapter_pair",
            "revise_chapter_pair",
            "accumulate_chapters",
            "verify_full_story",
            "review_verification",
            "fix_verified_issues",
            "assemble_result",
            "cancel_task",
        ]
        for node_name in node_names:
            callback = getattr(callbacks, node_name, None)
            if callback is None:
                raise ValueError(f"callbacks 缺少必需节点: {node_name}")
            graph.add_node(node_name, callback)

        # 边：主线流程
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
                "cancel_task": "cancel_task",
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
                "cancel_task": "cancel_task",
            },
        )
        graph.add_edge("revise_chapter_pair", "review_chapter_pair")
        graph.add_conditional_edges(
            "accumulate_chapters",
            route_after_accumulate,
            {
                "prepare_chapter_pair_context": "prepare_chapter_pair_context",
                "verify_full_story": "verify_full_story",
                "cancel_task": "cancel_task",
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
                "cancel_task": "cancel_task",
            },
        )
        graph.add_edge("fix_verified_issues", "verify_full_story")
        graph.add_edge("assemble_result", END)
        graph.add_edge("cancel_task", END)

        return graph.compile(checkpointer=_create_checkpointer(checkpoint_db_path))

    def start(self, initial_state: dict, config: dict) -> dict:
        """启动工作流。"""
        return self.graph.invoke(initial_state, config=config)

    def resume(self, command: Command, config: dict) -> dict:
        """从中断点恢复工作流。"""
        return self.graph.invoke(command, config=config)

    def get_state(self, config: dict):
        """获取当前图状态。"""
        return self.graph.get_state(config)

    def update_state(
        self,
        config: dict,
        values: dict,
        as_node: str | None = None,
    ):
        """更新图状态。"""
        return self.graph.update_state(config, values, as_node=as_node)
