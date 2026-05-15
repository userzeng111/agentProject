from __future__ import annotations

from typing import Any, TypedDict


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
    # 大纲批次分步
    outline_phase: str
    outline_batch_index: int
    outline_batch_size: int
    outline_total_count: int
    outline_completed_count: int
    outline_batch_retry_count: int
    current_batch_chapter_plans: list[dict[str, Any]]
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
    # 自动审核
    auto_review: bool
    auto_review_policy: dict[str, Any]
    auto_review_trace: list[dict[str, Any]]


MAX_OUTLINE_REVISIONS = 5
MAX_CHAPTER_PAIR_REVISIONS = 5
MAX_VERIFICATION_REVISIONS = 3
