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


class TaskService:
    _STALE_RUN_AFTER = timedelta(minutes=10)

    def __init__(
        self,
        store: TaskLogStore,
        engine: StoryEngine,
        model_catalog: ModelCatalogService | None = None,
        context_manager: ContextManager | None = None,
        rag_service: RagService | None = None,
        novel_skill_service: Any | None = None,
        style_profile_service: Any | None = None,
        auto_review: bool = False,
        auto_review_policy: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.engine = engine
        self.model_catalog = model_catalog or ModelCatalogService(
            settings=engine.settings,
            gateway_client=engine.gateway_client,
        )
        self.context_manager = context_manager or ContextManager(
            cache_store=LayeredCacheStore(
                [
                    InMemoryCacheStore(ttl_seconds=1800),
                    FileBackedCacheStore(Path(self.store.root_dir) / "cache" / "context", ttl_seconds=86400),
                ]
            )
        )
        self.rag_service = rag_service
        self.novel_skill_service = novel_skill_service
        self.style_profile_service = style_profile_service
        self.auto_review = auto_review
        self.auto_review_policy = auto_review_policy or {}
        checkpoint_db_path = str(Path(self.store.root_dir) / "checkpoints.db")
        self.graph = build_graph(
            engine,
            context_manager=self.context_manager,
            model_catalog=self.model_catalog,
            history_loader=self._load_message_history,
            checkpoint_db_path=checkpoint_db_path,
            rag_service=self.rag_service,
            novel_skill_service=self.novel_skill_service,
            style_profile_service=self.style_profile_service,
            auto_review=auto_review,
            auto_review_policy=self.auto_review_policy,
        )
        self._active_runs: set[str] = set()
        self._run_lock = threading.Lock()

        # 初始化 SQLite 业务数据库
        from app.storage.database import init_db
        init_db(str(Path(self.store.root_dir) / "data.db"))

        # 启动时同步运行时默认模型到 StoryEngine
        runtime_default = self.model_catalog._effective_default_model()
        if self.model_catalog._runtime_default_model and hasattr(self.engine, "set_runtime_default_model"):
            self.engine.set_runtime_default_model(runtime_default)

    def create_task(self, payload: TaskCreateRequest) -> TaskRecord:
        requested_model = (payload.model_id or "").strip() or self.model_catalog._effective_default_model()
        self.model_catalog.ensure_novel_generation_model_supported(requested_model)
        task = self.store.create_task(payload)
        task.supervisor_plan = build_initial_supervisor_plan(payload)
        if self._resolve_task_auto_review(task) and not task.auto_review_policy:
            task.auto_review_policy = dict(self.auto_review_policy)
        task = self.store.save(task)
        return self._sync_supervisor_plan(task.id)

    def _resolve_task_model_id(self, task: TaskRecord) -> str:
        candidate = (task.model_id or "").strip() or self.model_catalog._effective_default_model()
        self.model_catalog.ensure_novel_generation_model_supported(candidate)
        return candidate

    def _resolve_action_model_id(self, task: TaskRecord, model_id: str | None) -> str:
        requested_model = (model_id or "").strip()
        if requested_model:
            self.model_catalog.ensure_novel_generation_model_supported(requested_model)
            return requested_model
        return self._resolve_task_model_id(task)

    def _with_model_id(self, payload: dict[str, Any], model_id: str) -> dict[str, Any]:
        next_payload = dict(payload)
        next_payload["model_id"] = model_id
        return next_payload

    def _record_last_action(self, task_id: str, *, model_id: str, kind: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task.last_action_model_id == model_id and task.last_action_kind == kind:
            return task
        task.last_action_model_id = model_id
        task.last_action_kind = kind
        return self.store.save(task)

    def add_source(self, task_id: str, filename: str, media_type: str, content: str) -> TaskRecord:
        source = SourceAsset(filename=filename, media_type=media_type, content=content)
        return self.store.add_source(task_id, source)

    def get_task(self, task_id: str) -> TaskRecord:
        return self.recover_task(task_id)

    def recover_task(
        self,
        task_id: str,
        force: bool = False,
        model_id: str | None = None,
        recovery_mode: str = "recover_to_stable",
    ) -> TaskRecord:
        task = self.store.get(task_id)
        action_model_id = self._resolve_action_model_id(task, model_id)

        if recovery_mode == "restart_from_input":
            retried = self._retry_task_from_original_input(task, action_model_id)
            if retried is not None:
                return self._safe_sync_supervisor_plan(task_id, fallback=retried)
            raise ValueError("当前任务不能按原始输入重新开始。")
        if recovery_mode != "recover_to_stable":
            raise ValueError("不支持的 recovery_mode。")

        if not self._should_attempt_recovery(task, force=force):
            return task

        recovered = self._recover_task_from_stable_state(task, force=force)
        if recovered is not None:
            return self._safe_sync_supervisor_plan(task_id, fallback=recovered)
        if force:
            raise ValueError("当前没有可回填的稳定阶段。")

        if task.status is not TaskStatus.WAITING_MANUAL_ACTION or force:
            return self.store.set_waiting_manual_action(
                task_id,
                "任务当前无法恢复，缺少可恢复的稳定产物，已转入待人工处理。",
                payload={
                    "summary": "任务无法自动恢复，已转入待人工处理。",
                    "display_level": "public",
                    "reason": "missing_stable_state",
                },
            )
        return task

    def cancel_task(self, task_id: str, comment: str = "") -> TaskRecord:
        """取消一个正在运行或等待审核的任务。"""
        # 检查任务是否在活跃运行中，如果是则先移除
        with self._run_lock:
            was_active = task_id in self._active_runs
            if was_active:
                self._active_runs.discard(task_id)
        record = self.store.cancel_task(task_id, comment=comment)
        self._sync_supervisor_plan(task_id)
        return record

    def delete_task(self, task_id: str) -> dict[str, str]:
        """删除一个已取消/已完成/失败的任务（不能删除运行中的任务）。"""
        # 再次确认任务不在活跃运行中
        with self._run_lock:
            if task_id in self._active_runs:
                raise ValueError("任务正在运行中，请先取消后再删除。")
        return self.store.delete_task(task_id)

    def run_task(self, task_id: str, model_id: str | None = None) -> TaskRecord:
        task = self.store.get(task_id)
        if task.status not in {TaskStatus.CREATED, TaskStatus.SOURCES_INGESTED}:
            raise ValueError("只有新建任务或已上传素材的任务才能开始生成。")
        if self.rag_service is not None and not self.rag_service.is_ready():
            raise ValueError(self.rag_service.readiness_error())
        action_model_id = self._resolve_action_model_id(task, model_id)
        snapshot = self.store.mark_stage(
            task_id,
            status=TaskStatus.PLANNING,
            stage="planning",
            progress=max(task.progress, 5),
            message="任务已进入后台执行，正在整理创作要求。",
            event_type="task.queued",
        )
        snapshot = self._record_last_action(task_id, model_id=action_model_id, kind="run")
        snapshot = self._sync_supervisor_plan(task_id)
        self._start_background(task_id, self._run_task_sync, task_id, action_model_id)
        return snapshot

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

    def continue_task(self, task_id: str, payload: ContinueDraftRequest | dict[str, Any]) -> TaskRecord:
        request = payload if isinstance(payload, ContinueDraftRequest) else ContinueDraftRequest.model_validate(payload)
        task = self.store.get(task_id)
        action_model_id = self._resolve_action_model_id(task, request.model_id)
        self._ensure_novel_project_seeded(task)

        from app.storage.db_repository import (
            create_batch,
            get_active_batch,
            get_batch_by_request,
            get_novel_project,
            mark_batch_failed,
            upsert_outline_chapter_draft,
            update_project_status,
        )

        existing_batch = get_batch_by_request(task_id, request.continue_request_id)
        if existing_batch is not None:
            return self.store.get(task_id)

        if task.status is not TaskStatus.READY_FOR_BATCH:
            raise ValueError("当前任务尚未进入继续创作阶段。")
        if task.story_plan is None:
            raise ValueError("当前任务缺少大纲，无法继续创作。")

        active_batch = get_active_batch(task_id)
        if active_batch is not None and active_batch.continue_request_id != request.continue_request_id:
            raise ValueError("当前已有活动批次，不能开启新的继续创作请求。")

        project = get_novel_project(task_id)
        if project is None:
            raise ValueError("当前任务缺少小说项目记录。")

        completed_count = int(project.completed_chapter_count or 0)
        remaining = max(int(project.planned_chapter_count or 0) - completed_count, 0)
        effective_count = min(int(request.requested_chapter_count), remaining)
        if effective_count <= 0:
            raise ValueError("当前任务没有可继续创作的剩余章节。")

        batch = create_batch(
            task_id,
            continue_request_id=request.continue_request_id,
            requested_count=int(request.requested_chapter_count),
            effective_count=effective_count,
            actual_start_chapter=completed_count + 1,
        )
        update_project_status(
            task_id,
            status=TaskStatus.DRAFTING.value,
            completed_chapter_count=completed_count,
            next_chapter_number=completed_count + 1,
            active_batch_no=batch.batch_no,
            active_continue_request_id=request.continue_request_id,
            current_generating_chapter_number=completed_count + 1,
        )

        task = self.store.mark_stage(
            task_id,
            status=TaskStatus.DRAFTING,
            stage="drafting",
            progress=max(task.progress, 60),
            message="正在生成章节批次。",
            event_type="draft.generating",
            unit_id=f"chapter-pair-{batch.batch_no}",
        )
        task = self._record_last_action(task_id, model_id=action_model_id, kind="continue")

        completed_chapters = self.get_current_chapters(task_id)[:completed_count]
        draft_seed_map = self._load_draft_seed_map(
            task_id,
            list(range(completed_count + 1, completed_count + effective_count + 1)),
        )
        try:
            chapter_pair = self.engine.generate_chapter_pair(
                spec=self._with_model_id(
                    task.normalized_spec or self._initial_state(task)["input_payload"],
                    action_model_id,
                ),
                story_plan=task.story_plan.model_dump(mode="json"),
                batch_index=completed_count,
                completed_chapters=completed_chapters,
                reference_text="\n\n".join(source.content for source in task.sources),
                model=action_model_id,
                requested_batch_size=effective_count,
                draft_seeds=draft_seed_map,
            )
            chapter_drafts = [ChapterDraft.model_validate(item) for item in chapter_pair]
            for chapter in chapter_drafts:
                self._write_chapter_file(
                    task_id,
                    chapter_number=chapter.number,
                    title=chapter.title,
                    summary=chapter.summary,
                    content=chapter.content,
                )
                upsert_outline_chapter_draft(
                    task_id,
                    chapter_number=chapter.number,
                    title=chapter.title,
                    summary=chapter.summary,
                    batch_no=batch.batch_no,
                    md_ref=f"tasklog/runs/{task_id}/chapters/{chapter.number:02d}.md",
                    json_ref=f"tasklog/runs/{task_id}/chapters/{chapter.number:02d}.json",
                    content=chapter.content,
                )

            from app.storage.db_repository import mark_batch_waiting_review

            mark_batch_waiting_review(task_id, batch.batch_no, persisted_count=len(chapter_drafts))
            update_project_status(
                task_id,
                status=TaskStatus.WAITING_CHAPTER_REVIEW.value,
                completed_chapter_count=completed_count,
                next_chapter_number=completed_count + 1,
                current_generating_chapter_number=None,
            )
            review = ReviewPayload(
                type="chapter_pair_review",
                version="v1",
                summary="请审核当前章节批次。",
                chapter_pair=chapter_drafts,
                batch_index=completed_count,
                completed_count=completed_count,
                total_chapters=int(project.planned_chapter_count or len(task.story_plan.chapter_plan)),
            )
            snapshot = self.store.set_waiting_chapter_review(task_id, review)
            return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)
        except Exception as exc:
            mark_batch_failed(task_id, batch.batch_no)
            update_project_status(
                task_id,
                status=TaskStatus.WAITING_MANUAL_ACTION.value,
                completed_chapter_count=completed_count,
                next_chapter_number=completed_count + 1,
                active_batch_no=None,
                active_continue_request_id="",
                blocked_from_status=TaskStatus.READY_FOR_BATCH.value,
                current_generating_chapter_number=self._current_generating_chapter_number_from_error(task_id, completed_count + 1),
            )
            snapshot = self.store.set_waiting_manual_action(
                task_id,
                f"继续创作失败：{exc}",
                payload={
                    "summary": "继续创作失败，但当前任务仍可恢复后重试。",
                    "display_level": "public",
                    "reason": "draft_batch_generation_failed",
                },
            )
            return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)

    def list_artifacts(self, task_id: str) -> list[ArtifactItem]:
        return self.store.get(task_id).artifacts

    def list_models(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        return self.model_catalog.list_models(force_refresh=force_refresh)

    def list_models_payload(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.model_catalog.list_models_payload(force_refresh=force_refresh)

    def update_default_model(self, model_id: str) -> dict[str, Any]:
        """更新默认模型，同时持久化到配置文件并更新运行时状态。"""
        result = self.model_catalog.update_default_model(model_id)
        # 同步到 StoryEngine，使其立即生效
        self.engine.set_runtime_default_model(model_id)
        return result

    def get_dashboard(self) -> DashboardResponse:
        tasks = sorted(self.store._tasks.values(), key=lambda item: item.updated_at, reverse=True)
        dead_statuses = {
            TaskStatus.WAITING_MANUAL_ACTION,
            TaskStatus.CANCELLED,
            TaskStatus.ASSEMBLING,
        }
        continue_statuses = {
            TaskStatus.CREATED,
            TaskStatus.SOURCES_INGESTED,
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.READY_FOR_BATCH,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
        }
        running_statuses = {
            TaskStatus.PLANNING,
            TaskStatus.DRAFTING,
        }
        running_tasks = [
            self._to_summary(task)
            for task in tasks
            if task.status in running_statuses and not self._is_stale_running_task(task)
        ]
        continue_tasks = [self._to_summary(task) for task in tasks if task.status in continue_statuses]
        failed_tasks = [self._to_summary(task) for task in tasks if task.status is TaskStatus.FAILED]
        failed_tasks.extend(self._to_summary(task) for task in tasks if task.status in dead_statuses)
        failed_tasks.extend(self._to_stale_run_summary(task) for task in tasks if self._is_stale_running_task(task))
        completed_tasks = [
            self._to_summary(task)
            for task in tasks
            if task.status is TaskStatus.COMPLETED and task.storage_state != "archive"
        ]
        return DashboardResponse(
            continue_tasks=continue_tasks,
            running_tasks=running_tasks,
            failed_tasks=failed_tasks,
            completed_tasks=completed_tasks,
            model_summary=self._model_summary(),
            system_summary={
                "active_runs": len(running_tasks),
                "archived_runs": sum(1 for task in tasks if task.storage_state == "archive"),
            },
            continue_total=len(continue_tasks),
            running_total=len(running_tasks),
            failed_total=len(failed_tasks),
            completed_total=len(completed_tasks),
        )

    def get_archive_list(self, page: int = 1, page_size: int = 10) -> ArchiveTaskListResponse:
        paginated_tasks, total = self.store.list_archive_tasks_paginated(page, page_size)
        items = [self._to_summary(task) for task in paginated_tasks]
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        return ArchiveTaskListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_archive_detail(self, task_id: str) -> ArchiveTaskDetailResponse:
        task = self.store.get(task_id)
        if task.storage_state != "archive":
            raise ValueError("当前任务尚未归档。")
        if task.draft_result is None:
            raise ValueError("归档任务缺少正文结果。")
        return ArchiveTaskDetailResponse(
            meta=self._to_summary(task),
            request_preview=self._request_preview(task),
            sources=task.sources,
            recent_events=task.events[-20:],
            result_summary=task.draft_result.summary,
            result_markdown=self._result_markdown(task.draft_result),
            result_md_ref=self._file_ref(task, "result.md"),
            chapter_index=[
                {
                    "number": chapter.number,
                    "title": chapter.title,
                    "summary": chapter.summary,
                    "md_ref": self._artifact_ref(task, f"chapter-{chapter.number:02d}.md"),
                    "content": chapter.content,
                }
                for chapter in task.draft_result.chapters
            ],
            artifact_index=[self._artifact_index_item(task, artifact) for artifact in task.artifacts],
            history_index=self._review_history(task),
        )

    def get_workspace(self, task_id: str) -> WorkspaceResponse:
        task = self.store.get(task_id)
        task, reconciliation = self._reconcile_task_for_read(task)
        if task.story_plan is not None and task.status in {
            TaskStatus.READY_FOR_BATCH,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
        }:
            self._ensure_novel_project_seeded(task)
        recent_events = task.events[-20:]
        recovery_contract = self._build_recovery_contract(task, reconciliation=reconciliation)
        return WorkspaceResponse(
            meta=self._to_summary(task),
            recent_events=recent_events,
            active_trace_summary=recent_events[-1].message if recent_events else None,
            available_tabs=self._workspace_tabs(task),
            **recovery_contract,
            request_preview=self._request_preview(task),
            context_status=self._load_context_status(task.id),
            response_cache_status=self._load_response_cache_status(task),
            novel_progress=self._novel_progress(task),
            sources=task.sources,
            supervisor_plan=task.supervisor_plan,
            agent_runs=task.agent_runs,
        )

    def get_supervisor_plan(self, task_id: str) -> dict[str, Any]:
        task = self.store.get(task_id)
        if task.supervisor_plan is None:
            raise ValueError("当前任务还没有 supervisor 规划结果。")
        payload = task.supervisor_plan.model_dump(mode="json")
        payload["agent_runs"] = [item.model_dump(mode="json") for item in task.agent_runs]
        return payload

    def get_review(self, task_id: str) -> ReviewResponse:
        task = self.store.get(task_id)
        task, reconciliation = self._reconcile_task_for_read(task)
        review = task.pending_review
        auto_review_trace = task.auto_review_trace or []
        recovery_contract = self._build_recovery_contract(task, reconciliation=reconciliation)
        if review is None:
            historical_review_type = self._historical_review_type(task)
            outline_ref = self._file_ref(task, "outline.md")
            if task.story_plan is None:
                if recovery_contract["allowed_actions"]:
                    return ReviewResponse(
                        meta=self._to_summary(task),
                        review_type=historical_review_type,
                        review_version="v1",
                        **recovery_contract,
                        summary="当前审核上下文不可用，请先执行恢复动作。",
                        risk_flags=[],
                        outline_markdown=None,
                        outline_md_ref=None,
                        revision_count=0,
                        review_history=self._review_history(task),
                        auto_review_trace=auto_review_trace,
                    )
                raise ValueError("当前任务还没有可审核的内容。")
            return ReviewResponse(
                meta=self._to_summary(task),
                review_type=historical_review_type,
                review_version="v1",
                **recovery_contract,
                summary="当前任务已有大纲，可查看历史审核结果。",
                risk_flags=[],
                outline_markdown=self._outline_markdown(task.story_plan) if historical_review_type != "verification_review" else None,
                outline_md_ref=outline_ref if historical_review_type != "verification_review" else None,
                revision_count=0,
                review_history=self._review_history(task),
                auto_review_trace=auto_review_trace,
            )

        review_type = review.type
        outline_ref = self._file_ref(task, "outline.md")

        if review_type == "chapter_pair_review":
            chapter_pair_data = review.chapter_pair or []
            chapter_index = [
                {
                    "number": ch.number,
                    "title": ch.title,
                    "summary": ch.summary,
                    "content": ch.content,
                }
                for ch in chapter_pair_data
            ]
            return ReviewResponse(
                meta=self._to_summary(task),
                review_type="chapter_pair_review",
                review_version=review.version,
                **recovery_contract,
                summary=review.summary,
                risk_flags=review.risk_flags,
                outline_markdown=self._outline_markdown(task.story_plan) if task.story_plan else None,
                outline_md_ref=outline_ref,
                review_history=self._review_history(task),
                auto_review_trace=auto_review_trace,
                chapter_pair=chapter_index,
                batch_index=review.batch_index,
                completed_count=review.completed_count,
                total_chapters=review.total_chapters,
                chapter_pair_revision_count=review.chapter_pair_revision_count,
            )

        elif review_type == "verification_review":
            return ReviewResponse(
                meta=self._to_summary(task),
                review_type="verification_review",
                review_version=review.version,
                **recovery_contract,
                summary=review.summary,
                risk_flags=review.risk_flags,
                outline_markdown=None,
                outline_md_ref=None,
                review_history=self._review_history(task),
                auto_review_trace=auto_review_trace,
                verification_report=review.verification_report,
                verification_revision_count=review.verification_revision_count,
            )

        # 默认：大纲审核
        return ReviewResponse(
            meta=self._to_summary(task),
            review_type="outline_review",
            review_version=review.version,
            **recovery_contract,
            summary=review.summary,
            risk_flags=review.risk_flags,
            outline_markdown=self._outline_markdown(task.story_plan) if task.story_plan else None,
            outline_md_ref=outline_ref,
            revision_count=review.revision_count,
            review_history=self._review_history(task),
            auto_review_trace=auto_review_trace,
        )

    def get_result(self, task_id: str) -> ResultResponse:
        task = self.store.get(task_id)
        if task.draft_result is None:
            raise ValueError("当前任务还没有可查看的结果。")
        return ResultResponse(
            meta=self._to_summary(task),
            result_summary=task.draft_result.summary,
            result_markdown=self._result_markdown(task.draft_result),
            result_md_ref=self._file_ref(task, "result.md"),
            chapter_index=[
                {
                    "number": chapter.number,
                    "title": chapter.title,
                    "summary": chapter.summary,
                    "md_ref": self._artifact_ref(task, f"chapter-{chapter.number:02d}.md"),
                    "content": chapter.content,
                }
                for chapter in task.draft_result.chapters
            ],
            artifact_index=[
                self._artifact_index_item(task, artifact)
                for artifact in task.artifacts
            ],
            history_index=self._review_history(task),
        )

    def read_file_text(self, task_id: str, relative_path: str) -> str:
        return self.store.read_text(task_id, relative_path)

    def subscribe_task_events(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        self.store.get(task_id)
        return self.store.subscribe(task_id)

    def unsubscribe_task_events(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.store.unsubscribe(task_id, queue)

    def build_sse_snapshot(self, task_id: str) -> dict[str, Any]:
        task = self.store.get(task_id)
        latest_event = task.events[-1].model_dump(mode="json") if task.events else None
        return {
            "task_id": task.id,
            "meta": self._to_summary(task).model_dump(mode="json"),
            "latest_event": latest_event,
        }

    def _initial_state(self, task: TaskRecord, action_model_id: str | None = None) -> dict[str, Any]:
        reference_text = "\n\n".join(source.content for source in task.sources)
        resolved_auto_review = self._resolve_task_auto_review(task)
        resolved_model_id = self._resolve_action_model_id(task, action_model_id)
        return {
            "task_id": task.id,
            "input_payload": {
                "mode": task.mode.value,
                "creative_mode": task.creative_mode.value if task.creative_mode else "",
                "novel_size": task.novel_size.value if task.novel_size else "",
                "chapter_word_min": task.chapter_word_min or task.input.target_words,
                "model_id": resolved_model_id,
                "prompt": task.input.prompt,
                "genre": task.input.genre,
                "style": task.input.style,
                "style_profile_id": task.input.style_profile_id,
                "target_words": task.input.target_words,
                "audience": task.input.audience,
                "banned": task.input.banned,
                "title_hint": task.input.title_hint,
            },
            "reference_text": reference_text,
            "source_assets": [source.model_dump(mode="json") for source in task.sources],
            "auto_review": resolved_auto_review,
            "auto_review_policy": task.auto_review_policy or dict(self.auto_review_policy),
        }

    def _resolve_task_auto_review(self, task: TaskRecord) -> bool:
        if task.auto_review is None:
            return self.auto_review
        return task.auto_review

    def _should_attempt_recovery(self, task: TaskRecord, *, force: bool = False) -> bool:
        if force:
            return True
        if task.status is TaskStatus.WAITING_OUTLINE_REVIEW:
            return task.pending_review is None or task.story_plan is None
        if task.status is TaskStatus.WAITING_MANUAL_ACTION:
            return task.pending_review is None or task.story_plan is None
        if task.status is TaskStatus.WAITING_CHAPTER_REVIEW:
            return task.pending_review is None or task.story_plan is None
        if task.status is TaskStatus.WAITING_VERIFICATION_REVIEW:
            return task.pending_review is None or task.story_plan is None
        if (
            task.status is TaskStatus.PLANNING
            and str(task.current_unit or "").startswith("outline")
            and task.pending_review is None
            and task.story_plan is None
        ):
            return True
        return False

    def _reconcile_pending_review_with_novel_project(self, task: TaskRecord) -> TaskRecord:
        if task.pending_review is None or task.pending_review.type != "chapter_pair_review":
            return task
        if task.status is not TaskStatus.WAITING_CHAPTER_REVIEW:
            return task
        if not self._has_novel_project(task.id):
            return task

        from app.storage.db_repository import get_active_batch, get_novel_project, update_project_status

        project = get_novel_project(task.id)
        if project is None:
            return task
        active_batch = get_active_batch(task.id)
        if active_batch is not None:
            return task

        planned = int(project.planned_chapter_count or 0)
        completed = int(project.completed_chapter_count or 0)
        should_move_to_verification = (
            project.status == TaskStatus.WAITING_VERIFICATION_REVIEW.value
            or (planned > 0 and completed >= planned)
        )
        if not should_move_to_verification:
            return task

        verification_review = ReviewPayload(
            type="verification_review",
            version="v1",
            summary="请审核全文一致性验证报告。",
            verification_report={"overall_score": 100, "issues": []},
        )
        record = self.store.set_waiting_verification_review(
            task.id,
            verification_review,
            task.auto_review_trace or None,
        )
        update_project_status(
            task.id,
            status=TaskStatus.WAITING_VERIFICATION_REVIEW.value,
            completed_chapter_count=completed,
            next_chapter_number=int(project.next_chapter_number or (completed + 1)),
            active_batch_no=None,
            active_continue_request_id="",
            current_generating_chapter_number=None,
        )
        self.store.append_event(
            task.id,
            stage="waiting_verification_review",
            message="检测到章节审核状态已过期，已自动校正到全文验证审核。",
            event_type="task.recovered",
            payload={
                "summary": "任务已自动校正到全文验证审核。",
                "display_level": "public",
                "source": "novel_project_state",
            },
        )
        return self.store.get(record.id)

    def _task_recovery_signature(self, task: TaskRecord) -> tuple[str, str, str, str, str, int]:
        pending_review = task.pending_review
        return (
            task.status.value,
            str(task.current_stage or ""),
            str(task.current_unit or ""),
            pending_review.type if pending_review is not None else "",
            pending_review.version if pending_review is not None else "",
            len(pending_review.chapter_pair or []) if pending_review is not None and pending_review.chapter_pair else 0,
        )

    def _mark_reconciliation(
        self,
        payload: dict[str, Any],
        *,
        kind: str,
        summary: str,
    ) -> None:
        if not payload["state_reconciled"]:
            payload["state_reconciled"] = True
            payload["reconciliation_kind"] = kind
            payload["reconciliation_summary"] = summary
            return
        if summary and summary not in payload["reconciliation_summary"]:
            payload["reconciliation_summary"] = f"{payload['reconciliation_summary']}；{summary}".strip("；")

    def _reconcile_task_for_read(self, task: TaskRecord) -> tuple[TaskRecord, dict[str, Any]]:
        reconciliation = {
            "state_reconciled": False,
            "reconciliation_kind": "",
            "reconciliation_summary": "",
        }
        current = task

        before = self._task_recovery_signature(current)
        current = self._reconcile_pending_review_with_novel_project(current)
        if self._task_recovery_signature(current) != before:
            self._mark_reconciliation(
                reconciliation,
                kind="stale_review_state",
                summary="已自动校正到最新稳定审核状态。",
            )

        return current, reconciliation

    def _recovery_blocked_reason(self, task: TaskRecord) -> str:
        event = next(
            (
                item
                for item in reversed(task.events)
                if item.event_type == "task.recovery.blocked" and isinstance(item.payload, dict)
            ),
            None,
        )
        if event is None:
            return ""
        reason = event.payload.get("reason")
        return str(reason) if reason else ""

    def _recovery_allowed_model_ids(self) -> list[str]:
        return [
            str(item.get("id"))
            for item in self.model_catalog.list_models()
            if isinstance(item, dict) and item.get("id")
        ]

    def _preview_recover_to_stable(self, task: TaskRecord) -> RecoveryPreview | None:
        allowed_model_ids = self._recovery_allowed_model_ids()
        default_model_id = self._resolve_task_model_id(task)
        last_action_model_id = task.last_action_model_id or ""

        target_stage = ""
        target_chapter_number: int | None = None
        target_chapter_numbers: list[int] = []
        target_batch_no: int | None = None
        reuse_existing_draft = False
        if task.status in {TaskStatus.PLANNING, TaskStatus.WAITING_OUTLINE_REVIEW} and self._can_recover_outline_review(task):
            target_stage = TaskStatus.WAITING_OUTLINE_REVIEW.value
        elif task.status is TaskStatus.WAITING_CHAPTER_REVIEW and task.pending_review is not None:
            if (
                task.pending_review.type == "chapter_pair_review"
                and self._has_novel_project(task.id)
            ):
                from app.storage.db_repository import get_active_batch, get_novel_project

                project = get_novel_project(task.id)
                active_batch = get_active_batch(task.id)
                planned = int(project.planned_chapter_count or 0) if project is not None else 0
                completed = int(project.completed_chapter_count or 0) if project is not None else 0
                if active_batch is None and (project is not None) and (
                    project.status == TaskStatus.WAITING_VERIFICATION_REVIEW.value
                    or (planned > 0 and completed >= planned)
                ):
                    target_stage = TaskStatus.WAITING_VERIFICATION_REVIEW.value
                else:
                    target_stage = TaskStatus.WAITING_CHAPTER_REVIEW.value
                    target_chapter_numbers = [
                        int(ch.number if isinstance(ch, ChapterDraft) else ch.get("number"))
                        for ch in (task.pending_review.chapter_pair or [])
                        if (isinstance(ch, ChapterDraft) and ch.number) or (isinstance(ch, dict) and ch.get("number"))
                    ]
                    target_chapter_number = target_chapter_numbers[-1] if target_chapter_numbers else None
            elif self._can_recover_chapter_review(task, force=False):
                target_stage = TaskStatus.WAITING_CHAPTER_REVIEW.value
        elif task.status is TaskStatus.WAITING_VERIFICATION_REVIEW and self._can_recover_verification_review(task, force=False):
            target_stage = TaskStatus.WAITING_VERIFICATION_REVIEW.value
        elif task.status is TaskStatus.WAITING_MANUAL_ACTION:
            if self._has_novel_project(task.id):
                from app.storage.db_repository import get_active_batch, get_novel_project

                project = get_novel_project(task.id)
                blocked_status = str(project.blocked_from_status or "") if project is not None else ""
                active_batch = get_active_batch(task.id) if project is not None else None
                if blocked_status == TaskStatus.READY_FOR_BATCH.value and project is not None:
                    target_stage = "waiting_chapter_generation"
                    target_batch_no = int(active_batch.batch_no) if active_batch is not None else None
                    if active_batch is not None:
                        target_chapter_numbers = list(
                            range(
                                int(active_batch.actual_start_chapter),
                                int(active_batch.expected_end_chapter) + 1,
                            )
                        )
                    target_chapter_number = int(
                        project.current_generating_chapter_number
                        or project.next_chapter_number
                        or (target_chapter_numbers[0] if target_chapter_numbers else 0)
                    ) or None
                    reuse_existing_draft = bool(
                        target_chapter_number and self._load_chapter_draft_from_history(task.id, target_chapter_number)
                    )
                elif blocked_status in _STAGE_LABELS:
                    target_stage = blocked_status
            if not target_stage:
                if task.pending_review is not None and task.pending_review.type == "verification_review":
                    target_stage = TaskStatus.WAITING_VERIFICATION_REVIEW.value
                elif task.pending_review is not None and task.pending_review.type == "chapter_pair_review":
                    target_stage = TaskStatus.WAITING_CHAPTER_REVIEW.value
                    target_chapter_numbers = [
                        int(ch.number if isinstance(ch, ChapterDraft) else ch.get("number"))
                        for ch in (task.pending_review.chapter_pair or [])
                        if (isinstance(ch, ChapterDraft) and ch.number) or (isinstance(ch, dict) and ch.get("number"))
                    ]
                    target_chapter_number = target_chapter_numbers[-1] if target_chapter_numbers else None
                elif self._load_story_plan_from_history(task.id) is not None:
                    target_stage = TaskStatus.WAITING_OUTLINE_REVIEW.value

        if not target_stage:
            return None

        target_stage_label = _STAGE_LABELS.get(target_stage, target_stage)
        if target_stage == "waiting_chapter_generation":
            if target_chapter_numbers:
                if len(target_chapter_numbers) == 1:
                    target_stage_label = f"恢复到第 {target_chapter_numbers[0]} 章待生成"
                else:
                    target_stage_label = (
                        f"恢复到第 {target_chapter_numbers[0]}-{target_chapter_numbers[-1]} 章批次待生成"
                    )
            elif target_chapter_number is not None:
                target_stage_label = f"恢复到第 {target_chapter_number} 章待生成"
        elif target_stage == TaskStatus.WAITING_CHAPTER_REVIEW.value and target_chapter_numbers:
            if len(target_chapter_numbers) == 1:
                target_stage_label = f"恢复到第 {target_chapter_numbers[0]} 章待审核"
            else:
                target_stage_label = (
                    f"恢复到第 {target_chapter_numbers[0]}-{target_chapter_numbers[-1]} 章待审核"
                )

        return RecoveryPreview(
            target_stage=target_stage,
            target_stage_label=target_stage_label,
            target_chapter_number=target_chapter_number,
            target_chapter_numbers=target_chapter_numbers,
            target_batch_no=target_batch_no,
            reuse_existing_draft=reuse_existing_draft,
            will_resume_generation=target_stage == "waiting_chapter_generation",
            default_model_id=default_model_id,
            last_action_model_id=last_action_model_id,
            allowed_model_ids=allowed_model_ids,
            fallback_actions=["restart_from_input"],
        )

    def _preview_restart_from_input(self, task: TaskRecord) -> RecoveryPreview | None:
        can_restart = task.status in {TaskStatus.WAITING_MANUAL_ACTION, TaskStatus.FAILED}
        if (
            task.status is TaskStatus.PLANNING
            and str(task.current_unit or "").startswith("outline")
            and task.story_plan is None
            and task.pending_review is None
        ):
            can_restart = True
        if not can_restart:
            return None
        if not str(task.input.prompt or "").strip():
            return None
        return RecoveryPreview(
            target_stage=TaskStatus.PLANNING.value,
            target_stage_label=_STAGE_LABELS[TaskStatus.PLANNING.value],
            will_resume_generation=True,
            default_model_id=self._resolve_task_model_id(task),
            last_action_model_id=task.last_action_model_id or "",
            allowed_model_ids=self._recovery_allowed_model_ids(),
            fallback_actions=[],
        )

    def _build_recovery_contract(
        self,
        task: TaskRecord,
        *,
        reconciliation: dict[str, Any],
    ) -> dict[str, Any]:
        stable_preview = self._preview_recover_to_stable(task)
        restart_preview = self._preview_restart_from_input(task)

        stable_option = RecoveryOption(
            action="recover_to_stable",
            label="回填最近稳定阶段",
            kind="primary",
            available=stable_preview is not None,
            reason_unavailable="" if stable_preview is not None else "当前没有可回填的稳定阶段",
            preview=stable_preview,
        )
        restart_option = RecoveryOption(
            action="restart_from_input",
            label="按原始输入重新开始",
            kind="secondary",
            available=restart_preview is not None,
            reason_unavailable="" if restart_preview is not None else "当前不支持按原始输入重新开始",
            preview=restart_preview,
        )
        recovery_options = [stable_option, restart_option]
        allowed_actions = [item.action for item in recovery_options if item.available]
        recommended_action = ""
        if stable_option.available:
            recommended_action = stable_option.action
        elif restart_option.available:
            recommended_action = restart_option.action

        return {
            "allowed_actions": allowed_actions,
            "recommended_action": recommended_action,
            "blocked_reason": self._recovery_blocked_reason(task),
            "state_reconciled": bool(reconciliation.get("state_reconciled")),
            "reconciliation_kind": str(reconciliation.get("reconciliation_kind") or ""),
            "reconciliation_summary": str(reconciliation.get("reconciliation_summary") or ""),
            "recovery_options": recovery_options,
        }

    def _recover_task_from_stable_state(self, task: TaskRecord, *, force: bool = False) -> TaskRecord | None:
        novel_recovered = self._recover_novel_project_state(task)
        if novel_recovered is not None:
            return novel_recovered
        if self._can_recover_outline_review(task):
            return self._recover_outline_review(task)
        if self._can_recover_chapter_review(task, force=force):
            return self._recover_chapter_review(task)
        if self._can_recover_verification_review(task, force=force):
            return self._recover_verification_review(task)
        return None

    def _recover_novel_project_state(self, task: TaskRecord) -> TaskRecord | None:
        from app.storage.db_repository import (
            get_active_batch,
            get_novel_project,
            list_outline_chapters,
            mark_outline_chapter_manual_action,
            read_file_content_hash,
            update_project_status,
            upsert_outline_chapter_draft,
        )

        project = get_novel_project(task.id)
        if project is None:
            return None

        chapters = list_outline_chapters(task.id)
        for chapter in chapters:
            chapter_path = self._chapter_storage_path(task.id, int(chapter.chapter_number))
            if chapter_path.exists():
                current_hash, current_size = read_file_content_hash(chapter_path)
                if chapter.content_hash and chapter.file_size and (
                    chapter.content_hash != current_hash or int(chapter.file_size) != int(current_size)
                ):
                    mark_outline_chapter_manual_action(task.id, int(chapter.chapter_number), "checksum_mismatch")
                    update_project_status(
                        task.id,
                        status=TaskStatus.WAITING_MANUAL_ACTION.value,
                        blocked_from_status=project.status,
                        current_generating_chapter_number=int(chapter.chapter_number),
                    )
                    return self.store.set_waiting_manual_action(
                        task.id,
                        f"章节文件校验失败：第 {chapter.chapter_number} 章。",
                    )
                if (not chapter.md_ref) or (not chapter.json_ref) or (not chapter.content_hash) or int(chapter.file_size or 0) <= 0:
                    chapter_data = self._load_chapter_file_payload(task.id, int(chapter.chapter_number))
                    upsert_outline_chapter_draft(
                        task.id,
                        chapter_number=int(chapter.chapter_number),
                        title=str(chapter_data.get("title") or chapter.title or f"第{chapter.chapter_number}章"),
                        summary=str(chapter_data.get("summary") or chapter.summary or ""),
                        batch_no=int(chapter.batch_no or 0),
                        md_ref=f"tasklog/runs/{task.id}/chapters/{int(chapter.chapter_number):02d}.json",
                        json_ref=f"tasklog/runs/{task.id}/chapters/{int(chapter.chapter_number):02d}.json",
                        content=str(chapter_data.get("content") or ""),
                    )
            elif chapter.status in {"approved", "rejected", "drafted"} or chapter.md_ref:
                mark_outline_chapter_manual_action(task.id, int(chapter.chapter_number), "file_missing")
                update_project_status(
                    task.id,
                    status=TaskStatus.WAITING_MANUAL_ACTION.value,
                    blocked_from_status=project.status,
                    current_generating_chapter_number=int(chapter.chapter_number),
                )
                return self.store.set_waiting_manual_action(
                    task.id,
                    f"章节文件缺失：第 {chapter.chapter_number} 章。",
                )

        batch = get_active_batch(task.id)
        if batch is not None:
            expected_end = int(batch.actual_start_chapter) + int(batch.effective_count) - 1
            actual_end = None
            if int(batch.persisted_count or 0) > 0:
                actual_end = int(batch.actual_start_chapter) + int(batch.persisted_count) - 1
            if (
                int(batch.expected_end_chapter or 0) != expected_end
                or (batch.actual_end_chapter != actual_end)
                or int(batch.persisted_count or 0) < 0
                or int(batch.persisted_count or 0) > int(batch.effective_count or 0)
            ):
                update_project_status(
                    task.id,
                    status=TaskStatus.WAITING_MANUAL_ACTION.value,
                    blocked_from_status=project.status,
                    current_generating_chapter_number=int(batch.actual_start_chapter),
                )
                return self.store.set_waiting_manual_action(
                    task.id,
                    "章节批次一致性校验失败，已转入待人工处理。",
                )

        if task.status is TaskStatus.WAITING_MANUAL_ACTION and project.blocked_from_status:
            blocked_status = project.blocked_from_status
            if blocked_status == TaskStatus.WAITING_CHAPTER_REVIEW.value and task.pending_review is not None:
                snapshot = self.store.set_waiting_chapter_review(task.id, task.pending_review)
                update_project_status(
                    task.id,
                    status=TaskStatus.WAITING_CHAPTER_REVIEW.value,
                    blocked_from_status="",
                    active_batch_no=project.active_batch_no,
                    active_continue_request_id=project.active_continue_request_id,
                    current_generating_chapter_number=None,
                )
                return snapshot
            if blocked_status == TaskStatus.READY_FOR_BATCH.value and task.story_plan is not None:
                snapshot = self.store.set_ready_for_batch(task.id, task.story_plan)
                update_project_status(
                    task.id,
                    status=TaskStatus.READY_FOR_BATCH.value,
                    active_batch_no=None,
                    active_continue_request_id="",
                    blocked_from_status="",
                    current_generating_chapter_number=(
                        int(project.current_generating_chapter_number)
                        if project.current_generating_chapter_number
                        else None
                    ),
                )
                return snapshot

        return None

    def _retry_task_from_original_input(self, task: TaskRecord, action_model_id: str | None = None) -> TaskRecord | None:
        if task.status not in {TaskStatus.WAITING_MANUAL_ACTION, TaskStatus.FAILED}:
            return None
        if task.story_plan is not None or task.pending_review is not None:
            return None
        if not str(task.input.prompt or "").strip():
            return None

        snapshot = self.store.mark_stage(
            task.id,
            status=TaskStatus.PLANNING,
            stage="planning",
            progress=max(task.progress, 5),
            message="正在根据原始输入重新尝试生成大纲。",
            event_type="task.recovered",
            payload={
                "summary": "任务已重新进入大纲生成阶段。",
                "display_level": "public",
                "source": "raw_input_retry",
            },
        )
        snapshot.error_message = None
        snapshot = self.store.save(snapshot)
        snapshot = self._record_last_action(task.id, model_id=action_model_id or self._resolve_task_model_id(task), kind="recover")
        self._start_background(task.id, self._run_task_sync, task.id, action_model_id)
        return snapshot

    def _can_recover_outline_review(self, task: TaskRecord) -> bool:
        if task.status is TaskStatus.WAITING_OUTLINE_REVIEW:
            return task.pending_review is None or task.story_plan is None
        if task.status is TaskStatus.WAITING_MANUAL_ACTION:
            return task.pending_review is None and task.story_plan is None
        return (
            task.status is TaskStatus.PLANNING
            and str(task.current_unit or "").startswith("outline")
            and task.pending_review is None
            and task.story_plan is None
        )

    def _has_novel_project(self, task_id: str) -> bool:
        from app.storage.db_repository import get_novel_project

        return get_novel_project(task_id) is not None

    def _ensure_novel_project_seeded(self, task: TaskRecord) -> None:
        if task.story_plan is None:
            return
        from app.storage.db_repository import get_novel_project, seed_outline_chapters, upsert_novel_project

        if get_novel_project(task.id) is None:
            upsert_novel_project(task, task.story_plan)
        seed_outline_chapters(task.id, task.story_plan)

    def _can_recover_chapter_review(self, task: TaskRecord, *, force: bool = False) -> bool:
        if task.pending_review is None or task.pending_review.type != "chapter_pair_review":
            return False
        return (
            task.status in {TaskStatus.WAITING_CHAPTER_REVIEW, TaskStatus.WAITING_MANUAL_ACTION}
            and (
                task.story_plan is None
                or force
                or self._chapter_pair_payload_is_dirty(task)
            )
        )

    def _can_recover_verification_review(self, task: TaskRecord, *, force: bool = False) -> bool:
        return (
            task.status in {TaskStatus.WAITING_VERIFICATION_REVIEW, TaskStatus.WAITING_MANUAL_ACTION}
            and task.pending_review is not None
            and task.pending_review.type == "verification_review"
            and (task.story_plan is None or force)
        )

    def _recover_outline_review(self, task: TaskRecord) -> TaskRecord | None:
        story_plan = self._load_story_plan_from_history(task.id)
        if story_plan is None:
            return None
        review = ReviewPayload(
            type="outline_review",
            version="v1",
            summary="请确认大纲是否可以进入正文起草。",
            story_plan=story_plan,
            risk_flags=[
                "demo 版本，大纲以稳定展示工作流为优先。",
                "若上传了参考小说，系统只提炼风味和设定气质，不直接复刻原文。",
            ],
            revision_count=self._outline_revision_count_from_history(task.id),
        )
        record = self.store.set_waiting_review(
            task.id,
            review,
            story_plan,
            task.auto_review_trace or None,
        )
        self.store.append_event(
            task.id,
            stage="waiting_outline_review",
            message="已从历史大纲快照恢复到待大纲审核。",
            event_type="task.recovered",
            payload={
                "summary": "任务已恢复到待大纲审核。",
                "display_level": "public",
                "source": "outline_history",
            },
        )
        return self.store.save(self.store.get(record.id))

    def _recover_chapter_review(self, task: TaskRecord) -> TaskRecord | None:
        story_plan = task.story_plan or self._load_story_plan_from_history(task.id)
        if story_plan is None or task.pending_review is None:
            return None
        rebuilt_chapter_pair = self._rebuild_chapter_pair_from_history(task, story_plan, task.pending_review)
        if rebuilt_chapter_pair:
            task.pending_review.chapter_pair = rebuilt_chapter_pair
        current_task = self.store.get(task.id)
        current_task.story_plan = story_plan
        current_task.pending_review = task.pending_review
        self.store.save(current_task)
        record = self.store.set_waiting_chapter_review(
            task.id,
            task.pending_review,
            task.auto_review_trace or None,
        )
        self.store.append_event(
            task.id,
            stage="waiting_chapter_review",
            message="已从历史大纲快照恢复章节审核所需状态。",
            event_type="task.recovered",
            payload={
                "summary": "任务已恢复到待章节审核。",
                "display_level": "public",
                "source": "outline_history",
            },
        )
        return self.store.save(self.store.get(record.id))

    def _recover_verification_review(self, task: TaskRecord) -> TaskRecord | None:
        story_plan = task.story_plan or self._load_story_plan_from_history(task.id)
        if story_plan is None or task.pending_review is None:
            return None
        current_task = self.store.get(task.id)
        current_task.story_plan = story_plan
        self.store.save(current_task)
        record = self.store.set_waiting_verification_review(
            task.id,
            task.pending_review,
            task.auto_review_trace or None,
        )
        self.store.append_event(
            task.id,
            stage="waiting_verification_review",
            message="已从历史快照恢复验证审核所需状态。",
            event_type="task.recovered",
            payload={
                "summary": "任务已恢复到待验证审核。",
                "display_level": "public",
                "source": "verification_snapshot",
            },
        )
        return self.store.save(self.store.get(record.id))

    def _load_story_plan_from_history(self, task_id: str) -> StoryPlan | None:
        for snapshot_name in ("outline-revision-history", "outline-history"):
            history = self._load_context_snapshot(task_id, stage="planning", snapshot_name=snapshot_name)
            if not isinstance(history, dict):
                continue
            messages = history.get("messages") or []
            for message in reversed(messages):
                if message.get("role") != "assistant":
                    continue
                content = str(message.get("content") or "").strip()
                if not content:
                    continue
                try:
                    return StoryPlan.model_validate_json(content)
                except Exception:
                    try:
                        return StoryPlan.model_validate(json.loads(content))
                    except Exception:
                        continue
        return None

    def _outline_revision_count_from_history(self, task_id: str) -> int:
        history = self._load_context_snapshot(task_id, stage="planning", snapshot_name="outline-revision-history")
        if not isinstance(history, dict):
            return 0
        messages = history.get("messages") or []
        return 1 if any(item.get("role") == "assistant" for item in messages if isinstance(item, dict)) else 0

    def _chapter_pair_payload_is_dirty(self, task: TaskRecord) -> bool:
        review = task.pending_review
        if review is None or review.type != "chapter_pair_review":
            return False
        story_plan = task.story_plan
        if story_plan is None:
            return False
        total_chapters = review.total_chapters or len(story_plan.chapter_plan)
        completed_count = review.completed_count or 0
        mode = str((task.normalized_spec or {}).get("mode") or task.mode.value)
        expected = 2
        if mode == TaskMode.STYLE_REMIX.value and total_chapters > 2:
            expected = 2 if completed_count == 0 else 1
        current = len(review.chapter_pair or [])
        return current != expected

    def _rebuild_chapter_pair_from_history(
        self,
        task: TaskRecord,
        story_plan: StoryPlan,
        review: ReviewPayload,
    ) -> list[ChapterDraft] | None:
        batch_index = review.batch_index or 0
        completed_count = review.completed_count or 0
        total_chapters = review.total_chapters or len(story_plan.chapter_plan)
        mode = str((task.normalized_spec or {}).get("mode") or task.mode.value)
        batch_size = 2
        if mode == TaskMode.STYLE_REMIX.value and total_chapters > 2:
            batch_size = 2 if completed_count == 0 else 1

        rebuilt: list[ChapterDraft] = []
        for chapter_number in range(batch_index + 1, min(batch_index + batch_size, total_chapters) + 1):
            history = self._load_context_snapshot(
                task.id,
                stage="drafting",
                snapshot_name=f"chapter-{chapter_number:02d}-history",
            )
            messages = history.get("messages") if isinstance(history, dict) else []
            if not isinstance(messages, list):
                continue
            for message in reversed(messages):
                if message.get("role") != "assistant":
                    continue
                content = str(message.get("content") or "").strip()
                if not content:
                    continue
                try:
                    payload = ChapterDraft.model_validate_json(content)
                except Exception:
                    continue
                rebuilt.append(payload)
                break
        return rebuilt or None

    def _config(self, task_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": task_id}, "recursion_limit": 100}

    def _graph_state_values(self, task_id: str) -> dict[str, Any]:
        try:
            snapshot = self.graph.get_state(self._config(task_id))
        except Exception:
            return {}
        return snapshot.values if snapshot and hasattr(snapshot, "values") and isinstance(snapshot.values, dict) else {}

    def _load_context_snapshot(self, task_id: str, *, stage: str, snapshot_name: str) -> dict[str, Any] | None:
        relative_path = f"context/{stage}/{snapshot_name}.json"
        try:
            return self.store.read_json(task_id, relative_path)
        except Exception:
            return None

    def _load_completed_chapters_for_resume(self, task_id: str, completed_count: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for number in range(1, completed_count + 1):
            relative_path = f"context/drafting/chapter-{number:02d}-history.json"
            try:
                history = self.store.read_json(task_id, relative_path)
            except Exception:
                continue
            messages = history.get("messages") if isinstance(history, dict) else []
            if not isinstance(messages, list) or not messages:
                continue
            assistant_content = str(messages[-1].get("content") or "")
            if not assistant_content.strip():
                continue
            try:
                payload = ChapterDraft.model_validate_json(assistant_content)
            except Exception:
                continue
            items.append(payload.model_dump(mode="json"))
        return items

    def _load_chapter_draft_from_history(self, task_id: str, chapter_number: int) -> dict[str, Any] | None:
        relative_path = f"context/drafting/chapter-{chapter_number:02d}-history.json"
        try:
            history = self.store.read_json(task_id, relative_path)
        except Exception:
            return None
        messages = history.get("messages") if isinstance(history, dict) else []
        if not isinstance(messages, list):
            return None
        for message in reversed(messages):
            if message.get("role") != "assistant":
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            try:
                payload = ChapterDraft.model_validate_json(content)
            except Exception:
                continue
            return payload.model_dump(mode="json")
        return None

    def _load_draft_seed_map(self, task_id: str, chapter_numbers: list[int]) -> dict[int, str]:
        draft_seed_map: dict[int, str] = {}
        for chapter_number in chapter_numbers:
            payload = self._load_chapter_draft_from_history(task_id, chapter_number)
            if payload is None:
                continue
            content = str(payload.get("content") or "").strip()
            if content:
                draft_seed_map[int(chapter_number)] = content
        return draft_seed_map

    def _current_generating_chapter_number_from_error(self, task_id: str, default_value: int) -> int:
        task = self.store.get(task_id)
        for event in reversed(task.events):
            payload = event.payload if isinstance(event.payload, dict) else {}
            chapter_number = payload.get("chapter_number")
            if (
                isinstance(chapter_number, int)
                and chapter_number > 0
                and chapter_number >= int(default_value)
            ):
                return chapter_number
        return int(default_value)

    def _resume_seed_state(self, task: TaskRecord, action_model_id: str | None = None) -> tuple[dict[str, Any], str] | None:
        if task.pending_review is None:
            return None
        seed = self._initial_state(task, action_model_id)
        resolved_model_id = str((seed.get("input_payload") or {}).get("model_id") or self._resolve_task_model_id(task))
        if task.normalized_spec:
            seed["normalized_spec"] = self._with_model_id(task.normalized_spec, resolved_model_id)
        if task.story_plan is not None:
            seed["story_plan"] = task.story_plan.model_dump(mode="json")

        review = task.pending_review
        if review.type == "outline_review":
            outline_snapshot = self._load_context_snapshot(task.id, stage="planning", snapshot_name="outline-context")
            if isinstance(outline_snapshot, dict):
                seed["outline_context_snapshot"] = outline_snapshot
                packet = outline_snapshot.get("packet")
                if isinstance(packet, dict):
                    seed["outline_context_packet"] = packet
            elif task.story_plan is not None:
                state_for_refs = {
                    "reference_text": seed.get("reference_text", ""),
                    "source_assets": seed.get("source_assets", []),
                }
                references = _build_references(state_for_refs)
                if self.rag_service is not None:
                    references.extend(
                        self.rag_service.build_reference_materials(
                            self.rag_service.search_for_story_outline(spec=seed.get("normalized_spec") or {}),
                            prefix="大纲RAG",
                        )
                    )
                snapshot = self.context_manager.build_snapshot(
                    task_id=task.id,
                    stage="planning",
                    instruction=_outline_instruction(seed.get("normalized_spec") or {}),
                    model_profile=_resolve_model_profile(self.model_catalog, resolved_model_id),
                    references=references,
                    memory_items=[],
                )
                seed["outline_context_packet"] = snapshot.packet.model_dump(mode="json")
                seed["outline_context_snapshot"] = snapshot.model_dump(mode="json")
            seed["outline_revision_count"] = review.revision_count
            return seed, "plan_story"

        if review.type == "chapter_pair_review":
            completed_count = review.completed_count or 0
            completed_chapters = self._load_completed_chapters_for_resume(task.id, completed_count)
            chapter_pair = [item.model_dump(mode="json") for item in (review.chapter_pair or [])]
            seed.update(
                {
                    "batch_index": review.batch_index or 0,
                    "total_chapters": review.total_chapters or (len(task.story_plan.chapter_plan) if task.story_plan else 0),
                    "completed_count": completed_count,
                    "completed_chapters": completed_chapters,
                    "current_chapter_pair": chapter_pair,
                    "chapter_pair_revision_count": review.chapter_pair_revision_count,
                }
            )
            references = _build_references(
                {
                    "reference_text": seed.get("reference_text", ""),
                    "source_assets": seed.get("source_assets", []),
                }
            )
            if self.rag_service is not None:
                references.extend(
                    self.rag_service.build_reference_materials(
                        self.rag_service.search_for_story_chapter(
                            spec=seed.get("normalized_spec") or {},
                            story_plan=seed.get("story_plan"),
                            batch_index=review.batch_index or 0,
                            completed_chapters=completed_chapters,
                        ),
                        prefix="章节RAG",
                    )
                )
            snapshot = self.context_manager.build_snapshot(
                task_id=task.id,
                stage="drafting",
                instruction=_chapter_pair_instruction(seed.get("normalized_spec") or {}, seed.get("story_plan")),
                model_profile=_resolve_model_profile(self.model_catalog, resolved_model_id),
                references=references,
                memory_items=[
                    *(f"世界观：{note}" for note in ((seed.get("story_plan") or {}).get("world_notes") or [])),
                    *(f"人物：{note}" for note in ((seed.get("story_plan") or {}).get("character_notes") or [])),
                    *(
                        f"章节计划：第{chapter.get('number')}章 {chapter.get('title')} - {chapter.get('goal')}"
                        for chapter in (((seed.get("story_plan") or {}).get("chapter_plan")) or [])
                        if isinstance(chapter, dict)
                    ),
                ],
            )
            seed["chapter_pair_context_packet"] = snapshot.packet.model_dump(mode="json")
            return seed, "draft_chapter_pair"

        if review.type == "verification_review":
            # 恢复 story_plan：优先从 task.story_plan，否则从 outline-history.json
            if task.story_plan:
                total = len(task.story_plan.chapter_plan)
            else:
                total = 0
                outline_history = self._load_context_snapshot(task.id, stage="planning", snapshot_name="outline-history")
                if isinstance(outline_history, dict):
                    messages = outline_history.get("messages") or []
                    for msg in reversed(messages):
                        if msg.get("role") == "assistant":
                            content = str(msg.get("content", "")).strip()
                            if content:
                                try:
                                    plan_data = StoryPlan.model_validate_json(content)
                                    seed["story_plan"] = plan_data.model_dump(mode="json")
                                    total = len(plan_data.chapter_plan)
                                except Exception:
                                    try:
                                        import json as _json
                                        plan_data = _json.loads(content)
                                        seed["story_plan"] = plan_data
                                        total = len(plan_data.get("chapter_plan", []))
                                    except Exception:
                                        pass
                                break
            seed.update(
                {
                    "completed_chapters": self._load_completed_chapters_for_resume(task.id, total),
                    "verification_report": review.verification_report or {},
                    "verification_revision_count": review.verification_revision_count,
                }
            )
            return seed, "verify_full_story"

        return None

    def _rehydrate_resume_state_if_needed(self, task: TaskRecord, action_model_id: str | None = None) -> None:
        values = self._graph_state_values(task.id)
        if not hasattr(self.graph, "update_state"):
            return
        resolved_model_id = self._resolve_action_model_id(task, action_model_id)
        patch: dict[str, Any] = {}
        input_payload = values.get("input_payload")
        if isinstance(input_payload, dict) and str(input_payload.get("model_id") or "").strip() != resolved_model_id:
            patch["input_payload"] = self._with_model_id(input_payload, resolved_model_id)
        normalized_spec = values.get("normalized_spec")
        if isinstance(normalized_spec, dict) and str(normalized_spec.get("model_id") or "").strip() != resolved_model_id:
            patch["normalized_spec"] = self._with_model_id(normalized_spec, resolved_model_id)
        if patch:
            self.graph.update_state(self._config(task.id), patch)
        if values.get("input_payload"):
            return
        seeded = self._resume_seed_state(task, action_model_id)
        if seeded is None:
            return
        seed_values, as_node = seeded
        self.graph.update_state(self._config(task.id), seed_values, as_node=as_node)

    def _persistable_normalized_spec(self, task: TaskRecord, normalized_spec: dict[str, Any]) -> dict[str, Any]:
        return self._with_model_id(normalized_spec, self._resolve_task_model_id(task))

    def _sync_result(
        self,
        task_id: str,
        result: dict[str, Any],
        review_comment: str = "",
    ) -> TaskRecord:
        snapshot = self.graph.get_state(self._config(task_id))
        values = snapshot.values if snapshot and hasattr(snapshot, "values") else {}
        normalized_spec = values.get("normalized_spec")
        if normalized_spec:
            current_task = self.store.get(task_id)
            persisted_spec = self._persistable_normalized_spec(current_task, normalized_spec)
            if current_task.normalized_spec != persisted_spec:
                self.store.update_normalized_spec(task_id, persisted_spec)
                self._emit_trace_summary(
                    task_id,
                    kind="spec",
                    title="创作要求已标准化",
                    detail="已整理用户诉求、风格、字数和参考材料，开始生成大纲。",
                )

        outline_context_snapshot = values.get("outline_context_snapshot")
        if isinstance(outline_context_snapshot, dict):
            self.store.write_context_snapshot(
                task_id,
                stage="planning",
                snapshot_name="outline-context",
                payload=outline_context_snapshot,
            )
            self._emit_trace_summary(
                task_id,
                kind="context",
                title="大纲上下文已装配",
                detail="已完成 planning 阶段上下文预算、压缩与缓存判定。",
                unit_id="outline-context",
            )

        if "__interrupt__" in result:
            story_plan_data = values.get("story_plan")
            review = ReviewPayload.model_validate(self._extract_interrupt_payload(result))
            review_type = review.type
            auto_review_trace = values.get("auto_review_trace") or []

            if review_type == "outline_review":
                if not story_plan_data:
                    raise RuntimeError("工作流进入审核前未生成可用大纲。")
                story_plan = StoryPlan.model_validate(story_plan_data)
                record = self.store.set_waiting_review(task_id, review, story_plan, auto_review_trace)
                record = self._safe_sync_supervisor_plan(task_id, fallback=record)
                self._safe_emit_trace_summary(
                    task_id,
                    kind="outline",
                    title="大纲已生成",
                    detail="已完成故事骨架与章节规划，等待人工审核。",
                    unit_id="outline",
                )
                return record

            elif review_type == "chapter_pair_review":
                current_chapter_pair = values.get("current_chapter_pair") or []
                review.chapter_pair = [ChapterDraft.model_validate(ch) for ch in current_chapter_pair]
                batch_index = values.get("batch_index", 0)
                completed = values.get("completed_chapters") or []
                chapter_plan = (story_plan_data or {}).get("chapter_plan") or []
                batch_end = min(batch_index + len(current_chapter_pair), len(chapter_plan))
                review.batch_index = batch_index
                review.completed_count = len(completed)
                review.total_chapters = len(chapter_plan)
                record = self.store.set_waiting_chapter_review(task_id, review, auto_review_trace)
                record = self._safe_sync_supervisor_plan(task_id, fallback=record)
                self._safe_emit_trace_summary(
                    task_id,
                    kind="chapter",
                    title="章节批次已生成",
                    detail=(
                        f"第 {batch_index + 1} 章已起草，等待审核。"
                        if batch_end <= batch_index + 1
                        else f"第 {batch_index + 1}-{batch_end} 章已起草，等待审核。"
                    ),
                    unit_id=f"chapter-pair-{batch_index}",
                )
                return record

            elif review_type == "verification_review":
                verification_report = values.get("verification_report") or {}
                review.verification_report = verification_report
                record = self.store.set_waiting_verification_review(task_id, review, auto_review_trace)
                record = self._safe_sync_supervisor_plan(task_id, fallback=record)
                self._safe_emit_trace_summary(
                    task_id,
                    kind="verification",
                    title="全文验证完成",
                    detail=f"总分 {verification_report.get('overall_score', '?')}，发现 {len(verification_report.get('issues') or [])} 个问题。",
                    unit_id="verification",
                )
                return record

            # 兜底：未知类型按大纲审核处理
            if not story_plan_data:
                raise RuntimeError("工作流进入审核前未生成可用大纲。")
            story_plan = StoryPlan.model_validate(story_plan_data)
            record = self.store.set_waiting_review(task_id, review, story_plan, auto_review_trace)
            return self._safe_sync_supervisor_plan(task_id, fallback=record)

        # 工作流正常结束
        story_plan_data = values.get("story_plan")
        if not story_plan_data:
            raise RuntimeError("工作流结束后未找到大纲结果。")
        story_plan = StoryPlan.model_validate(story_plan_data)
        if values.get("cancelled"):
            self.store.set_cancelled(task_id, story_plan, review_comment)
            return self._safe_sync_supervisor_plan(task_id, fallback=self.store.get(task_id))

        draft_result_data = values.get("draft_result")
        if not draft_result_data:
            raise RuntimeError("工作流结束后未找到正文结果。")
        draft_result = DraftResult.model_validate(draft_result_data)
        artifacts = self._build_artifacts(story_plan, draft_result)
        record = self.store.set_completed(task_id, story_plan, draft_result, artifacts)
        record = self._safe_sync_supervisor_plan(task_id, fallback=record)
        self._safe_emit_trace_summary(
            task_id,
            kind="completed",
            title="正文生成完成",
            detail="章节已全部写完，正文与工件已归档。",
        )
        return record

    def _run_task_sync(self, task_id: str, action_model_id: str | None = None) -> TaskRecord:
        if not self._enter_active_run(task_id):
            return self.store.get(task_id)
        task = self.store.get(task_id)
        if task.status not in {TaskStatus.CREATED, TaskStatus.SOURCES_INGESTED, TaskStatus.PLANNING}:
            raise ValueError("只有新建任务或已上传素材的任务才能开始生成。")
        try:
            self.store.mark_stage(
                task_id,
                status=TaskStatus.PLANNING,
                stage="planning",
                progress=max(task.progress, 20),
                message="开始执行 LangGraph 工作流，正在生成大纲。",
                event_type="outline.generating",
            )
            self._emit_trace_summary(
                task_id,
                kind="outline",
                title="开始生成大纲",
                detail="正在结合提示词、风格和参考文本收敛故事骨架。",
            )
            initial_state = self._initial_state(task, action_model_id)
            initial_payload = initial_state["input_payload"]
            normalized_spec = build_normalized_spec(
                initial_payload,
                novel_skill_service=self.novel_skill_service,
                style_profile_service=self.style_profile_service,
            )
            self.store.update_normalized_spec(task_id, self._persistable_normalized_spec(task, normalized_spec))
            self._emit_trace_summary(
                task_id,
                kind="spec",
                title="创作要求已标准化",
                detail="已整理用户诉求、方法论、风格、字数和参考材料，开始生成大纲。",
            )
            progress_token = set_progress_callback(self._build_progress_callback(task_id))
            exchange_token = set_exchange_callback(self._build_exchange_callback(task_id))
            try:
                result = self.graph.invoke(initial_state, config=self._config(task_id))
            finally:
                reset_progress_callback(progress_token)
                reset_exchange_callback(exchange_token)
            return self._sync_result(task_id, result)
        except Exception as exc:
            self._mark_failed_unless_stable(task_id, f"运行失败：{exc}")
            raise
        finally:
            self._leave_active_run(task_id)

    def _resume_task_sync(self, task_id: str, approved: bool, comment: str, action_model_id: str | None = None) -> TaskRecord:
        if not self._enter_active_run(task_id):
            return self.store.get(task_id)
        task = self.store.get(task_id)
        valid_statuses = {
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_MANUAL_ACTION,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
            TaskStatus.PLANNING,
            TaskStatus.DRAFTING,
        }
        if task.pending_review is None or task.status not in valid_statuses:
            raise ValueError("当前任务没有待恢复的审核节点。")
        try:
            if approved:
                self.store.mark_stage(
                    task_id,
                    status=TaskStatus.DRAFTING,
                    stage="drafting",
                    progress=max(task.progress, 60),
                    message="收到人工审核结果，继续执行工作流。",
                    event_type="draft.generating",
                    unit_id=task.current_unit,
                )
            else:
                self.store.append_event(
                    task_id,
                    stage="review_decision",
                    message="收到人工审核结果（驳回），准备修订。",
                    event_type="task.review.rejected",
                )
            progress_token = set_progress_callback(self._build_progress_callback(task_id))
            exchange_token = set_exchange_callback(self._build_exchange_callback(task_id))
            try:
                self._rehydrate_resume_state_if_needed(task, action_model_id)
                result = self.graph.invoke(
                    Command(resume={"approved": approved, "comment": comment}),
                    config=self._config(task_id),
                )
            finally:
                reset_progress_callback(progress_token)
                reset_exchange_callback(exchange_token)
            return self._sync_result(task_id, result, review_comment=comment)
        except Exception as exc:
            self._mark_failed_unless_stable(task_id, f"恢复执行失败：{exc}")
            raise
        finally:
            self._leave_active_run(task_id)

    def _build_artifacts(self, story_plan: StoryPlan, draft_result: DraftResult) -> list[ArtifactItem]:
        return [
            ArtifactItem(
                type="story_plan",
                name=f"{story_plan.working_title}-大纲",
                content=story_plan.model_dump_json(indent=2),
            ),
            ArtifactItem(
                type="manuscript",
                name=f"{draft_result.title}-正文",
                content=draft_result.body,
            ),
        ]

    def _to_summary(self, task: TaskRecord) -> TaskSummary:
        title = task.story_plan.working_title if task.story_plan else (task.input.title_hint or task.input.prompt[:24] or task.id)
        summary = task.events[-1].message if task.events else ""
        model_id = task.model_id or self.engine.settings.default_chat_model
        return TaskSummary(
            task_id=task.id,
            title=title,
            mode=task.mode,
            creative_mode=task.creative_mode,
            novel_size=task.novel_size,
            chapter_word_min=task.chapter_word_min,
            model_id=model_id,
            default_model_id=model_id,
            last_action_model_id=task.last_action_model_id,
            last_action_kind=task.last_action_kind,
            model_capabilities=self._model_capabilities(model_id),
            status=task.status,
            current_stage=task.current_stage,
            current_unit=task.current_unit,
            progress=task.progress,
            updated_at=task.updated_at,
            summary=summary,
            error_message=task.error_message,
            storage_state=task.storage_state,
            entry_refs={
                "meta_json": f"tasklog/{task.storage_state}/{task.id}/meta.json",
                "events_tail_json": f"tasklog/{task.storage_state}/{task.id}/events.tail.json",
                "result_json": f"tasklog/{task.storage_state}/{task.id}/result.json",
            },
        )

    def _model_summary(self) -> dict[str, Any]:
        models = self.model_catalog.list_models()
        supported_models = [item["id"] for item in models if isinstance(item, dict) and item.get("id")]
        default_model = self.model_catalog._effective_default_model()
        return {
            "default_model": default_model,
            "supported_models": supported_models,
        }

    def _workspace_tabs(self, task: TaskRecord) -> list[str]:
        tabs = ["request", "events"]
        if task.supervisor_plan is not None:
            tabs.append("supervisor")
        if task.story_plan is not None:
            tabs.append("outline")
        review_statuses = {
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
            TaskStatus.CANCELLED,
            TaskStatus.COMPLETED,
        }
        if task.pending_review is not None or task.status in review_statuses:
            tabs.append("review")
        if task.draft_result is not None:
            tabs.append("result")
        return tabs

    def _novel_progress(self, task: TaskRecord) -> dict[str, Any]:
        from app.storage.db_repository import get_novel_project

        project = get_novel_project(task.id)
        if project is None:
            if task.story_plan is None:
                return {}
            planned_count = int(task.story_plan.planned_chapter_count or len(task.story_plan.chapter_plan))
            completed_count = 0
            next_chapter_number = 1
            default_batch_size = 3
        else:
            planned_count = int(project.planned_chapter_count or 0)
            completed_count = int(project.completed_chapter_count or 0)
            next_chapter_number = int(project.next_chapter_number or (completed_count + 1))
            default_batch_size = int(project.default_batch_size or 3)
            current_generating_chapter_number = (
                int(project.current_generating_chapter_number)
                if project.current_generating_chapter_number
                else None
            )
        if project is None:
            current_generating_chapter_number = None
        target_chapter_count = int(task.target_chapter_count or task.input.target_chapter_count or 0)
        chapter_count_min = int(task.chapter_count_min or task.input.chapter_count_min)
        chapter_count_max = int(task.chapter_count_max or task.input.chapter_count_max)
        remaining = max(planned_count - completed_count, 0)
        return {
            "target_chapter_count": target_chapter_count,
            "chapter_count_min": chapter_count_min,
            "chapter_count_max": chapter_count_max,
            "planned_chapter_count": planned_count,
            "completed_chapter_count": completed_count,
            "next_chapter_number": next_chapter_number,
            "current_generating_chapter_number": current_generating_chapter_number if project is not None else None,
            "remaining_chapter_count": remaining,
            "default_batch_size": default_batch_size,
        }

    def _review_history(self, task: TaskRecord) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for event in task.events:
            if event.event_type == "review.waiting":
                items.append(
                    {
                        "version": "v1",
                        "action": "waiting",
                        "comment": event.message,
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif event.event_type == "review.submitted":
                items.append(
                    {
                        "version": "v1",
                        "action": "submitted",
                        "comment": event.message,
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif event.event_type == "task.review.rejected":
                items.append(
                    {
                        "version": "v1",
                        "action": "rejected",
                        "comment": event.message,
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif (
                event.event_type == "context.history.updated"
                and event.stage == "verification"
                and (event.payload or {}).get("exchange_label") == "fix-issues"
            ):
                items.append(
                    {
                        "version": "v1",
                        "action": "repairing",
                        "comment": "已进入验证问题修复阶段。",
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif event.event_type == "task.cancelled":
                items.append(
                    {
                        "version": "v1",
                        "action": "rejected",
                        "comment": event.message,
                        "created_at": event.created_at.isoformat(),
                    }
                )
            elif event.event_type == "task.completed":
                items.append(
                    {
                        "version": "v1",
                        "action": "approved",
                        "comment": "审核通过，已继续生成正文。",
                        "created_at": event.created_at.isoformat(),
                    }
                )
        return items

    def _outline_markdown(self, story_plan: StoryPlan) -> str:
        lines = [
            f"# {story_plan.working_title}",
            "",
            story_plan.logline,
            "",
            "## 世界观",
            "",
        ]
        lines.extend(f"- {item}" for item in story_plan.world_notes)
        lines.extend(["", "## 人物", ""])
        lines.extend(f"- {item}" for item in story_plan.character_notes)
        lines.extend(["", "## 章节计划", ""])
        for chapter in story_plan.chapter_plan:
            lines.append(f"- 第{chapter.number}章 {chapter.title}：{chapter.goal}")
        return "\n".join(lines) + "\n"

    def _result_markdown(self, draft_result: DraftResult) -> str:
        return f"# {draft_result.title}\n\n{draft_result.summary}\n\n{draft_result.body}\n"

    def _file_ref(self, task: TaskRecord, filename: str) -> str:
        return f"/api/tasks/{task.id}/files/{filename}"

    def _artifact_ref(self, task: TaskRecord, filename: str) -> str:
        return f"/api/tasks/{task.id}/files/artifacts/{filename}"

    def _artifact_index_item(self, task: TaskRecord, artifact: ArtifactItem) -> dict[str, Any]:
        md_ref = None
        json_ref = None
        if artifact.type == "story_plan":
            md_ref = self._file_ref(task, "outline.md")
            json_ref = self._file_ref(task, "outline.json")
        elif artifact.type == "manuscript":
            md_ref = self._file_ref(task, "result.md")
            json_ref = self._file_ref(task, "result.json")
        return {
            "id": artifact.id,
            "type": artifact.type,
            "name": artifact.name,
            "created_at": artifact.created_at.isoformat(),
            "md_ref": md_ref,
            "json_ref": json_ref,
        }

    def _historical_review_type(self, task: TaskRecord) -> str:
        for event in reversed(task.events):
            if event.event_type != "review.waiting":
                continue
            if event.stage == "waiting_verification_review":
                return "verification_review"
            if event.stage == "waiting_chapter_review":
                return "chapter_pair_review"
            if event.stage == "waiting_outline_review":
                return "outline_review"
        return "outline_review"

    def _build_progress_callback(self, task_id: str):
        def callback(event: dict[str, Any]) -> None:
            from app.storage.db_repository import update_project_status

            stage = str(event.get("stage") or "drafting")
            event_type = str(event.get("event_type") or "task.updated")
            unit_id = event.get("unit_id")
            message = str(event.get("message") or "任务进度已更新。")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            progress = self._progress_value(task_id, event_type, payload)
            status = TaskStatus.DRAFTING if stage == "drafting" else None
            self.store.mark_stage(
                task_id,
                status=status,
                stage=stage,
                progress=progress,
                unit_id=unit_id,
                message=message,
                event_type=event_type,
                payload=payload,
            )
            self._sync_supervisor_plan(task_id)
            # 章节正文持久化（从 conversation_history 中提取）
            if event_type == "chapter.saved":
                chapter_number = payload.get("chapter_number")
                chapter_title = payload.get("chapter_title")
                chapter_summary = payload.get("chapter_summary")
                conversation_history = event.get("conversation_history") or []
                # 从对话历史中提取章节 JSON
                chapter_content = self._extract_chapter_content(conversation_history)
                if chapter_content:
                    self._write_chapter_file(
                        task_id,
                        chapter_number=chapter_number,
                        title=chapter_title or f"第{chapter_number}章",
                        summary=chapter_summary or "",
                        content=chapter_content,
                    )
                self._emit_trace_summary(
                    task_id,
                    kind="chapter",
                    title=f"第 {payload.get('chapter_number', '?')} 章已完成",
                    detail=str(payload.get("chapter_summary") or payload.get("chapter_title") or message),
                    unit_id=unit_id,
                )
            elif event_type == "chapter.started":
                chapter_number = payload.get("chapter_number")
                if isinstance(chapter_number, int) and chapter_number > 0:
                    update_project_status(
                        task_id,
                        status=TaskStatus.DRAFTING.value,
                        current_generating_chapter_number=chapter_number,
                    )
                self._emit_trace_summary(
                    task_id,
                    kind="chapter",
                    title=f"开始生成第 {payload.get('chapter_number', '?')} 章",
                    detail=str(payload.get("chapter_title") or message),
                    unit_id=unit_id,
                )

        return callback

    def _extract_chapter_content(self, conversation_history: list[dict[str, Any]]) -> str | None:
        """从对话历史中提取最后一轮 assistant 消息中的章节正文。"""
        for item in reversed(conversation_history):
            if not isinstance(item, dict):
                continue
            if item.get("role") != "assistant":
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            # 尝试解析 JSON
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and parsed.get("content"):
                    return str(parsed["content"])
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def _write_chapter_file(
        self,
        task_id: str,
        chapter_number: int | None,
        title: str,
        summary: str,
        content: str,
    ) -> None:
        """将章节正文写入磁盘文件。"""
        task = self.store.get(task_id)
        task_dir = self.store._task_dir(task)
        chapters_dir = task_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        safe_num = f"{chapter_number:02d}" if chapter_number else "00"
        chapter_md_file = chapters_dir / f"{safe_num}.md"
        chapter_file = chapters_dir / f"{safe_num}.json"
        chapter_data = {
            "number": chapter_number,
            "title": title,
            "summary": summary,
            "content": content,
        }
        chapter_md_file.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        chapter_file.write_text(json.dumps(chapter_data, ensure_ascii=False, indent=2), encoding="utf-8")
        # 更新 chapters/index.json
        index_file = chapters_dir / "index.json"
        index_data: list[dict[str, Any]] = []
        if index_file.exists():
            try:
                index_data = json.loads(index_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                index_data = []
        # 去重后追加
        existing = {item.get("number") for item in index_data}
        if chapter_number not in existing:
            index_data.append({"number": chapter_number, "title": title, "summary": summary})
            index_data.sort(key=lambda x: x.get("number") or 0)
        index_file.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_current_chapters(self, task_id: str) -> list[dict[str, Any]]:
        """获取当前任务的章节正文列表（用于工作台预览）。"""
        task = self.store.get(task_id)
        task_dir = self.store._task_dir(task)
        chapters_dir = task_dir / "chapters"
        index_file = chapters_dir / "index.json"
        if not index_file.exists():
            return []
        try:
            index_data = json.loads(index_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return []
        chapters: list[dict[str, Any]] = []
        for item in index_data:
            num = item.get("number")
            safe_num = f"{num:02d}" if num else "00"
            chapter_file = chapters_dir / f"{safe_num}.json"
            if chapter_file.exists():
                try:
                    chapters.append(json.loads(chapter_file.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, ValueError):
                    chapters.append(item)
            else:
                chapters.append(item)
        return chapters

    def _build_exchange_callback(self, task_id: str):
        def callback(event: dict[str, Any]) -> None:
            stage = str(event.get("stage") or "unknown")
            exchange_label = str(event.get("exchange_label") or "exchange")
            history = event.get("conversation_history")
            if not isinstance(history, list):
                return
            history_path = self.store.write_message_history(
                task_id,
                stage=stage,
                history=history,
                filename=f"{exchange_label}-history",
            )
            cache_hit = bool(event.get("cache_hit"))
            cache_key = event.get("cache_key")
            model_name = str(event.get("model") or self.engine.settings.default_chat_model)
            message = (
                f"{stage} 阶段已命中模型响应缓存：{exchange_label}"
                if cache_hit
                else f"{stage} 阶段已记录模型上下文链：{exchange_label}"
            )
            self.store.append_event(
                task_id,
                stage=stage,
                message=message,
                event_type="cache.hit" if cache_hit else "context.history.updated",
                unit_id=exchange_label,
                json_ref=f"tasklog/{self.store.get(task_id).storage_state}/{task_id}/{history_path}",
                payload={
                    "summary": message,
                    "display_level": "public",
                    "cache_hit": cache_hit,
                    "cache_key": cache_key,
                    "model": model_name,
                    "history_count": len(history),
                    "exchange_label": exchange_label,
                },
            )

        return callback

    def _chapter_storage_path(self, task_id: str, chapter_number: int) -> Path:
        task = self.store.get(task_id)
        return self.store._task_dir(task) / "chapters" / f"{chapter_number:02d}.json"

    def _load_chapter_file_payload(self, task_id: str, chapter_number: int) -> dict[str, Any]:
        path = self._chapter_storage_path(task_id, chapter_number)
        return json.loads(path.read_text(encoding="utf-8"))

    def _progress_value(self, task_id: str, event_type: str, payload: dict[str, Any]) -> int | None:
        task = self.store.get(task_id)
        total = len(task.story_plan.chapter_plan) if task.story_plan is not None else 0
        chapter_number = payload.get("chapter_number")
        if not isinstance(chapter_number, int) or total <= 0:
            return max(task.progress, 60) if event_type.startswith("chapter.") else None
        base_progress = 55
        span = 35
        offset = chapter_number - 1 if event_type == "chapter.started" else chapter_number
        return min(90, max(task.progress, base_progress + int(offset / total * span)))

    def _sync_supervisor_plan(self, task_id: str) -> TaskRecord:
        task = self.store.get(task_id)
        if task.supervisor_plan is None:
            return task

        status_map = self._derive_supervisor_subtask_status(task)
        next_subtasks = [
            item.model_copy(update={"status": status_map.get(item.kind, item.status)}, deep=True)
            for item in task.supervisor_plan.subtasks
        ]
        task.supervisor_plan = task.supervisor_plan.model_copy(
            update={"subtasks": next_subtasks},
            deep=True,
        )
        return self.store.save(task)

    def _derive_supervisor_subtask_status(self, task: TaskRecord) -> dict[str, SubtaskStatus]:
        status_map = {
            "reference_analysis": SubtaskStatus.BLOCKED,
            "outline_planning": SubtaskStatus.BLOCKED,
            "chapter_writing": SubtaskStatus.BLOCKED,
            "chapter_review": SubtaskStatus.BLOCKED,
            "full_verification": SubtaskStatus.BLOCKED,
            "result_assembly": SubtaskStatus.BLOCKED,
        }

        if task.status in {TaskStatus.CREATED, TaskStatus.SOURCES_INGESTED}:
            status_map["reference_analysis"] = SubtaskStatus.READY
            return status_map

        if task.status is TaskStatus.PLANNING:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.WAITING_OUTLINE_REVIEW:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.WAITING_CHAPTER_REVIEW:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.COMPLETED
            status_map["chapter_writing"] = SubtaskStatus.RUNNING
            status_map["chapter_review"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.WAITING_VERIFICATION_REVIEW:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.COMPLETED
            status_map["chapter_writing"] = SubtaskStatus.COMPLETED
            status_map["chapter_review"] = SubtaskStatus.COMPLETED
            status_map["full_verification"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.ASSEMBLING:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.COMPLETED
            status_map["chapter_writing"] = SubtaskStatus.COMPLETED
            status_map["chapter_review"] = SubtaskStatus.COMPLETED
            status_map["full_verification"] = SubtaskStatus.COMPLETED
            status_map["result_assembly"] = SubtaskStatus.RUNNING
            return status_map

        if task.status is TaskStatus.COMPLETED:
            return {key: SubtaskStatus.COMPLETED for key in status_map}

        if task.status is TaskStatus.DRAFTING:
            status_map["reference_analysis"] = SubtaskStatus.COMPLETED
            status_map["outline_planning"] = SubtaskStatus.COMPLETED
            if task.current_stage == "verification" or task.current_unit == "verification":
                status_map["chapter_writing"] = SubtaskStatus.COMPLETED
                status_map["chapter_review"] = SubtaskStatus.COMPLETED
                status_map["full_verification"] = SubtaskStatus.RUNNING
                return status_map

            status_map["chapter_writing"] = SubtaskStatus.RUNNING
            if isinstance(task.current_unit, str) and task.current_unit.startswith("chapter-pair-"):
                status_map["chapter_review"] = SubtaskStatus.RUNNING
            return status_map

        if task.status in {TaskStatus.CANCELLED, TaskStatus.FAILED}:
            derived = self._derive_supervisor_subtask_status_for_terminal(task)
            return derived

        return status_map

    def _derive_supervisor_subtask_status_for_terminal(self, task: TaskRecord) -> dict[str, SubtaskStatus]:
        status_map = self._derive_supervisor_subtask_status(
            task.model_copy(update={"status": TaskStatus.DRAFTING}, deep=True)
        )
        if task.current_stage in {"planning", "waiting_outline_review"}:
            status_map["outline_planning"] = SubtaskStatus.FAILED
        elif task.current_stage in {"drafting", "waiting_chapter_review"}:
            if isinstance(task.current_unit, str) and task.current_unit.startswith("chapter-pair-"):
                status_map["chapter_review"] = SubtaskStatus.FAILED
            else:
                status_map["chapter_writing"] = SubtaskStatus.FAILED
        elif task.current_stage in {"verification", "waiting_verification_review"}:
            status_map["full_verification"] = SubtaskStatus.FAILED
        elif task.current_stage == "completed":
            status_map["result_assembly"] = SubtaskStatus.FAILED
        return status_map

    def _enter_active_run(self, task_id: str) -> bool:
        with self._run_lock:
            if task_id in self._active_runs:
                return False
            self._active_runs.add(task_id)
            return True

    def _leave_active_run(self, task_id: str) -> None:
        with self._run_lock:
            self._active_runs.discard(task_id)

    def _start_background(self, task_id: str, target, *args: Any) -> None:
        def runner() -> None:
            try:
                target(*args)
            except Exception as exc:
                # 尝试标记任务为失败，防止永久卡在运行状态
                try:
                    self._mark_failed_unless_stable(task_id, f"后台任务异常：{exc}")
                except Exception:
                    logger.exception("后台任务异常且 set_failed 也失败，task_id=%s", task_id)

        threading.Thread(
            target=runner,
            name=f"task-worker-{task_id}",
            daemon=True,
        ).start()

    def _request_preview(self, task: TaskRecord) -> dict[str, Any]:
        model_id = task.model_id or self.engine.settings.default_chat_model
        return {
            "prompt": task.input.prompt,
            "model_id": model_id,
            "default_model_id": model_id,
            "last_action_model_id": task.last_action_model_id,
            "last_action_kind": task.last_action_kind,
            "creative_mode": task.creative_mode.value if task.creative_mode else "",
            "novel_size": task.novel_size.value if task.novel_size else "",
            "target_chapter_count": task.target_chapter_count or task.input.target_chapter_count,
            "chapter_word_min": task.chapter_word_min or task.input.target_words,
            "target_words": task.input.target_words,
            "model_capabilities": self._model_capabilities(model_id),
            "genre": task.input.genre,
            "style": task.input.style,
            "style_profile_id": task.input.style_profile_id,
            "style_profile_name": str(task.normalized_spec.get("style_profile_name") or ""),
            "target_words": task.input.target_words,
            "audience": task.input.audience,
            "banned": task.input.banned,
            "title_hint": task.input.title_hint,
        }

    def _extract_interrupt_payload(self, result: dict[str, Any]) -> dict[str, Any]:
        interrupts = result.get("__interrupt__")
        if isinstance(interrupts, dict):
            return interrupts
        if not isinstance(interrupts, list) or not interrupts:
            raise RuntimeError("工作流返回了空的中断结果，无法恢复审核状态。")
        first_interrupt = interrupts[0]
        if isinstance(first_interrupt, dict):
            return first_interrupt
        payload = getattr(first_interrupt, "value", None)
        if isinstance(payload, dict):
            return payload
        raise RuntimeError("工作流中断结果结构不兼容，无法解析审核载荷。")

    def _safe_sync_supervisor_plan(self, task_id: str, *, fallback: TaskRecord) -> TaskRecord:
        try:
            return self._sync_supervisor_plan(task_id)
        except Exception:
            logger.exception("supervisor 计划同步失败，保留已持久化任务状态，task_id=%s", task_id)
            return self.store.get(task_id) if fallback.id == task_id else fallback

    def _safe_emit_trace_summary(self, task_id: str, **kwargs: Any) -> None:
        try:
            self._emit_trace_summary(task_id, **kwargs)
        except Exception:
            logger.exception("trace 摘要写入失败，已保留任务主状态，task_id=%s", task_id)

    def _has_stable_terminal_state(self, task: TaskRecord) -> bool:
        return task.status in {
            TaskStatus.WAITING_OUTLINE_REVIEW,
            TaskStatus.WAITING_CHAPTER_REVIEW,
            TaskStatus.WAITING_VERIFICATION_REVIEW,
            TaskStatus.WAITING_MANUAL_ACTION,
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
        }

    def _mark_failed_unless_stable(self, task_id: str, message: str) -> TaskRecord:
        current = self.store.get(task_id)
        if self._has_stable_terminal_state(current):
            logger.warning(
                "任务已进入稳定状态，跳过失败覆盖。task_id=%s status=%s reason=%s",
                task_id,
                current.status.value,
                message,
            )
            return current
        if (
            current.story_plan is not None
            or current.pending_review is not None
            or current.normalized_spec
            or self._has_novel_project(task_id)
            or bool(str(current.input.prompt or "").strip())
        ):
            record = self.store.set_waiting_manual_action(
                task_id,
                message,
                payload={
                    "summary": "任务执行异常，但存在可恢复上下文，已转入待人工处理。",
                    "display_level": "public",
                    "reason": "recoverable_runtime_error",
                },
            )
            return self._safe_sync_supervisor_plan(task_id, fallback=record)
        record = self.store.set_failed(task_id, message)
        return self._safe_sync_supervisor_plan(task_id, fallback=record)

    def _model_capabilities(self, model_id: str) -> dict[str, Any] | None:
        profile = self.model_catalog.get_model_profile(model_id)
        capabilities = profile.get("capabilities")
        return capabilities if isinstance(capabilities, dict) else None

    def _load_context_status(self, task_id: str) -> dict[str, Any]:
        for relative_path in ("context/drafting/draft-context.json", "context/planning/outline-context.json"):
            try:
                snapshot = self.store.read_json(task_id, relative_path)
            except FileNotFoundError:
                continue
            return self._context_status_from_snapshot(snapshot)
        return {}

    def _load_response_cache_status(self, task: TaskRecord) -> dict[str, Any]:
        cache_event = next(
            (event for event in reversed(task.events) if event.event_type == "cache.hit"),
            None,
        )
        if cache_event is None:
            return {}
        payload = cache_event.payload if isinstance(cache_event.payload, dict) else {}
        status: dict[str, Any] = {
            "stage": cache_event.stage,
            "status": "cached",
            "summary": cache_event.message,
            "cache_hit": True,
            "cache_scope": "response_cache",
        }
        if payload.get("cache_key"):
            status["cache_key"] = payload.get("cache_key")
        if payload.get("model"):
            status["model"] = payload.get("model")
        if isinstance(payload.get("history_count"), int):
            status["history_count"] = payload.get("history_count")
        if payload.get("exchange_label"):
            status["exchange_label"] = payload.get("exchange_label")
        return status

    def _load_message_history(
        self,
        task_id: str,
        stage: str,
        filename: str,
    ) -> list[dict[str, str]]:
        try:
            payload = self.store.read_json(task_id, f"context/{stage}/{filename}.json")
        except FileNotFoundError:
            return []
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user").strip() or "user"
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            normalized.append({"role": role, "content": content})
        return normalized

    def _context_status_from_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        budget = snapshot.get("budget") if isinstance(snapshot.get("budget"), dict) else {}
        packet = snapshot.get("packet") if isinstance(snapshot.get("packet"), dict) else {}
        compressed_references = snapshot.get("compressed_references")
        compressed_items = compressed_references if isinstance(compressed_references, list) else []
        original_chars = sum(
            int(item.get("original_chars") or 0)
            for item in compressed_items
            if isinstance(item, dict)
        )
        compressed_chars = sum(
            int(item.get("compressed_chars") or 0)
            for item in compressed_items
            if isinstance(item, dict)
        )
        compression_applied = any(
            bool(item.get("was_compressed"))
            for item in compressed_items
            if isinstance(item, dict)
        )
        ratio = None
        if original_chars > 0:
            ratio = round(max(original_chars - compressed_chars, 0) / original_chars, 4)
        max_input_tokens = budget.get("max_input_tokens")
        input_tokens = packet.get("estimated_input_tokens")
        window_usage_ratio = None
        if isinstance(max_input_tokens, int) and max_input_tokens > 0 and isinstance(input_tokens, int):
            window_usage_ratio = round(input_tokens / max_input_tokens, 4)
        return {
            "stage": snapshot.get("stage"),
            "status": "cached" if snapshot.get("cache_hit") else "fresh",
            "summary": "已完成上下文预算、压缩与装配。",
            "input_tokens": input_tokens,
            "current_tokens": input_tokens,
            "max_input_tokens": max_input_tokens,
            "window_usage_ratio": window_usage_ratio,
            "compression_applied": compression_applied,
            "compression_ratio": ratio,
            "compression_summary": f"已压缩 {sum(1 for item in compressed_items if isinstance(item, dict) and item.get('was_compressed'))} 份素材",
            "cache_hit": bool(snapshot.get("cache_hit")),
            "cache_scope": "runtime_context",
            "cache_key": snapshot.get("cache_key"),
            "cached_segments": len(compressed_items),
        }

    def _emit_trace_summary(
        self,
        task_id: str,
        *,
        kind: str,
        title: str,
        detail: str,
        unit_id: str | None = None,
    ) -> TaskEvent:
        task = self.store.get(task_id)
        return self.store.append_event(
            task_id,
            stage=task.current_stage,
            message=f"{title}：{detail}",
            event_type="trace.summary",
            unit_id=unit_id,
            payload={
                "kind": kind,
                "title": title,
                "detail": detail,
                "display_level": "public",
            },
        ).events[-1]

    def _is_stale_running_task(self, task: TaskRecord) -> bool:
        # 只有自动执行中的状态（planning/drafting/assembling）才可能过期
        # 等待用户操作的状态（waiting_*）不会过期
        if task.storage_state != "runs":
            return False
        if task.status not in {
            TaskStatus.PLANNING,
            TaskStatus.DRAFTING,
            TaskStatus.ASSEMBLING,
        }:
            return False
        if task.id in self._active_runs:
            return False
        return utc_now() - task.updated_at > self._STALE_RUN_AFTER

    def _to_stale_run_summary(self, task: TaskRecord) -> TaskSummary:
        summary = self._to_summary(task)
        summary.summary = f"该任务在 {summary.updated_at.isoformat()} 后未继续更新，已不计入活动运行数。"
        return summary
