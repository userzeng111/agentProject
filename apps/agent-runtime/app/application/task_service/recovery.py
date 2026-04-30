from __future__ import annotations

import json
from app.observability import get_logger
from typing import Any


from app.domain.models import (
    ChapterDraft,
    RecoveryOption,
    RecoveryPreview,
    ReviewPayload,
    StoryPlan,
    TaskMode,
    TaskRecord,
    TaskStatus,
)
from app.graph.main_graph import (
    _build_references,
    _chapter_pair_instruction,
    _outline_instruction,
    _resolve_model_profile,
)

logger = get_logger(__name__)

_STAGE_LABELS: dict[str, str] = {
    TaskStatus.WAITING_OUTLINE_REVIEW.value: "待大纲审核",
    TaskStatus.READY_FOR_BATCH.value: "可继续创作",
    TaskStatus.WAITING_CHAPTER_REVIEW.value: "待章节审核",
    TaskStatus.WAITING_VERIFICATION_REVIEW.value: "待验证审核",
    TaskStatus.PLANNING.value: "重新进入规划",
}


class TaskServiceRecoveryMixin:

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
        elif task.status is TaskStatus.WAITING_CHAPTER_REVIEW and self._can_recover_chapter_review(task):
            if (
                task.pending_review is not None
                and task.pending_review.type == "chapter_pair_review"
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
            else:
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
                if not target_stage and project is not None and int(project.completed_chapter_count or 0) > 0 and task.story_plan is not None:
                    target_stage = TaskStatus.READY_FOR_BATCH.value
                    next_chapter = int(project.next_chapter_number or (int(project.completed_chapter_count or 0) + 1))
                    target_chapter_number = next_chapter if next_chapter > 0 else None
            if not target_stage:
                history_resume = self._history_ready_resume_state(task)
                if history_resume is not None:
                    story_plan, completed_chapters = history_resume
                    completed_count = len(completed_chapters)
                    total_chapters = int(story_plan.planned_chapter_count or len(story_plan.chapter_plan))
                    target_stage = TaskStatus.READY_FOR_BATCH.value
                    if completed_count < total_chapters:
                        target_chapter_number = completed_count + 1
            if not target_stage:
                if self._can_recover_verification_review(task):
                    target_stage = TaskStatus.WAITING_VERIFICATION_REVIEW.value
                elif self._can_recover_chapter_review(task):
                    target_stage = TaskStatus.WAITING_CHAPTER_REVIEW.value
                    target_chapter_numbers = [
                        int(ch.number if isinstance(ch, ChapterDraft) else ch.get("number"))
                        for ch in (task.pending_review.chapter_pair or [])
                        if (isinstance(ch, ChapterDraft) and ch.number) or (isinstance(ch, dict) and ch.get("number"))
                    ]
                    target_chapter_number = target_chapter_numbers[-1] if target_chapter_numbers else None
                elif self._can_recover_outline_review(task):
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
        elif target_stage == TaskStatus.READY_FOR_BATCH.value and target_chapter_number is not None:
            target_stage_label = f"恢复到可继续创作（下一章：第 {target_chapter_number} 章）"

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
        history_recovered = self._recover_ready_for_batch_from_history(task)
        if history_recovered is not None:
            return history_recovered
        if self._can_recover_outline_review(task):
            return self._recover_outline_review(task)
        if self._can_recover_chapter_review(task, force=force):
            return self._recover_chapter_review(task)
        if self._can_recover_verification_review(task, force=force):
            return self._recover_verification_review(task)
        return None

    def _history_ready_resume_state(self, task: TaskRecord) -> tuple[StoryPlan, list[dict[str, Any]]] | None:
        story_plan = task.story_plan or self._load_story_plan_from_history(task.id)
        if story_plan is None:
            return None
        completed_chapters = self._load_completed_chapters_until_gap(
            task.id,
            max_chapters=int(story_plan.planned_chapter_count or len(story_plan.chapter_plan) or 0),
        )
        if not completed_chapters:
            return None
        return story_plan, completed_chapters

    def _recover_ready_for_batch_from_history(self, task: TaskRecord) -> TaskRecord | None:
        if task.status is not TaskStatus.WAITING_MANUAL_ACTION or task.pending_review is not None:
            return None
        history_resume = self._history_ready_resume_state(task)
        if history_resume is None:
            return None

        story_plan, completed_chapters = history_resume
        completed_count = len(completed_chapters)
        next_chapter_number = completed_count + 1

        from app.storage.db_repository import (
            seed_outline_chapters,
            update_project_status,
            upsert_novel_project,
            upsert_outline_chapter_draft,
        )

        current_task = self.store.get(task.id)
        current_task.story_plan = story_plan
        self.store.save(current_task)
        upsert_novel_project(current_task, story_plan)
        seed_outline_chapters(task.id, story_plan)

        for chapter in completed_chapters:
            chapter_number = int(chapter.get("number") or 0)
            if chapter_number <= 0:
                continue
            title = str(chapter.get("title") or f"第{chapter_number}章")
            summary = str(chapter.get("summary") or "")
            content = str(chapter.get("content") or "")
            self._write_chapter_file(
                task.id,
                chapter_number=chapter_number,
                title=title,
                summary=summary,
                content=content,
            )
            upsert_outline_chapter_draft(
                task.id,
                chapter_number=chapter_number,
                title=title,
                summary=summary,
                batch_no=0,
                md_ref=f"tasklog/runs/{task.id}/chapters/{chapter_number:02d}.md",
                json_ref=f"tasklog/runs/{task.id}/chapters/{chapter_number:02d}.json",
                content=content,
            )

        snapshot = self.store.set_ready_for_batch(
            task.id,
            story_plan,
            message=f"已从历史大纲和 {completed_count} 章章节快照恢复，可从第 {next_chapter_number} 章继续创作。",
        )
        update_project_status(
            task.id,
            status=TaskStatus.READY_FOR_BATCH.value,
            completed_chapter_count=completed_count,
            next_chapter_number=next_chapter_number,
            active_batch_no=None,
            active_continue_request_id="",
            blocked_from_status="",
            current_generating_chapter_number=None,
        )
        self.store.append_event(
            task.id,
            stage="ready_for_batch",
            message=f"已从历史快照重建大纲和前 {completed_count} 章，可继续生成第 {next_chapter_number} 章。",
            event_type="task.recovered",
            payload={
                "summary": f"任务已恢复到可继续创作，下一章为第 {next_chapter_number} 章。",
                "display_level": "public",
                "source": "outline_and_chapter_history",
                "completed_chapter_count": completed_count,
                "next_chapter_number": next_chapter_number,
            },
        )
        return self.store.save(self.store.get(snapshot.id))

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

        if (
            task.status is TaskStatus.WAITING_MANUAL_ACTION
            and task.story_plan is not None
            and project is not None
            and int(project.completed_chapter_count or 0) > 0
        ):
            snapshot = self.store.set_ready_for_batch(task.id, task.story_plan)
            update_project_status(
                task.id,
                status=TaskStatus.READY_FOR_BATCH.value,
                active_batch_no=None,
                active_continue_request_id="",
                blocked_from_status="",
                current_generating_chapter_number=None,
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
            if self._has_novel_project(task.id):
                from app.storage.db_repository import get_novel_project
                project = get_novel_project(task.id)
                if project is not None and int(project.completed_chapter_count or 0) > 0:
                    return False
            return task.pending_review is None and self._load_story_plan_from_history(task.id) is not None
        return (
            task.status is TaskStatus.PLANNING
            and str(task.current_unit or "").startswith("outline")
            and task.pending_review is None
            and task.story_plan is None
        )

    def _can_recover_chapter_review(self, task: TaskRecord, *, force: bool = False) -> bool:
        if task.pending_review is None or task.pending_review.type != "chapter_pair_review":
            return False
        if task.status not in {TaskStatus.WAITING_CHAPTER_REVIEW, TaskStatus.WAITING_MANUAL_ACTION}:
            return False
        if task.status is TaskStatus.WAITING_CHAPTER_REVIEW:
            return task.story_plan is None or force or self._chapter_pair_payload_is_dirty(task)
        return True

    def _can_recover_verification_review(self, task: TaskRecord, *, force: bool = False) -> bool:
        if task.pending_review is None or task.pending_review.type != "verification_review":
            return False
        if task.status not in {TaskStatus.WAITING_VERIFICATION_REVIEW, TaskStatus.WAITING_MANUAL_ACTION}:
            return False
        if task.status is TaskStatus.WAITING_VERIFICATION_REVIEW:
            return task.story_plan is None or force
        return True

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

    def _load_completed_chapters_until_gap(self, task_id: str, max_chapters: int = 0) -> list[dict[str, Any]]:
        upper_bound = max(int(max_chapters or 0), 0)
        if upper_bound <= 0:
            upper_bound = 1000
        items: list[dict[str, Any]] = []
        for number in range(1, upper_bound + 1):
            payload = self._load_chapter_draft_from_history(task_id, number)
            if payload is None:
                break
            chapter_number = int(payload.get("number") or number)
            if chapter_number != number:
                break
            items.append(payload)
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
            seed["auto_review_trace"] = [dict(item) for item in (task.auto_review_trace or [])]
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
                    "auto_review_trace": [dict(item) for item in (task.auto_review_trace or [])],
                }
            )
            references = _build_references(
                {
                    "reference_text": seed.get("reference_text", ""),
                    "source_assets": seed.get("source_assets", []),
                }
            )
            if self.rag_service is not None:
                chapter_batch_size = max(len(chapter_pair), 1)
                try:
                    chapter_result = self.rag_service.search_for_story_chapter(
                        spec=seed.get("normalized_spec") or {},
                        story_plan=seed.get("story_plan"),
                        batch_index=review.batch_index or 0,
                        batch_size=chapter_batch_size,
                        completed_chapters=completed_chapters,
                    )
                except TypeError:
                    chapter_result = self.rag_service.search_for_story_chapter(
                        spec=seed.get("normalized_spec") or {},
                        story_plan=seed.get("story_plan"),
                        batch_index=review.batch_index or 0,
                        completed_chapters=completed_chapters,
                    )
                references.extend(
                    self.rag_service.build_reference_materials(
                        chapter_result,
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
                    "auto_review_trace": [dict(item) for item in (task.auto_review_trace or [])],
                }
            )
            return seed, "verify_full_story"

        return None

    def _rehydrate_resume_state_if_needed(self, task: TaskRecord, action_model_id: str | None = None) -> None:
        values = self._graph_state_values(task.id)
        if not hasattr(self.workflow_engine, "update_state"):
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
            self.workflow_engine.update_state(self._config(task.id), patch)
        if values.get("input_payload"):
            return
        seeded = self._resume_seed_state(task, action_model_id)
        if seeded is None:
            return
        seed_values, as_node = seeded
        self.workflow_engine.update_state(self._config(task.id), seed_values, as_node=as_node)
