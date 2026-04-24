from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

from langgraph.types import Command

from app.context.cache_store import FileBackedCacheStore, InMemoryCacheStore, LayeredCacheStore
from app.context.manager import ContextManager
from app.domain.models import (
    AgentRunRecord,
    ArchiveTaskDetailResponse,
    ArchiveTaskListResponse,
    ArtifactItem,
    ChapterDraft,
    ContinueDraftRequest,
    DashboardResponse,
    DraftResult,
    RecoveryOption,
    RecoveryPreview,
    ResultResponse,
    ReviewPayload,
    ReviewResponse,
    SourceAsset,
    StoryPlan,
    SubtaskRecord,
    SubtaskStatus,
    TaskCreateRequest,
    TaskMode,
    TaskRecord,
    TaskStatus,
    TaskSummary,
    TaskEvent,
    WorkspaceResponse,
    utc_now,
)
from app.graph.main_graph import (
    _build_references,
    _chapter_pair_instruction,
    _outline_instruction,
    _resolve_model_profile,
    build_normalized_spec,
    build_graph,
)
from app.graph.supervisor_graph import build_initial_supervisor_plan
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import (
    StoryEngine,
    reset_exchange_callback,
    reset_progress_callback,
    set_exchange_callback,
    set_progress_callback,
)
from app.rag.service import RagService
from app.storage.task_store import TaskLogStore

logger = logging.getLogger(__name__)

_STAGE_LABELS: dict[str, str] = {
    TaskStatus.WAITING_OUTLINE_REVIEW.value: "待大纲审核",
    TaskStatus.READY_FOR_BATCH.value: "可继续创作",
    TaskStatus.WAITING_CHAPTER_REVIEW.value: "待章节审核",
    TaskStatus.WAITING_VERIFICATION_REVIEW.value: "待验证审核",
    TaskStatus.PLANNING.value: "重新进入规划",
}


class TaskServiceReviewMixin:

    def resume_task(self, task_id: str, approved: bool, comment: str, model_id: str | None = None) -> TaskRecord:
        valid_statuses = {
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
        }
        task = self.store.get(task_id)
        task = self._reconcile_pending_review_with_novel_project(task)
        if task.status not in valid_statuses or task.pending_review is None:
            task = self.recover_task(task_id, model_id=model_id)
            task = self._reconcile_pending_review_with_novel_project(task)
        if task.status not in valid_statuses or task.pending_review is None:
            raise ValueError("当前任务没有待恢复的审核节点。")
        action_model_id = self._resolve_action_model_id(task, model_id)
        review_type = task.pending_review.type

        if review_type == "outline_review" and approved:
            story_plan = task.story_plan or task.pending_review.story_plan
            if story_plan is None:
                raise ValueError("当前任务缺少大纲，无法进入继续创作阶段。")
            task.story_plan = story_plan
            self._ensure_novel_project_seeded(task)
            snapshot = self.store.set_ready_for_batch(
                task_id,
                story_plan,
                message=comment.strip() or "大纲审核通过，等待继续创作。",
            )
            return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)

        if review_type == "chapter_pair_review" and self._has_novel_project(task_id):
            story_plan = task.story_plan
            if story_plan is None:
                raise ValueError("当前任务缺少大纲，无法推进章节批次。")
            chapter_numbers = [
                int(ch.number if isinstance(ch, ChapterDraft) else ch.get("number"))
                for ch in (task.pending_review.chapter_pair or [])
            ]
            from app.storage.db_repository import (
                count_approved_chapters,
                get_active_batch,
                get_novel_project,
                mark_batch_approved,
                mark_batch_rejected,
                mark_outline_chapters_approved,
                update_project_status,
            )

            batch = get_active_batch(task_id)
            if batch is None:
                raise ValueError("当前任务缺少章节批次记录。")
            project = get_novel_project(task_id)
            if project is None:
                raise ValueError("当前任务缺少小说项目记录。")
            if approved:
                mark_outline_chapters_approved(task_id, chapter_numbers)
                mark_batch_approved(task_id, batch.batch_no)
                completed_count = count_approved_chapters(task_id)
                next_chapter_number = completed_count + 1
                if completed_count >= project.planned_chapter_count:
                    update_project_status(
                        task_id,
                        status=TaskStatus.WAITING_VERIFICATION_REVIEW.value,
                        completed_chapter_count=completed_count,
                        next_chapter_number=next_chapter_number,
                        current_generating_chapter_number=None,
                    )
                    note = comment.strip() or "当前批次审核通过，全部章节已完成，等待全文验证。"
                    task.pending_review = ReviewPayload(
                        type="verification_review",
                        version="v1",
                        summary="请审核全文一致性验证报告。",
                        verification_report={"overall_score": 100, "issues": []},
                    )
                    self.store.save(task)
                    snapshot = self.store.set_waiting_verification_review(task_id, task.pending_review)
                    return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)
                update_project_status(
                    task_id,
                    status=TaskStatus.READY_FOR_BATCH.value,
                    completed_chapter_count=completed_count,
                    next_chapter_number=next_chapter_number,
                    current_generating_chapter_number=None,
                )
                snapshot = self.store.set_ready_for_batch(
                    task_id,
                    story_plan,
                    message=comment.strip() or "当前批次审核通过，等待继续创作。",
                )
                return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)

            mark_batch_rejected(task_id, batch.batch_no)
            update_project_status(
                task_id,
                status=TaskStatus.READY_FOR_BATCH.value,
                completed_chapter_count=project.completed_chapter_count,
                next_chapter_number=project.next_chapter_number,
                current_generating_chapter_number=None,
            )
            snapshot = self.store.set_ready_for_batch(
                task_id,
                story_plan,
                message=comment.strip() or "当前批次已驳回，等待继续创作。",
            )
            return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)

        if review_type == "chapter_pair_review":
            note = comment.strip() or (
                "人工审核已通过，任务转入后台处理。"
                if approved
                else "人工审核已驳回，正在修订章节。"
            )
            snapshot = self.store.mark_stage(
                task_id,
                status=TaskStatus.DRAFTING,
                stage="drafting",
                progress=max(task.progress, 60),
                message=note,
                event_type="review.submitted",
                unit_id=f"chapter-pair-{task.pending_review.batch_index or 0}",
            )
        elif review_type == "verification_review":
            note = comment.strip() or (
                "人工审核已通过，任务转入后台处理。"
                if approved
                else "人工审核已驳回，正在根据验证意见修复。"
            )
            snapshot = self.store.mark_stage(
                task_id,
                status=TaskStatus.DRAFTING,
                stage="verification",
                progress=max(task.progress, 92),
                message=note,
                event_type="review.submitted",
                unit_id="verification",
            )
        else:
            note = comment.strip() or (
                "人工审核已通过，任务转入后台处理。"
                if approved
                else "人工审核已驳回，正在修订大纲。"
            )
            snapshot = self.store.mark_stage(
                task_id,
                status=TaskStatus.DRAFTING if approved else TaskStatus.PLANNING,
                stage="drafting" if approved else "planning",
                progress=60 if approved else max(task.progress, 56),
                message=note,
                event_type="review.submitted",
                unit_id="outline",
            )
        snapshot = self._record_last_action(task_id, model_id=action_model_id, kind="resume")
        snapshot = self._sync_supervisor_plan(task_id)
        self._start_background(task_id, self._resume_task_sync, task_id, approved, comment, action_model_id)
        return snapshot

