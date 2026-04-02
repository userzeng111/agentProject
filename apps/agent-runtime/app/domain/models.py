from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, Field


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
    WAITING_CHAPTER_REVIEW = "waiting_chapter_review"
    WAITING_VERIFICATION_REVIEW = "waiting_verification_review"
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
    model_id: str | None = Field(default=None, validation_alias=AliasChoices("model_id", "model"))


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
    # 三种审核类型: outline_review | chapter_pair_review | verification_review
    type: str = "outline_review"
    version: str = "v1"
    summary: str
    story_plan: StoryPlan | None = None
    risk_flags: list[str] = Field(default_factory=list)
    # 大纲修订计数
    revision_count: int = 0
    # 章节对审核时
    batch_index: int | None = None
    chapter_pair: list[ChapterDraft] | None = None
    completed_count: int | None = None
    total_chapters: int | None = None
    chapter_pair_revision_count: int = 0
    # 验证审核时
    verification_report: dict[str, Any] | None = None
    verification_revision_count: int = 0


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
    task_id: str | None = None
    event_type: str = "task.updated"
    created_at: datetime = Field(default_factory=utc_now, validation_alias=AliasChoices("created_at", "at"))
    stage: str
    message: str
    unit_id: str | None = None
    md_ref: str | None = None
    json_ref: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    mode: TaskMode
    model_id: str = Field(default="", validation_alias=AliasChoices("model_id", "model"))
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


class TaskSummary(BaseModel):
    task_id: str
    title: str
    mode: TaskMode
    model_id: str
    model_capabilities: dict[str, Any] | None = None
    status: TaskStatus
    current_stage: str
    current_unit: str | None = None
    progress: int
    updated_at: datetime
    summary: str
    storage_state: str


class DashboardResponse(BaseModel):
    continue_tasks: list[TaskSummary]
    running_tasks: list[TaskSummary]
    failed_tasks: list[TaskSummary]
    model_summary: dict[str, Any]
    system_summary: dict[str, Any]
    continue_total: int = 0
    running_total: int = 0
    failed_total: int = 0


class WorkspaceResponse(BaseModel):
    meta: TaskSummary
    recent_events: list[TaskEvent]
    active_trace_summary: str | None = None
    available_tabs: list[str] = Field(default_factory=list)
    request_preview: dict[str, Any] = Field(default_factory=dict)
    context_status: dict[str, Any] = Field(default_factory=dict)
    response_cache_status: dict[str, Any] = Field(default_factory=dict)
    sources: list[SourceAsset] = Field(default_factory=list)


class ReviewResponse(BaseModel):
    meta: TaskSummary
    review_type: str
    review_version: str
    summary: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    outline_markdown: str | None = None
    outline_md_ref: str | None = None
    review_history: list[dict[str, Any]] = Field(default_factory=list)
    # 章节对审核
    chapter_pair: list[dict[str, Any]] = Field(default_factory=list)
    batch_index: int | None = None
    completed_count: int | None = None
    total_chapters: int | None = None
    chapter_pair_revision_count: int = 0
    # 验证审核
    verification_report: dict[str, Any] | None = None
    verification_revision_count: int = 0


class ResultResponse(BaseModel):
    meta: TaskSummary
    result_summary: str | None = None
    result_markdown: str | None = None
    result_md_ref: str | None = None
    chapter_index: list[dict[str, Any]] = Field(default_factory=list)
    artifact_index: list[dict[str, Any]] = Field(default_factory=list)
    history_index: list[dict[str, Any]] = Field(default_factory=list)


class ArchiveTaskListResponse(BaseModel):
    items: list[TaskSummary] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10
    total_pages: int = 0


class ArchiveTaskDetailResponse(BaseModel):
    meta: TaskSummary
    request_preview: dict[str, Any] = Field(default_factory=dict)
    sources: list[SourceAsset] = Field(default_factory=list)
    recent_events: list[TaskEvent] = Field(default_factory=list)
    result_summary: str | None = None
    result_markdown: str | None = None
    result_md_ref: str | None = None
    chapter_index: list[dict[str, Any]] = Field(default_factory=list)
    artifact_index: list[dict[str, Any]] = Field(default_factory=list)
    history_index: list[dict[str, Any]] = Field(default_factory=list)
