from __future__ import annotations

import asyncio
import logging
from typing import Any


from app.domain.models import (
    ArchiveTaskDetailResponse,
    ArchiveTaskListResponse,
    ArtifactItem,
    ChapterPlan,
    DashboardResponse,
    DraftResult,
    ResultResponse,
    ReviewResponse,
    StoryPlan,
    SubtaskStatus,
    TaskRecord,
    TaskStatus,
    TaskSummary,
    WorkspaceResponse,
)
from app.storage import db_repository

logger = logging.getLogger(__name__)


class TaskServiceQueriesMixin:

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
        story_plan_payload: dict[str, Any] | None = None
        if task.story_plan is not None:
            story_plan_payload = {
                "working_title": task.story_plan.working_title,
                "logline": task.story_plan.logline,
                "world_notes": task.story_plan.world_notes,
                "character_notes": task.story_plan.character_notes,
                "planned_chapter_count": task.story_plan.planned_chapter_count,
                "chapter_plan": [
                    {"number": ch.number, "title": ch.title, "goal": ch.goal}
                    for ch in task.story_plan.chapter_plan
                ],
            }
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
            story_plan=story_plan_payload,
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
        # 保留最近事件，同时确保所有 chapter.* 事件不被截断
        chapter_events = [e for e in task.events if e.event_type.startswith("chapter.")]
        other_events = [e for e in task.events if not e.event_type.startswith("chapter.")]
        recent_other_events = other_events[-100:]
        recent_events = chapter_events + recent_other_events
        recovery_contract = self._build_recovery_contract(task, reconciliation=reconciliation)
        outline_batch = task.pending_review.outline_batch if task.pending_review else None
        outline_phase = outline_batch.phase if outline_batch else ""
        outline_completed_count = outline_batch.completed_count if outline_batch else 0
        outline_total_count = outline_batch.total_count if outline_batch else 0
        if outline_batch is None:
            outline_summary = db_repository.get_chapter_plan_batch_workspace_summary(task.id)
            if outline_summary is not None:
                outline_phase = str(outline_summary["phase"])
                outline_completed_count = int(outline_summary["approved_count"])
                outline_total_count = int(outline_summary["total_count"])
        context_status = self._load_context_status(task.id)
        response_cache_status = self._load_response_cache_status(task)
        return WorkspaceResponse(
            meta=self._to_summary(task),
            recent_events=recent_events,
            active_trace_summary=recent_events[-1].message if recent_events else None,
            available_tabs=self._workspace_tabs(task),
            **recovery_contract,
            request_preview=self._request_preview(task),
            context_status=context_status,
            response_cache_status=response_cache_status,
            pending_review_summary=self._build_pending_review_summary(task),
            rag_status=self._build_rag_status(task, context_status),
            llm_report=self._build_llm_report(task),
            novel_progress=self._novel_progress(task),
            sources=task.sources,
            supervisor_plan=task.supervisor_plan,
            agent_runs=task.agent_runs,
            auto_review_trace=task.auto_review_trace or [],
            outline_phase=outline_phase,
            outline_completed_count=outline_completed_count,
            outline_total_count=outline_total_count,
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
        outline_batch = review.outline_batch
        pending_batch = None
        phase = outline_batch.phase if outline_batch else "master"
        completed_count = outline_batch.completed_count if outline_batch else 0
        if outline_batch and outline_batch.phase == "chapter_batches":
            pending_batch = outline_batch.current_batch_plans or None
        story_plan_payload = None
        if task.story_plan is not None:
            story_plan_payload = {
                "working_title": task.story_plan.working_title,
                "logline": task.story_plan.logline,
                "world_notes": task.story_plan.world_notes,
                "character_notes": task.story_plan.character_notes,
                "planned_chapter_count": task.story_plan.planned_chapter_count,
            }
        return ReviewResponse(
            meta=self._to_summary(task),
            review_type="outline_review",
            review_version=review.version,
            **recovery_contract,
            summary=review.summary,
            risk_flags=review.risk_flags,
            outline_markdown=self._outline_markdown(
                task.story_plan,
                phase=phase,
                completed_count=completed_count,
                pending_batch=pending_batch,
            ) if task.story_plan else None,
            outline_md_ref=outline_ref,
            revision_count=review.revision_count,
            review_history=self._review_history(task),
            auto_review_trace=auto_review_trace,
            story_plan=story_plan_payload,
            outline_batch={
                "phase": outline_batch.phase,
                "batch_index": outline_batch.batch_index,
                "batch_size": outline_batch.batch_size,
                "completed_count": outline_batch.completed_count,
                "total_count": outline_batch.total_count,
                "current_batch_plans": [
                    {"number": p.number, "title": p.title, "goal": p.goal}
                    for p in (outline_batch.current_batch_plans or [])
                ],
            } if outline_batch else None,
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

    def _to_summary(self, task: TaskRecord) -> TaskSummary:
        title = task.story_plan.working_title if task.story_plan else (task.input.title_hint or task.input.prompt[:24] or task.id)
        summary = task.events[-1].message if task.events else ""
        model_id = task.model_id or self.engine.settings.default_chat_model
        review_model_meta = self._auto_review_model_metadata(task)
        chapter_count, word_count = self._archive_metrics(task)
        last_error_detail = task.error_message
        for event in reversed(task.events):
            if event.event_type == "task.error_recorded":
                last_error_detail = event.payload.get("detail") if isinstance(event.payload, dict) else None
                if not last_error_detail:
                    last_error_detail = event.message
                break
        return TaskSummary(
            task_id=task.id,
            title=title,
            mode=task.mode,
            creative_mode=task.creative_mode,
            novel_size=task.novel_size,
            chapter_word_min=task.chapter_word_min,
            model_id=model_id,
            creative_model_id=model_id,
            default_model_id=model_id,
            last_action_model_id=task.last_action_model_id,
            last_action_kind=task.last_action_kind,
            auto_review_model_mode=review_model_meta["auto_review_model_mode"],
            review_model_id=review_model_meta["review_model_id"],
            model_capabilities=self._model_capabilities(model_id),
            status=task.status,
            current_stage=task.current_stage,
            current_unit=task.current_unit,
            progress=task.progress,
            chapter_count=chapter_count,
            word_count=word_count,
            updated_at=task.updated_at,
            summary=summary,
            error_message=task.error_message,
            auto_review=task.auto_review if task.auto_review is not None else False,
            last_error_detail=last_error_detail,
            storage_state=task.storage_state,
            entry_refs={
                "meta_json": f"tasklog/{task.storage_state}/{task.id}/meta.json",
                "events_tail_json": f"tasklog/{task.storage_state}/{task.id}/events.tail.json",
                "result_json": f"tasklog/{task.storage_state}/{task.id}/result.json",
            },
        )

    def _archive_metrics(self, task: TaskRecord) -> tuple[int | None, int | None]:
        if task.draft_result is not None:
            chapters = task.draft_result.chapters
            return len(chapters), sum(self._count_text_words(chapter.content) for chapter in chapters)
        if task.story_plan is not None:
            return len(task.story_plan.chapter_plan), None
        return None, None

    @staticmethod
    def _count_text_words(text: str | None) -> int:
        if not text:
            return 0
        chinese_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        english_words = 0
        in_word = False
        for char in text:
            if char.isascii() and char.isalpha():
                if not in_word:
                    english_words += 1
                    in_word = True
            else:
                in_word = False
        return chinese_chars + english_words

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

    def _outline_markdown(
        self,
        story_plan: StoryPlan,
        *,
        phase: str = "master",
        completed_count: int = 0,
        pending_batch: list[ChapterPlan] | None = None,
    ) -> str:
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

        total = story_plan.planned_chapter_count or 0
        if phase == "master":
            # 总纲阶段：只显示预计总章数，不将 chapter_plan 视为已确认
            lines.extend(["", f"## 章节计划（预计 {total} 章，待分步设计）", ""])
            if story_plan.chapter_plan:
                lines.append(f"大纲总纲已预置 {len(story_plan.chapter_plan)} 章概要，将在总纲通过后分批展示审核。")
            else:
                lines.append("总纲通过后，系统将分批次生成章节计划供审核。")
        else:
            # 批次阶段：按 completed_count 区分已确认与未确认
            all_plans = story_plan.chapter_plan or []
            confirmed = all_plans[:completed_count]
            lines.extend(["", f"## 章节计划（已确认 {len(confirmed)} / {total or '?'} 章）", ""])
            for chapter in confirmed:
                lines.append(f"- [已确认] 第{chapter.number}章 {chapter.title}：{chapter.goal}")

            if pending_batch:
                lines.append("")
                lines.append(f"### 待审核批次（第 {pending_batch[0].number}-{pending_batch[-1].number} 章）")
                lines.append("")
                for chapter in pending_batch:
                    lines.append(f"- [待审核] 第{chapter.number}章 {chapter.title}：{chapter.goal}")

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

    def _request_preview(self, task: TaskRecord) -> dict[str, Any]:
        model_id = task.model_id or self.engine.settings.default_chat_model
        review_model_meta = self._auto_review_model_metadata(task)
        return {
            "prompt": task.input.prompt,
            "model_id": model_id,
            "creative_model_id": model_id,
            "default_model_id": model_id,
            "last_action_model_id": task.last_action_model_id,
            "last_action_kind": task.last_action_kind,
            "auto_review_model_mode": review_model_meta["auto_review_model_mode"],
            "review_model_id": review_model_meta["review_model_id"],
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

    def _build_pending_review_summary(self, task: TaskRecord) -> dict[str, Any]:
        stage = task.current_stage or task.status.value
        review = task.pending_review
        if review is None:
            return self._empty_pending_review_summary(stage)

        review_type = review.type or ""
        expected_status_by_review_type = {
            "outline_review": TaskStatus.WAITING_OUTLINE_REVIEW,
            "chapter_pair_review": TaskStatus.WAITING_CHAPTER_REVIEW,
            "verification_review": TaskStatus.WAITING_VERIFICATION_REVIEW,
        }
        if task.status is not expected_status_by_review_type.get(review_type):
            return self._empty_pending_review_summary(stage)

        outline_batch = review.outline_batch
        summary: dict[str, Any] = {
            "present": True,
            "review_type": review_type,
            "stage": stage,
            "batch_index": None,
            "revision_count": review.revision_count,
            "outline_phase": outline_batch.phase if outline_batch else "",
            "summary": self._short_debug_summary(review.summary),
        }

        if review_type == "chapter_pair_review":
            summary["batch_index"] = review.batch_index
            summary["revision_count"] = review.chapter_pair_revision_count
            summary["summary"] = self._chapter_pair_review_summary(review.batch_index, review.completed_count)
            return summary

        if review_type == "verification_review":
            summary["revision_count"] = review.verification_revision_count
            return summary

        if review_type == "outline_review" and outline_batch is not None:
            summary["outline_phase"] = outline_batch.phase
            summary["batch_index"] = outline_batch.batch_index
            if outline_batch.phase == "chapter_batches":
                summary["summary"] = self._outline_batch_review_summary(outline_batch)
        return summary

    @staticmethod
    def _empty_pending_review_summary(stage: str) -> dict[str, Any]:
        return {
            "present": False,
            "review_type": "",
            "stage": stage,
            "batch_index": None,
            "revision_count": 0,
            "outline_phase": "",
            "summary": "当前没有待审核内容。",
        }

    def _build_rag_status(self, task: TaskRecord, context_status: dict[str, Any]) -> dict[str, Any]:
        rag_service = self.rag_service
        enabled = rag_service is not None
        ready = False
        last_error = ""

        if rag_service is not None:
            config = getattr(rag_service, "config", None)
            if hasattr(config, "enabled"):
                enabled = bool(getattr(config, "enabled"))
            try:
                ready = bool(rag_service.is_ready())
            except Exception as exc:  # pragma: no cover - 具体异常类型由外部 RAG 实现决定
                logger.warning("读取 RAG 工作区就绪状态失败: %s", exc)
                ready = False
                last_error = str(exc)
            if not ready and not last_error:
                try:
                    last_error = str(rag_service.readiness_error() or "")
                except Exception as exc:  # pragma: no cover - 具体异常类型由外部 RAG 实现决定
                    logger.warning("读取 RAG 工作区未就绪原因失败: %s", exc)
                    last_error = str(exc)

        last_query_stage = ""
        injected = False
        injection_evidence = ""

        event_evidence = self._rag_event_evidence(task)
        if event_evidence:
            injected = True
            injection_evidence = "event"
            last_query_stage = event_evidence.get("stage", "")

        if not injected:
            snapshot_evidence = self._rag_context_snapshot_evidence(task.id)
            if snapshot_evidence:
                injected = True
                injection_evidence = "context_snapshot"
                last_query_stage = snapshot_evidence.get("stage", "")

        if not last_query_stage:
            last_query_stage = self._rag_last_stage_from_events(task)

        if not enabled:
            summary = "RAG 未启用。"
        elif ready:
            summary = "RAG 已启用且索引可用。"
        else:
            summary = "RAG 已启用但尚未就绪。"

        return {
            "enabled": enabled,
            "ready": ready if enabled else False,
            "source": "workspace",
            "summary": summary,
            "last_query_stage": last_query_stage,
            "last_error": last_error,
            "injected": injected,
            "injection_evidence": injection_evidence,
        }

    @staticmethod
    def _short_debug_summary(value: str | None, max_chars: int = 80) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}..."

    @staticmethod
    def _chapter_pair_review_summary(batch_index: int | None, completed_count: int | None) -> str:
        if batch_index is not None:
            display_batch = int(batch_index) + 1
            return f"等待第 {display_batch} 批章节审核。"
        if completed_count is not None:
            return f"等待已完成 {completed_count} 章后的章节审核。"
        return "等待章节审核。"

    @staticmethod
    def _outline_batch_review_summary(outline_batch: Any) -> str:
        current_plans = outline_batch.current_batch_plans or []
        if current_plans:
            first = current_plans[0].number
            last = current_plans[-1].number
            return f"等待第 {first}-{last} 章章节计划审核。"
        if outline_batch.total_count:
            return f"等待章节计划批次审核，已确认 {outline_batch.completed_count}/{outline_batch.total_count} 章。"
        return "等待章节计划批次审核。"

    def _rag_event_evidence(self, task: TaskRecord) -> dict[str, str]:
        for event in reversed(task.events):
            payload = event.payload if isinstance(event.payload, dict) else {}
            if self._event_has_rag_injection_evidence(event.event_type, payload):
                return {"stage": event.stage or ""}
        return {}

    @staticmethod
    def _event_has_rag_injection_evidence(event_type: str, payload: dict[str, Any]) -> bool:
        if TaskServiceQueriesMixin._rag_event_type_blocks_injection(event_type):
            return False
        evidence_keys = (
            "rag_injected",
            "rag_context_injected",
            "rag_augmented",
        )
        if any(bool(payload.get(key)) for key in evidence_keys):
            return True
        count_keys = ("rag_hit_count", "rag_context_count", "selected_context_count")
        for key in count_keys:
            value = payload.get(key)
            if isinstance(value, int) and value > 0:
                return True
        for key in ("selected_contexts", "selected_hits", "hits"):
            value = payload.get(key)
            if isinstance(value, list) and len(value) > 0:
                return True
        return False

    @staticmethod
    def _rag_event_type_blocks_injection(event_type: str) -> bool:
        normalized = event_type.strip().lower()
        blocked_prefixes = (
            "rag.search_failed",
            "rag.search_skipped",
            *TaskServiceQueriesMixin._rag_stage_denied_event_type_prefixes(),
        )
        return any(normalized.startswith(prefix) for prefix in blocked_prefixes)

    @staticmethod
    def _rag_stage_denied_event_type_prefixes() -> tuple[str, ...]:
        return (
            "rag.status",
            "rag.rebuild",
            "rag_rebuild",
        )

    @staticmethod
    def _rag_event_type_blocks_stage(event_type: str) -> bool:
        normalized = event_type.strip().lower()
        return any(
            normalized.startswith(prefix)
            for prefix in TaskServiceQueriesMixin._rag_stage_denied_event_type_prefixes()
        )

    def _rag_context_snapshot_evidence(self, task_id: str) -> dict[str, str]:
        for relative_path in ("context/drafting/draft-context.json", "context/planning/outline-context.json"):
            try:
                snapshot = self.store.read_json(task_id, relative_path)
            except FileNotFoundError:
                continue
            compressed_references = snapshot.get("compressed_references")
            if self._compressed_references_have_rag_source(compressed_references):
                return {"stage": str(snapshot.get("stage") or "")}
        return {}

    @staticmethod
    def _compressed_references_have_rag_source(compressed_references: Any) -> bool:
        if not isinstance(compressed_references, list):
            return False
        for item in compressed_references:
            if not isinstance(item, dict):
                continue
            for key in ("source_id", "id", "source"):
                value = item.get(key)
                if isinstance(value, str) and value.strip().startswith("rag-"):
                    return True
        return False

    @staticmethod
    def _rag_last_stage_from_events(task: TaskRecord) -> str:
        for event in reversed(task.events):
            payload = event.payload if isinstance(event.payload, dict) else {}
            event_type = event.event_type.lower()
            if TaskServiceQueriesMixin._rag_event_type_blocks_stage(event_type):
                continue
            has_rag_payload_key = any(
                str(key).lower().startswith("rag_")
                or str(key).lower() in {"selected_contexts", "selected_hits", "hits"}
                for key in payload.keys()
            )
            if event_type.startswith("rag.") or event_type.startswith("rag_") or has_rag_payload_key:
                return event.stage or ""
        return ""

    def _build_llm_report(self, task: TaskRecord) -> dict[str, Any]:
        token_fields = ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "cache_read_input_tokens")
        usage_total = {field: 0 for field in token_fields}
        by_model: dict[str, dict[str, Any]] = {}
        by_stage: dict[str, dict[str, Any]] = {}
        timing_by_stage: dict[str, dict[str, Any]] = {}
        latest_usage: dict[str, Any] | None = None
        latest_exchange: dict[str, Any] | None = None
        slowest_step: dict[str, Any] | None = None
        slowest_first_token: dict[str, Any] | None = None
        usage_count = 0
        exchange_count = 0
        cache_hit_count = 0
        runtime_response_cache_hit_count = 0
        provider_prompt_cache_hit_count = 0
        timing_count = 0

        for event in task.events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            if event.event_type == "model.usage":
                usage = self._normalize_usage_tokens(payload)
                model = str(payload.get("model") or task.model_id or "unknown")
                stage = event.stage or "unknown"
                provider_prompt_cache_hit = usage["cached_tokens"] > 0 or usage["cache_read_input_tokens"] > 0
                if provider_prompt_cache_hit:
                    provider_prompt_cache_hit_count += 1
                for field in token_fields:
                    usage_total[field] += usage[field]
                self._add_llm_usage_bucket(by_model, model, usage)
                self._add_llm_usage_bucket(by_stage, stage, usage)
                usage_count += 1
                latest_usage = {
                    "stage": stage,
                    "unit_id": event.unit_id or "",
                    "model": model,
                    "finish_reason": payload.get("finish_reason"),
                    "provider_prompt_cache_hit": provider_prompt_cache_hit,
                    **usage,
                }
            elif event.event_type in {"context.history.updated", "cache.hit"}:
                exchange_count += 1
                cache_hit = event.event_type == "cache.hit" or bool(payload.get("cache_hit"))
                if cache_hit:
                    runtime_response_cache_hit_count += 1
                    cache_hit_count += 1
                latest_exchange = {
                    "stage": event.stage,
                    "event_type": event.event_type,
                    "unit_id": event.unit_id or "",
                    "exchange_label": payload.get("exchange_label") or event.unit_id or "",
                    "model": payload.get("model") or task.model_id or "",
                    "cache_hit": cache_hit,
                }
                if payload.get("cache_key"):
                    latest_exchange["cache_key"] = payload.get("cache_key")
                if isinstance(payload.get("history_count"), int):
                    latest_exchange["history_count"] = payload.get("history_count")
                if isinstance(payload.get("parse_duration_ms"), (int, float)):
                    latest_exchange["parse_duration_ms"] = payload.get("parse_duration_ms")
                raw_timing_details = payload.get("timing_details")
                if isinstance(raw_timing_details, list):
                    for raw_detail in raw_timing_details:
                        if not isinstance(raw_detail, dict):
                            continue
                        stage = str(raw_detail.get("stage") or event.stage or "unknown")
                        exchange_label = str(raw_detail.get("exchange_label") or payload.get("exchange_label") or event.unit_id or "")
                        duration_ms = self._safe_non_negative_float(raw_detail.get("duration_ms"))
                        first_token_ms = self._safe_non_negative_float(raw_detail.get("first_token_ms"))
                        model = str(raw_detail.get("model") or payload.get("model") or task.model_id or "")
                        bucket = timing_by_stage.setdefault(
                            stage,
                            {
                                "call_count": 0,
                                "total_duration_ms": 0.0,
                                "max_duration_ms": 0.0,
                                "max_first_token_ms": 0.0,
                                "retry_count": 0,
                                "repair_count": 0,
                            },
                        )
                        bucket["call_count"] += 1
                        bucket["total_duration_ms"] += duration_ms
                        bucket["max_duration_ms"] = max(bucket["max_duration_ms"], duration_ms)
                        bucket["max_first_token_ms"] = max(bucket["max_first_token_ms"], first_token_ms)
                        if bool(raw_detail.get("is_retry")):
                            bucket["retry_count"] += 1
                        if bool(raw_detail.get("is_repair")):
                            bucket["repair_count"] += 1
                        timing_count += 1
                        detail = {
                            "stage": stage,
                            "exchange_label": exchange_label,
                            "model": model,
                            "duration_ms": duration_ms,
                            "first_token_ms": first_token_ms,
                            "attempt": self._safe_non_negative_int(raw_detail.get("attempt")) or 1,
                            "finish_reason": raw_detail.get("finish_reason"),
                            "content_chars": self._safe_non_negative_int(raw_detail.get("content_chars")),
                            "reasoning_chars": self._safe_non_negative_int(raw_detail.get("reasoning_chars")),
                            "status": raw_detail.get("status") or "success",
                            "is_retry": bool(raw_detail.get("is_retry")),
                            "is_repair": bool(raw_detail.get("is_repair")),
                        }
                        if slowest_step is None or duration_ms > slowest_step["duration_ms"]:
                            slowest_step = detail
                        if first_token_ms > 0 and (slowest_first_token is None or first_token_ms > slowest_first_token["first_token_ms"]):
                            slowest_first_token = detail

        if usage_count == 0 and exchange_count == 0 and timing_count == 0:
            return {}
        return {
            "usage_total": usage_total,
            "usage_count": usage_count,
            "by_model": by_model,
            "by_stage": by_stage,
            "exchange_count": exchange_count,
            "cache_hit_count": cache_hit_count,
            "runtime_response_cache_hit_count": runtime_response_cache_hit_count,
            "provider_prompt_cache_hit_count": provider_prompt_cache_hit_count,
            "timing_count": timing_count,
            "timing_by_stage": timing_by_stage,
            "slowest_step": slowest_step or {},
            "slowest_first_token": slowest_first_token or {},
            "latest_exchange": latest_exchange or {},
            "latest_usage": latest_usage or {},
        }

    def _normalize_usage_tokens(self, payload: dict[str, Any]) -> dict[str, int]:
        input_tokens = self._safe_non_negative_int(payload.get("input_tokens"), payload.get("prompt_tokens"))
        output_tokens = self._safe_non_negative_int(payload.get("output_tokens"), payload.get("completion_tokens"))
        total_tokens = self._safe_non_negative_int(payload.get("total_tokens"))
        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cached_tokens": self._safe_non_negative_int(payload.get("cached_tokens")),
            "cache_read_input_tokens": self._safe_non_negative_int(payload.get("cache_read_input_tokens")),
        }

    def _add_llm_usage_bucket(
        self,
        buckets: dict[str, dict[str, Any]],
        key: str,
        usage: dict[str, int],
    ) -> None:
        bucket = buckets.setdefault(
            key,
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cached_tokens": 0,
                "cache_read_input_tokens": 0,
                "usage_count": 0,
            },
        )
        for field in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "cache_read_input_tokens"):
            bucket[field] += usage[field]
        bucket["usage_count"] += 1

    @staticmethod
    def _safe_non_negative_float(*values: Any) -> float:
        for value in values:
            if value is None or isinstance(value, bool):
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            return max(parsed, 0.0)
        return 0.0

    @staticmethod
    def _safe_non_negative_int(*values: Any) -> int:
        for value in values:
            if value is None or isinstance(value, bool):
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            return max(parsed, 0)
        return 0

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
