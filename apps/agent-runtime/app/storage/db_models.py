"""SQLAlchemy ORM 模型 — 任务索引表。

仅存储 ID、标题、状态等元数据，正文内容留在文件系统。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.database import Base


class TaskIndexModel(Base):
    __tablename__ = "tasks_index"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    creative_mode: Mapped[str] = mapped_column(String(32), default="")
    novel_size: Mapped[str] = mapped_column(String(16), default="")
    chapter_word_min: Mapped[int] = mapped_column(Integer, default=1800)
    model_id: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_stage: Mapped[str] = mapped_column(String(64), default="created", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(512), default="")
    storage_state: Mapped[str] = mapped_column(String(16), default="runs", index=True)
    auto_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class NovelProjectModel(Base):
    __tablename__ = "novel_project"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    novel_title: Mapped[str] = mapped_column(String(512), default="")
    creative_mode: Mapped[str] = mapped_column(String(32), default="")
    novel_size: Mapped[str] = mapped_column(String(16), default="")
    target_chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    chapter_count_min: Mapped[int] = mapped_column(Integer, default=0)
    chapter_count_max: Mapped[int] = mapped_column(Integer, default=0)
    planned_chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    chapter_word_min: Mapped[int] = mapped_column(Integer, default=1800)
    chapter_word_max: Mapped[int] = mapped_column(Integer, default=1800)
    default_batch_size: Mapped[int] = mapped_column(Integer, default=3)
    completed_chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    next_chapter_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(64), default="created", index=True)
    active_batch_no: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    active_continue_request_id: Mapped[str] = mapped_column(String(128), default="")
    blocked_from_status: Mapped[str] = mapped_column(String(64), default="")
    last_checkpoint_stage: Mapped[str] = mapped_column(String(64), default="")
    last_consistency_state: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class NovelOutlineChapterModel(Base):
    __tablename__ = "novel_outline_chapter"
    __table_args__ = (
        UniqueConstraint("task_id", "chapter_number", name="uq_novel_outline_task_chapter"),
        Index("ix_novel_outline_task_status", "task_id", "status"),
        Index("ix_novel_outline_task_artifact_state", "task_id", "artifact_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="")
    goal: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[str] = mapped_column(String(32), default="planned")
    batch_no: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    summary: Mapped[str] = mapped_column(String(1024), default="")
    md_ref: Mapped[str] = mapped_column(String(512), default="")
    json_ref: Mapped[str] = mapped_column(String(512), default="")
    content_hash: Mapped[str] = mapped_column(String(128), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    artifact_state: Mapped[str] = mapped_column(String(32), default="pending")
    file_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class NovelGenerationBatchModel(Base):
    __tablename__ = "novel_generation_batch"
    __table_args__ = (
        UniqueConstraint("task_id", "batch_no", name="uq_novel_batch_task_no"),
        UniqueConstraint("task_id", "continue_request_id", name="uq_novel_batch_task_request"),
        Index("ix_novel_batch_task_status", "task_id", "status"),
        Index("ix_novel_batch_task_created_at", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    continue_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, default=0)
    effective_count: Mapped[int] = mapped_column(Integer, default=0)
    actual_start_chapter: Mapped[int] = mapped_column(Integer, default=1)
    expected_end_chapter: Mapped[int] = mapped_column(Integer, default=1)
    actual_end_chapter: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    persisted_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="created")
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    claim_token: Mapped[str] = mapped_column(String(128), default="")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    error_code: Mapped[str] = mapped_column(String(128), default="")
    error_message: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
