"""工作流引擎实现。

将 LangGraph 图构建逻辑封装为 NovelWorkflowEngine，
通过 WorkflowCallbacks 注入节点实现，实现编排与业务解耦。
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph.checkpointer import _create_checkpointer
from app.graph.routers.flow import (
    route_after_accumulate,
    route_after_verification_review,
)
from app.graph.routers.review import (
    route_after_chapter_gate_review,
    route_after_chapter_pair_review,
    route_after_outline_review,
)
from app.graph.state import WorkflowState
from app.workflow.callbacks import WorkflowCallbacks


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
            "plan_chapter_batch",
            "review_outline",
            "revise_outline",
            "prepare_chapter_pair_context",
            "draft_chapter_pair",
            "chapter_gate_review",
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
                "plan_chapter_batch": "plan_chapter_batch",
                "revise_outline": "revise_outline",
                "cancel_task": "cancel_task",
            },
        )
        graph.add_edge("plan_chapter_batch", "review_outline")
        graph.add_edge("revise_outline", "review_outline")

        # 章节对循环
        graph.add_edge("prepare_chapter_pair_context", "draft_chapter_pair")
        graph.add_edge("draft_chapter_pair", "chapter_gate_review")
        graph.add_conditional_edges(
            "chapter_gate_review",
            route_after_chapter_gate_review,
            {
                "accumulate_chapters": "accumulate_chapters",
                "review_chapter_pair": "review_chapter_pair",
                "cancel_task": "cancel_task",
            },
        )
        graph.add_conditional_edges(
            "review_chapter_pair",
            route_after_chapter_pair_review,
            {
                "accumulate_chapters": "accumulate_chapters",
                "revise_chapter_pair": "revise_chapter_pair",
                "cancel_task": "cancel_task",
            },
        )
        graph.add_edge("revise_chapter_pair", "chapter_gate_review")
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
