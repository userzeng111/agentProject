"""工作流回调接口定义。

将 LangGraph 工作流节点与外部服务解耦：
每个节点通过回调函数委托给业务层实现，工作流引擎本身不依赖任何具体服务。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.graph.state import WorkflowState


def _noop_window_wait(_: WorkflowState) -> WorkflowState:
    return {}


@dataclass
class WorkflowCallbacks:
    """工作流节点回调注册表。

    每个回调接收当前 WorkflowState，返回更新后的 WorkflowState。
    业务层在组装回调时通过闭包注入所需的外部依赖（engine、rag_service 等）。
    """

    normalize_request: Callable[[WorkflowState], WorkflowState]
    prepare_outline_context: Callable[[WorkflowState], WorkflowState]
    plan_story: Callable[[WorkflowState], WorkflowState]
    plan_chapter_batch: Callable[[WorkflowState], WorkflowState]
    review_outline: Callable[[WorkflowState], WorkflowState]
    revise_outline: Callable[[WorkflowState], WorkflowState]
    prepare_chapter_pair_context: Callable[[WorkflowState], WorkflowState]
    draft_chapter_pair: Callable[[WorkflowState], WorkflowState]
    chapter_gate_review: Callable[[WorkflowState], WorkflowState]
    review_chapter_pair: Callable[[WorkflowState], WorkflowState]
    revise_chapter_pair: Callable[[WorkflowState], WorkflowState]
    accumulate_chapters: Callable[[WorkflowState], WorkflowState]
    verify_full_story: Callable[[WorkflowState], WorkflowState]
    review_verification: Callable[[WorkflowState], WorkflowState]
    fix_verified_issues: Callable[[WorkflowState], WorkflowState]
    assemble_result: Callable[[WorkflowState], WorkflowState]
    cancel_task: Callable[[WorkflowState], WorkflowState]
    wait_for_window_drafts: Callable[[WorkflowState], WorkflowState] = _noop_window_wait


# 兼容旧调用：允许通过关键字参数逐个传入
WorkflowCallbacks.__init__.__doc__ = """
Args:
    normalize_request: 规范化输入节点回调
    prepare_outline_context: 大纲上下文准备节点回调
    plan_story: 故事大纲生成节点回调
    review_outline: 大纲审核节点回调
    revise_outline: 大纲修订节点回调
    prepare_chapter_pair_context: 章节对上下文准备节点回调
    draft_chapter_pair: 章节对起草节点回调
    chapter_gate_review: 章节批次门禁验证节点回调
    review_chapter_pair: 章节对审核节点回调
    revise_chapter_pair: 章节对修订节点回调
    accumulate_chapters: 章节累积节点回调
    verify_full_story: 全文验证节点回调
    review_verification: 验证审核节点回调
    fix_verified_issues: 修复验证问题节点回调
    assemble_result: 结果组装节点回调
    cancel_task: 任务取消节点回调
"""
