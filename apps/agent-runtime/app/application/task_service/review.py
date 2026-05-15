from __future__ import annotations

from app.observability import get_logger


from app.domain.models import (
    ChapterDraft,
    OutlineBatchInfo,
    ReviewPayload,
    TaskRecord,
    TaskStatus,
)
from app.storage import db_repository

logger = get_logger(__name__)

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

            from app.storage import db_repository

            outline_batch = task.pending_review.outline_batch if task.pending_review else None
            phase = outline_batch.phase if outline_batch else "master"

            if phase == "master":
                # 总纲通过，进入章节计划批次生成
                task.story_plan = story_plan
                self._ensure_novel_project_seeded(task)
                batch_size = outline_batch.batch_size if outline_batch else 20
                task.pending_review.outline_batch = OutlineBatchInfo(
                    phase="chapter_batches",
                    completed_count=0,
                    batch_index=0,
                    batch_size=batch_size,
                    total_count=story_plan.planned_chapter_count or 0,
                )
                self.store.save(task)
                snapshot = self.store.set_waiting_review(task_id, task.pending_review, task.story_plan)
                snapshot = self._record_last_action(task_id, model_id=action_model_id, kind="resume")
                snapshot = self._sync_supervisor_plan(task_id)
                with self._run_lock:
                    if task_id in self._active_runs:
                        raise ValueError("任务正在运行中，请勿重复提交。")
                self._start_background(task_id, self._resume_task_sync, task_id, approved, comment, action_model_id)
                return snapshot

            # 章节计划批次通过
            batch_plans = outline_batch.current_batch_plans if outline_batch else []
            story_plan.chapter_plan.extend(batch_plans)
            completed = len(story_plan.chapter_plan)
            task.story_plan = story_plan

            total = story_plan.planned_chapter_count or completed
            batch_size = outline_batch.batch_size if outline_batch else 20
            batch_no = (outline_batch.batch_index // batch_size) + 1 if outline_batch else 1

            db_repository.mark_chapter_plan_batch_approved(task_id, batch_no)
            for plan in batch_plans:
                db_repository.upsert_outline_chapter_plan(
                    task_id=task_id,
                    chapter_number=plan.number,
                    title=plan.title,
                    goal=plan.goal,
                    outline_batch_no=batch_no,
                    status="outline_approved",
                )

            if completed >= total:
                self.store.save(task)
                snapshot = self.store.set_ready_for_batch(
                    task_id, story_plan,
                    message=comment.strip() or f"章节计划全部完成（{completed}章），等待继续创作。"
                )
                return self._safe_sync_supervisor_plan(task_id, fallback=snapshot)

            # 还有剩余，准备下一批
            outline_batch.completed_count = completed
            outline_batch.batch_index = completed
            outline_batch.current_batch_plans = []
            outline_batch.retry_count = 0
            self.store.save(task)

            # 同步 checkpoint 状态，避免 graph 恢复时使用旧的分批进度
            if hasattr(self.workflow_engine, "update_state"):
                try:
                    self.workflow_engine.update_state(self._config(task_id), {
                        "outline_completed_count": completed,
                        "outline_batch_index": completed,
                        "outline_batch_retry_count": 0,
                        "story_plan": task.story_plan.model_dump(mode="json"),
                    })
                except Exception as e:
                    logger.warning("同步 checkpoint 状态失败: %s", e)

            snapshot = self.store.set_waiting_review(task_id, task.pending_review, task.story_plan)
            snapshot = self._record_last_action(task_id, model_id=action_model_id, kind="resume")
            snapshot = self._sync_supervisor_plan(task_id)
            with self._run_lock:
                if task_id in self._active_runs:
                    raise ValueError("任务正在运行中，请勿重复提交。")
            self._start_background(task_id, self._resume_task_sync, task_id, approved, comment, action_model_id)
            return snapshot

        if review_type == "outline_review" and not approved:
            outline_batch = task.pending_review.outline_batch if task.pending_review else None
            if outline_batch is None:
                outline_batch = OutlineBatchInfo(phase="master")
                task.pending_review.outline_batch = outline_batch
            phase = outline_batch.phase
            if phase == "master":
                # 原有逻辑：进入 revise_outline
                snapshot = self.store.mark_stage(
                    task_id,
                    status=TaskStatus.PLANNING,
                    stage="planning",
                    progress=max(task.progress, 56),
                    message=comment.strip() or "人工审核已驳回，正在修订大纲。",
                    event_type="review.submitted",
                    unit_id="outline",
                )
            else:
                # 批次驳回：清空当前批次，保留已确认的 chapter_plan，重新生成
                batch_size = outline_batch.batch_size if outline_batch else 20
                batch_no = (outline_batch.batch_index // batch_size) + 1 if outline_batch else 1
                db_repository.mark_chapter_plan_batch_rejected(task_id, batch_no)
                db_repository.delete_outline_chapter_plans_by_batch(task_id, batch_no)
                outline_batch.current_batch_plans = []
                self.store.save(task)
                snapshot = self.store.set_waiting_review(task_id, task.pending_review, task.story_plan)
            snapshot = self._record_last_action(task_id, model_id=action_model_id, kind="resume")
            snapshot = self._sync_supervisor_plan(task_id)
            self._start_background(task_id, self._resume_task_sync, task_id, approved, comment, action_model_id)
            return snapshot

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
                # 兜底：若数据库中缺失批次记录（例如旧流程或未正常创建），根据 pending_review 自动重建
                from app.storage.db_repository import create_batch
                batch = create_batch(
                    task_id,
                    continue_request_id=task.current_unit or f"recovered-{task_id}",
                    requested_count=len(chapter_numbers),
                    effective_count=len(chapter_numbers),
                    actual_start_chapter=min(chapter_numbers) if chapter_numbers else 1,
                )
                logger.warning("任务 %s 审核时缺失批次记录，已自动重建 batch_no=%s", task_id, batch.batch_no)
            project = get_novel_project(task_id)
            if project is None:
                raise ValueError("当前任务缺少小说项目记录。")
            if approved:
                mark_outline_chapters_approved(task_id, chapter_numbers)
                mark_batch_approved(task_id, batch.batch_no)
                approved_count = count_approved_chapters(task_id)
                current_completed = int(project.completed_chapter_count or 0)
                batch_end = int(batch.actual_end_chapter or 0)
                chapter_end = max(chapter_numbers) if chapter_numbers else 0
                completed_count = max(current_completed, approved_count, batch_end, chapter_end)
                planned_total = int(project.planned_chapter_count or 0)
                if planned_total > 0:
                    completed_count = min(completed_count, planned_total)
                next_chapter_number = completed_count + 1
                if planned_total > 0 and completed_count >= planned_total:
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
        with self._run_lock:
            if task_id in self._active_runs:
                raise ValueError("任务正在运行中，请勿重复提交。")
        self._start_background(task_id, self._resume_task_sync, task_id, approved, comment, action_model_id)
        return snapshot

    def rollback_chapter_plan(self, task_id: str, keep_batch_count: int) -> TaskRecord:
        with self._run_lock:
            if task_id in self._active_runs:
                raise ValueError("任务正在后台运行中，请等待完成后再操作回滚。")

            task = self.store.get(task_id)

            if task.status is not TaskStatus.WAITING_OUTLINE_REVIEW:
                raise ValueError(f"当前任务状态为 {task.status.value}，不支持回滚操作。")

            story_plan = task.story_plan
            if not story_plan or not story_plan.chapter_plan:
                raise ValueError("当前没有可回滚的章节计划。")

            outline_batch = task.pending_review.outline_batch if task.pending_review else None
            batch_size = outline_batch.batch_size if outline_batch else 20
            keep_count = keep_batch_count * batch_size

            if keep_count >= len(story_plan.chapter_plan):
                raise ValueError("回滚位置必须早于当前进度。")

            current_confirmed = outline_batch.completed_count if outline_batch else 0
            current_batch_plans = outline_batch.current_batch_plans if outline_batch else []
            if keep_count == current_confirmed and not current_batch_plans:
                return task

            # 数据库回滚 + JSON 截断（同一事务语义：先 DB 操作，再内存修改）
            db_repository.delete_outline_chapter_plans_after(task_id, keep_count)
            db_repository.delete_chapter_plan_batches_after(task_id, keep_batch_count)

            story_plan.chapter_plan = story_plan.chapter_plan[:keep_count]
            task.story_plan = story_plan

            if outline_batch:
                outline_batch.completed_count = keep_count
                outline_batch.batch_index = keep_count
                outline_batch.current_batch_plans = []
                outline_batch.retry_count = 0
            self.store.save(task)

            return self.store.set_waiting_review(task_id, task.pending_review, task.story_plan)
