"""数据库仓库层 — 任务索引的 upsert 操作。"""

from __future__ import annotations

import logging

from app.domain.models import TaskRecord

logger = logging.getLogger(__name__)


def upsert_task_index(task: TaskRecord) -> None:
    """将任务元数据写入（或更新）索引表。"""
    title = (
        task.story_plan.working_title
        if task.story_plan
        else (task.input.title_hint or task.input.prompt[:24] or task.id)
    )    with get_session() as session:
        row = session.query(TaskIndexModel).filter_by(id=task.id).first()
        if row is None:
            row = TaskIndexModel(id=task.id)
            session.add(row)
            session.flush()
        row.mode = task.mode.value
        row.model_id = task.model_id
        row.status = task.status.value
        row.current_stage = task.current_stage
        row.progress = task.progress
        row.title = title
        row.storage_state = task.storage_state
        row.auto_review = task.auto_review
        row.created_at = task.created_at
        row.updated_at = task.updated_at
        session.commit()
