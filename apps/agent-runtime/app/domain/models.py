from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


class TaskMode(str, Enum):
    SHORT_STORY = "short_story"
    LONG_STORY = "long_story"
    FANFIC = "fanfic"
    STYLE_REMIX = "style_remix"


class TaskStatus(str, Enum):
    CREATED = "created"
    SOURCES_INGESTED = "sources_ingested"
    PLANNING = "planning"
    WAITING_OUTLINE_REVIEW = "waiting_outline_review"
    DRAFTING = "drafting"
    ASSEMBLING = "assembling"
    WAITING_MANUAL_ACTION = "waiting_manual_action"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TaskInput(BaseModel):
    prompt: str
    genre: str = ""
    style: str = ""
    target_words: int = 1800
    audience: str = ""
    banned: str = ""
    title_hint: str = ""


class TaskCreateRequest(TaskInput):
    mode: TaskMode


class ResumeRequest(BaseModel):
    approved: bool
    comment: str = ""


class SourceAsset(BaseModel):
    id: str = Field(default_factory=lambda: new_id("asset"))
    filename: str
    media_type: str = "text/plain"
    content: str
    uploaded_at: datetime = Field(default_factory=utc_now)


class ChapterPlan(BaseModel):
    number: int
    title: str
    goal: str


class StoryPlan(BaseModel):
    working_title: str
    logline: str
    world_notes: list[str] = Field(default_factory=list)
    character_notes: list[str] = Field(default_factory=list)
    chapter_plan: list[ChapterPlan] = Field(default_factory=list)


class ReviewPayload(BaseModel):
    type: str = "outline_review"
    version: str = "v1"
    summary: str
    story_plan: StoryPlan
    risk_flags: list[str] = Field(default_factory=list)


class ChapterDraft(BaseModel):
    number: int
    title: str
    summary: str
    content: str


class DraftResult(BaseModel):
    title: str
    summary: str
    body: str
    chapters: list[ChapterDraft] = Field(default_factory=list)


class ArtifactItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("artifact"))
    type: str
    name: str
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class TaskEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    event_type: str = "task.updated"
    at: datetime = Field(default_factory=utc_now)
    stage: str
    message: str
    unit_id: str | None = None
    md_ref: str | None = None
    json_ref: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    mode: TaskMode
    status: TaskStatus = TaskStatus.CREATED
    current_stage: str = "created"
    current_unit: str | None = None
    progress: int = 0
    input: TaskInput
    sources: list[SourceAsset] = Field(default_factory=list)
    normalized_spec: dict[str, Any] = Field(default_factory=dict)
    story_plan: StoryPlan | None = None
    pending_review: ReviewPayload | None = None
    draft_result: DraftResult | None = None
    artifacts: list[ArtifactItem] = Field(default_factory=list)
    events: list[TaskEvent] = Field(default_factory=list)
    error_message: str | None = None
    storage_state: str = "runs"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
