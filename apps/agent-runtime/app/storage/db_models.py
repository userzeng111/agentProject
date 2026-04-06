"""SQLAlchemy ORM 模型定义 — 任务索引表。

仅存储 ID、标题、状态等元数据，正文内容留在文件系统。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.database import Base


class TaskIndexModel(Base):
    __tablename__ = "tasks_index"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_stage: Mapped[str] = mapped_column(String(64), default="created", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(512), default="")
    storage_state: Mapped[str] = mapped_column(String(16), default="runs", index=True)
    auto_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
