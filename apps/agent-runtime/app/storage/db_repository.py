"""数据库仓库层。"""

from __future__ import annotations

import hashlib
from app.observability import get_logger
from pathlib import Path

from app.domain.models import StoryPlan, TaskRecord, utc_now
from app.storage.database import get_session
from app.storage.db_models import (
    NovelChapterPlanBatchModel,
    NovelGenerationBatchModel,
    NovelOutlineChapterModel,
    NovelProjectModel,
    TaskIndexModel,
)

logger = get_logger(__name__)
_UNSET = object()


def _task_title(task: TaskRecord) -> str:
    return (
        task.story_plan.working_title
        if task.story_plan
        else (task.input.title_hint or task.input.prompt[:24] or task.id)
    )


def upsert_task_index(task: TaskRecord) -> None:
    """将任务元数据写入（或更新）索引表。"""
    creative_mode = task.creative_mode.value if task.creative_mode else ""
    novel_size = task.novel_size.value if task.novel_size else ""
    chapter_word_min = int(task.chapter_word_min or task.input.target_words or 1800)
    with get_session() as session:
        row = session.query(TaskIndexModel).filter_by(id=task.id).first()
        if row is None:
            row = TaskIndexModel(id=task.id)
            session.add(row)
        row.mode = task.mode.value
        row.creative_mode = creative_mode
        row.novel_size = novel_size
        row.chapter_word_min = chapter_word_min
        row.model_id = task.model_id
        row.status = task.status.value
        row.current_stage = task.current_stage
        row.progress = task.progress
        row.title = _task_title(task)
        row.storage_state = task.storage_state
        row.auto_review = bool(task.auto_review)
        row.created_at = task.created_at
        row.updated_at = task.updated_at
        session.commit()


def delete_task_index(task_id: str) -> None:
    """从索引表中删除指定任务的记录。"""
    with get_session() as session:
        row = session.query(TaskIndexModel).filter_by(id=task_id).first()
        if row is not None:
            session.delete(row)
            session.commit()


def get_novel_project(task_id: str) -> NovelProjectModel | None:
    with get_session() as session:
        return session.query(NovelProjectModel).filter_by(task_id=task_id).first()


def upsert_novel_project(task: TaskRecord, story_plan: StoryPlan | None = None) -> NovelProjectModel:
    active_plan = story_plan or task.story_plan
    if active_plan is None:
        raise ValueError("当前任务缺少 story_plan，无法初始化小说项目。")
    with get_session() as session:
        row = session.query(NovelProjectModel).filter_by(task_id=task.id).first()
        if row is None:
            row = NovelProjectModel(task_id=task.id, created_at=task.created_at, updated_at=task.updated_at)
            session.add(row)
        row.novel_title = active_plan.working_title
        row.creative_mode = task.creative_mode.value if task.creative_mode else ""
        row.novel_size = task.novel_size.value if task.novel_size else ""
        row.target_chapter_count = int(task.target_chapter_count or task.input.target_chapter_count or 0)
        row.chapter_count_min = int(task.chapter_count_min or task.input.chapter_count_min)
        row.chapter_count_max = int(task.chapter_count_max or task.input.chapter_count_max)
        row.planned_chapter_count = int(active_plan.planned_chapter_count or len(active_plan.chapter_plan))
        row.chapter_word_min = int(task.chapter_word_min or task.input.target_words or 1800)
        row.chapter_word_max = max(int(row.chapter_word_min * 1.3), row.chapter_word_min)
        row.default_batch_size = 3
        row.completed_chapter_count = int(row.completed_chapter_count or 0)
        row.next_chapter_number = max(row.completed_chapter_count + 1, 1)
        if row.current_generating_chapter_number is not None and row.current_generating_chapter_number <= 0:
            row.current_generating_chapter_number = None
        if not row.status:
            row.status = task.status.value
        row.updated_at = utc_now()
        session.commit()
        session.refresh(row)
        return row


def seed_outline_chapters(task_id: str, story_plan: StoryPlan) -> None:
    now = utc_now()
    with get_session() as session:
        existing = {
            row.chapter_number: row
            for row in session.query(NovelOutlineChapterModel).filter_by(task_id=task_id).all()
        }
        for chapter in story_plan.chapter_plan:
            row = existing.get(chapter.number)
            if row is None:
                row = NovelOutlineChapterModel(
                    task_id=task_id,
                    chapter_number=chapter.number,
                    updated_at=now,
                )
                session.add(row)
            row.title = chapter.title
            row.goal = chapter.goal
            if not row.status:
                row.status = "planned"
            row.updated_at = now
        session.commit()


def list_outline_chapters(task_id: str) -> list[NovelOutlineChapterModel]:
    with get_session() as session:
        return (
            session.query(NovelOutlineChapterModel)
            .filter_by(task_id=task_id)
            .order_by(NovelOutlineChapterModel.chapter_number.asc())
            .all()
        )


def get_outline_chapter(task_id: str, chapter_number: int) -> NovelOutlineChapterModel | None:
    with get_session() as session:
        return (
            session.query(NovelOutlineChapterModel)
            .filter_by(task_id=task_id, chapter_number=chapter_number)
            .first()
        )


def upsert_outline_chapter_draft(
    task_id: str,
    *,
    chapter_number: int,
    title: str,
    summary: str,
    batch_no: int,
    md_ref: str,
    json_ref: str,
    content: str,
) -> None:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    file_size = len(content.encode("utf-8"))
    now = utc_now()
    with get_session() as session:
        row = (
            session.query(NovelOutlineChapterModel)
            .filter_by(task_id=task_id, chapter_number=chapter_number)
            .first()
        )
        if row is None:
            row = NovelOutlineChapterModel(
                task_id=task_id,
                chapter_number=chapter_number,
                updated_at=now,
            )
            session.add(row)
        row.title = title
        row.summary = summary
        row.batch_no = batch_no
        row.status = "drafted"
        row.md_ref = md_ref
        row.json_ref = json_ref
        row.content_hash = digest
        row.file_size = file_size
        row.artifact_state = "present"
        row.file_checked_at = now
        row.updated_at = now
        session.commit()


def mark_outline_chapters_approved(task_id: str, chapter_numbers: list[int]) -> None:
    now = utc_now()
    with get_session() as session:
        rows = (
            session.query(NovelOutlineChapterModel)
            .filter(
                NovelOutlineChapterModel.task_id == task_id,
                NovelOutlineChapterModel.chapter_number.in_(chapter_numbers),
            )
            .all()
        )
        for row in rows:
            row.status = "approved"
            row.updated_at = now
        session.commit()


def create_batch(
    task_id: str,
    *,
    continue_request_id: str,
    requested_count: int,
    effective_count: int,
    actual_start_chapter: int,
) -> NovelGenerationBatchModel:
    now = utc_now()
    with get_session() as session:
        existing = (
            session.query(NovelGenerationBatchModel)
            .filter_by(task_id=task_id, continue_request_id=continue_request_id)
            .first()
        )
        if existing is not None:
            return existing
        latest = (
            session.query(NovelGenerationBatchModel)
            .filter_by(task_id=task_id)
            .order_by(NovelGenerationBatchModel.batch_no.desc())
            .first()
        )
        batch_no = (latest.batch_no + 1) if latest is not None else 1
        row = NovelGenerationBatchModel(
            task_id=task_id,
            batch_no=batch_no,
            continue_request_id=continue_request_id,
            requested_count=requested_count,
            effective_count=effective_count,
            actual_start_chapter=actual_start_chapter,
            expected_end_chapter=actual_start_chapter + effective_count - 1,
            persisted_count=0,
            status="drafting",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def get_batch_by_request(task_id: str, continue_request_id: str) -> NovelGenerationBatchModel | None:
    with get_session() as session:
        return (
            session.query(NovelGenerationBatchModel)
            .filter_by(task_id=task_id, continue_request_id=continue_request_id)
            .first()
        )


def get_active_batch(task_id: str) -> NovelGenerationBatchModel | None:
    with get_session() as session:
        return (
            session.query(NovelGenerationBatchModel)
            .filter(
                NovelGenerationBatchModel.task_id == task_id,
                NovelGenerationBatchModel.status.in_(["created", "drafting", "waiting_review"]),
            )
            .order_by(NovelGenerationBatchModel.batch_no.desc())
            .first()
        )


def get_batch(task_id: str, batch_no: int) -> NovelGenerationBatchModel | None:
    with get_session() as session:
        return session.query(NovelGenerationBatchModel).filter_by(task_id=task_id, batch_no=batch_no).first()


def mark_batch_waiting_review(task_id: str, batch_no: int, *, persisted_count: int) -> NovelGenerationBatchModel | None:
    now = utc_now()
    with get_session() as session:
        row = session.query(NovelGenerationBatchModel).filter_by(task_id=task_id, batch_no=batch_no).first()
        if row is None:
            return None
        row.persisted_count = persisted_count
        row.actual_end_chapter = (
            row.actual_start_chapter + persisted_count - 1 if persisted_count > 0 else None
        )
        row.status = "waiting_review"
        row.updated_at = now
        row.finished_at = now
        session.commit()
        session.refresh(row)
        return row


def mark_batch_approved(task_id: str, batch_no: int) -> None:
    now = utc_now()
    with get_session() as session:
        row = session.query(NovelGenerationBatchModel).filter_by(task_id=task_id, batch_no=batch_no).first()
        if row is None:
            return
        row.status = "approved"
        row.updated_at = now
        row.finished_at = now
        row.claim_token = ""
        session.commit()


def mark_batch_rejected(task_id: str, batch_no: int) -> None:
    now = utc_now()
    with get_session() as session:
        row = session.query(NovelGenerationBatchModel).filter_by(task_id=task_id, batch_no=batch_no).first()
        if row is None:
            return
        row.status = "rejected"
        row.updated_at = now
        row.finished_at = now
        row.claim_token = ""
        session.commit()


def mark_batch_failed(task_id: str, batch_no: int) -> None:
    now = utc_now()
    with get_session() as session:
        row = session.query(NovelGenerationBatchModel).filter_by(task_id=task_id, batch_no=batch_no).first()
        if row is None:
            return
        row.status = "failed"
        row.updated_at = now
        row.finished_at = now
        row.claim_token = ""
        session.commit()


def update_project_status(
    task_id: str,
    *,
    status: str,
    completed_chapter_count: int | None = None,
    next_chapter_number: int | None = None,
    active_batch_no: int | None = None,
    active_continue_request_id: str | None = None,
    blocked_from_status: str | None = None,
    current_generating_chapter_number: int | None | object = _UNSET,
) -> None:
    with get_session() as session:
        row = session.query(NovelProjectModel).filter_by(task_id=task_id).first()
        if row is None:
            return
        row.status = status
        if completed_chapter_count is not None:
            row.completed_chapter_count = completed_chapter_count
        if next_chapter_number is not None:
            row.next_chapter_number = next_chapter_number
        row.active_batch_no = active_batch_no
        row.active_continue_request_id = active_continue_request_id or ""
        if blocked_from_status is not None:
            row.blocked_from_status = blocked_from_status
        if current_generating_chapter_number is not _UNSET:
            row.current_generating_chapter_number = (
                int(current_generating_chapter_number)
                if isinstance(current_generating_chapter_number, int) and current_generating_chapter_number > 0
                else None
            )
        row.updated_at = utc_now()
        session.commit()


def mark_outline_chapter_manual_action(task_id: str, chapter_number: int, artifact_state: str) -> None:
    with get_session() as session:
        row = (
            session.query(NovelOutlineChapterModel)
            .filter_by(task_id=task_id, chapter_number=chapter_number)
            .first()
        )
        if row is None:
            return
        row.artifact_state = artifact_state
        row.updated_at = utc_now()
        session.commit()


def count_approved_chapters(task_id: str) -> int:
    with get_session() as session:
        return (
            session.query(NovelOutlineChapterModel)
            .filter_by(task_id=task_id, status="approved")
            .count()
        )


def read_file_content_hash(path: Path) -> tuple[str, int]:
    raw = path.read_text(encoding="utf-8")
    try:
        payload = __import__("json").loads(raw)
    except Exception:
        payload = {}
    content = str(payload.get("content") or raw)
    return hashlib.sha256(content.encode("utf-8")).hexdigest(), len(content.encode("utf-8"))


# ── 章节计划批次管理 ──

def create_chapter_plan_batch(
    task_id: str,
    batch_no: int,
    start_chapter: int,
    end_chapter: int,
    requested_count: int,
    effective_count: int,
    status: str = "planned",
) -> NovelChapterPlanBatchModel:
    now = utc_now()
    with get_session() as session:
        row = NovelChapterPlanBatchModel(
            task_id=task_id,
            batch_no=batch_no,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            requested_count=requested_count,
            effective_count=effective_count,
            status=status,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def get_chapter_plan_batch(task_id: str, batch_no: int) -> NovelChapterPlanBatchModel | None:
    with get_session() as session:
        return (
            session.query(NovelChapterPlanBatchModel)
            .filter_by(task_id=task_id, batch_no=batch_no)
            .first()
        )


def mark_chapter_plan_batch_approved(task_id: str, batch_no: int) -> None:
    now = utc_now()
    with get_session() as session:
        row = (
            session.query(NovelChapterPlanBatchModel)
            .filter_by(task_id=task_id, batch_no=batch_no)
            .first()
        )
        if row is not None:
            row.status = "approved"
            row.approved_at = now
            row.updated_at = now
            session.commit()


def mark_chapter_plan_batch_rejected(task_id: str, batch_no: int) -> None:
    now = utc_now()
    with get_session() as session:
        row = (
            session.query(NovelChapterPlanBatchModel)
            .filter_by(task_id=task_id, batch_no=batch_no)
            .first()
        )
        if row is not None:
            row.status = "rejected"
            row.rejected_at = now
            row.updated_at = now
            session.commit()


def delete_chapter_plan_batches_after(task_id: str, keep_batch_count: int) -> None:
    with get_session() as session:
        session.query(NovelChapterPlanBatchModel).filter(
            NovelChapterPlanBatchModel.task_id == task_id,
            NovelChapterPlanBatchModel.batch_no > keep_batch_count,
        ).delete(synchronize_session=False)
        session.commit()


def get_chapter_plan_batch_summary(task_id: str) -> dict[str, Any] | None:
    with get_session() as session:
        approved_batches = (
            session.query(NovelChapterPlanBatchModel)
            .filter_by(task_id=task_id, status="approved")
            .order_by(NovelChapterPlanBatchModel.batch_no.asc())
            .all()
        )
        if not approved_batches:
            return None
        # 取最常见 requested_count 作为 batch_size（用户配置一次确定后不变）
        requested_counts = [b.requested_count for b in approved_batches]
        batch_size = max(set(requested_counts), key=requested_counts.count)
        approved_count = sum(b.effective_count for b in approved_batches)
        # total_count 取最大 end_chapter
        total_count = max(b.end_chapter for b in approved_batches)
        return {
            "approved_count": approved_count,
            "batch_size": batch_size,
            "total_count": total_count,
        }


def upsert_outline_chapter_plan(
    task_id: str,
    chapter_number: int,
    title: str,
    goal: str,
    outline_batch_no: int,
    status: str = "outline_planned",
) -> None:
    now = utc_now()
    with get_session() as session:
        # 先删除同 task_id + chapter_number 的旧记录，确保无残留
        session.query(NovelOutlineChapterModel).filter(
            NovelOutlineChapterModel.task_id == task_id,
            NovelOutlineChapterModel.chapter_number == chapter_number,
        ).delete(synchronize_session=False)
        row = NovelOutlineChapterModel(
            task_id=task_id,
            chapter_number=chapter_number,
            title=title,
            goal=goal,
            outline_batch_no=outline_batch_no,
            status=status,
            updated_at=now,
        )
        session.add(row)
        session.commit()


def delete_outline_chapter_plans_after(task_id: str, keep_count: int) -> None:
    with get_session() as session:
        session.query(NovelOutlineChapterModel).filter(
            NovelOutlineChapterModel.task_id == task_id,
            NovelOutlineChapterModel.chapter_number > keep_count,
        ).delete(synchronize_session=False)
        session.commit()


def delete_outline_chapter_plans_by_batch(task_id: str, batch_no: int) -> None:
    with get_session() as session:
        session.query(NovelOutlineChapterModel).filter(
            NovelOutlineChapterModel.task_id == task_id,
            NovelOutlineChapterModel.outline_batch_no == batch_no,
        ).delete(synchronize_session=False)
        session.commit()
