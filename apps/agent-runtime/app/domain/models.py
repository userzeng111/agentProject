from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


class TaskMode(str, Enum):
    SHORT_STORY = "short_story"
    LONG_STORY = "long_story"
    FANFIC = "fanfic"
    STYLE_REMIX = "style_remix"


class CreativeMode(str, Enum):
    ORIGINAL = "original"
    FANFIC = "fanfic"
    STYLE_REMIX = "style_remix"


class NovelSize(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class AutoReviewModelMode(str, Enum):
    FOLLOW_CREATIVE = "follow_creative"
    FIXED = "fixed"


class TaskStatus(str, Enum):
    CREATED = "created"
    SOURCES_INGESTED = "sources_ingested"
    PLANNING = "planning"
    WAITING_OUTLINE_REVIEW = "waiting_outline_review"
    READY_FOR_BATCH = "ready_for_batch"
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
    style_profile_id: str = ""
    creative_mode: CreativeMode | None = None
    novel_size: NovelSize | None = None
    target_chapter_count: int | None = None
    chapter_word_min: int | None = Field(default=None, validation_alias=AliasChoices("chapter_word_min", "target_words"))
    audience: str = ""
    banned: str = ""
    title_hint: str = ""
    mode: TaskMode | None = Field(default=None, exclude=True, validation_alias=AliasChoices("mode", "legacy_mode"))

    @model_validator(mode="after")
    def _normalize_internal_fields(self) -> "TaskInput":
        if self.creative_mode is not None or self.novel_size is not None:
            self.mode = self._derive_mode()
        elif self.mode is None:
            self.mode = self._derive_mode()
        if self.creative_mode is None and self.mode is not None:
            self.creative_mode = self._derive_creative_mode(self.mode)
        if self.novel_size is None and self.mode is not None:
            self.novel_size = self._derive_novel_size(self.mode)
        if self.target_chapter_count is None:
            self.target_chapter_count = self._default_target_chapter_count(self.novel_size or NovelSize.SHORT)
        if self.chapter_word_min is None:
            self.chapter_word_min = 1800
        return self

    @property
    def target_words(self) -> int:
        return int(self.chapter_word_min or 1800)

    def _derive_mode(self) -> TaskMode:
        creative_mode = self.creative_mode or CreativeMode.ORIGINAL
        novel_size = self.novel_size or NovelSize.SHORT
        return self._resolve_mode(creative_mode, novel_size)

    @staticmethod
    def _resolve_mode(creative_mode: CreativeMode, novel_size: NovelSize) -> TaskMode:
        if creative_mode == CreativeMode.FANFIC:
            return TaskMode.FANFIC
        if creative_mode == CreativeMode.STYLE_REMIX:
            return TaskMode.STYLE_REMIX
        if novel_size == NovelSize.SHORT:
            return TaskMode.SHORT_STORY
        return TaskMode.LONG_STORY

    @staticmethod
    def _derive_creative_mode(mode: TaskMode) -> CreativeMode:
        if mode == TaskMode.FANFIC:
            return CreativeMode.FANFIC
        if mode == TaskMode.STYLE_REMIX:
            return CreativeMode.STYLE_REMIX
        return CreativeMode.ORIGINAL

    @staticmethod
    def _derive_novel_size(mode: TaskMode) -> NovelSize:
        if mode == TaskMode.SHORT_STORY:
            return NovelSize.SHORT
        if mode == TaskMode.FANFIC:
            return NovelSize.MEDIUM
        if mode == TaskMode.STYLE_REMIX:
            return NovelSize.LONG
        return NovelSize.LONG

    @staticmethod
    def _default_target_chapter_count(novel_size: NovelSize) -> int:
        if novel_size == NovelSize.SHORT:
            return 8
        if novel_size == NovelSize.MEDIUM:
            return 80
        return 400

    @property
    def chapter_count_min(self) -> int:
        target = int(self.target_chapter_count or self._default_target_chapter_count(self.novel_size or NovelSize.SHORT))
        return max(1, int(target * 0.9))

    @property
    def chapter_count_max(self) -> int:
        lower = self.chapter_count_min
        target = int(self.target_chapter_count or self._default_target_chapter_count(self.novel_size or NovelSize.SHORT))
        return max(lower, int(-(-target * 11 // 10)))


class TaskCreateRequest(TaskInput):
    model_id: str | None = Field(default=None, validation_alias=AliasChoices("model_id", "model", "default_model_id"))
    auto_review: bool | None = None  # 是否开启自动审核 [NEW]
    auto_review_model_mode: AutoReviewModelMode | None = None
    review_model_id: str = ""

    @model_validator(mode="after")
    def _ensure_task_mode_fields(self) -> "TaskCreateRequest":
        if self.mode is None:
            self.mode = self._derive_mode()
        if self.creative_mode is None:
            self.creative_mode = self._derive_creative_mode(self.mode)
        if self.novel_size is None:
            self.novel_size = self._derive_novel_size(self.mode)
        if self.target_chapter_count is None:
            self.target_chapter_count = self._default_target_chapter_count(self.novel_size)
        if self.chapter_word_min is None:
            self.chapter_word_min = 1800
        return self


class ResumeRequest(BaseModel):
    approved: bool
    comment: str = ""
    model_id: str = Field(default="", validation_alias=AliasChoices("model_id", "default_model_id"))


class RollbackChapterPlanRequest(BaseModel):
    keep_batch_count: int = Field(ge=0)


class ContinueDraftRequest(BaseModel):
    requested_chapter_count: int
    continue_request_id: str
    model_id: str = Field(default="", validation_alias=AliasChoices("model_id", "default_model_id"))


class TaskActionRequest(BaseModel):
    model_id: str = Field(default="", validation_alias=AliasChoices("model_id", "default_model_id"))


class RecoveryMode(str, Enum):
    RECOVER_TO_STABLE = "recover_to_stable"
    RESTART_FROM_INPUT = "restart_from_input"


class RecoveryPreview(BaseModel):
    target_stage: str = ""
    target_stage_label: str = ""
    target_chapter_number: int | None = None
    target_chapter_numbers: list[int] = Field(default_factory=list)
    target_batch_no: int | None = None
    reuse_existing_draft: bool = False
    will_resume_generation: bool = False
    creative_model_id: str = Field(
        default="",
        validation_alias=AliasChoices("creative_model_id", "default_model_id"),
    )
    last_action_model_id: str = ""
    allowed_model_ids: list[str] = Field(default_factory=list)
    fallback_actions: list[str] = Field(default_factory=list)


class RecoveryOption(BaseModel):
    action: str = ""
    label: str = ""
    kind: str = ""
    available: bool = False
    reason_unavailable: str = ""
    preview: RecoveryPreview | None = None


class RecoveryRequest(BaseModel):
    recovery_mode: RecoveryMode = RecoveryMode.RECOVER_TO_STABLE
    model_id: str = Field(default="", validation_alias=AliasChoices("model_id", "default_model_id"))


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


class OutlineBatchInfo(BaseModel):
    phase: str = "master"
    batch_index: int = 0
    batch_size: int = 20
    completed_count: int = 0
    total_count: int = 0
    current_batch_plans: list[ChapterPlan] = Field(default_factory=list)
    retry_count: int = 0


class StoryPlan(BaseModel):
    working_title: str
    logline: str
    world_notes: list[str] = Field(default_factory=list)
    character_notes: list[str] = Field(default_factory=list)
    planned_chapter_count: int | None = None
    chapter_plan: list[ChapterPlan] = Field(default_factory=list)

    @field_validator("world_notes", "character_notes", mode="before")
    @classmethod
    def _normalize_notes(cls, v: Any) -> list[str]:
        """容错处理：允许 LLM 返回字典数组，将字典转为字符串"""
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                # 将字典转为格式化字符串
                parts = []
                for k, val in item.items():
                    if isinstance(val, str):
                        parts.append(f"{k}: {val}")
                    else:
                        parts.append(f"{k}: {val}")
                result.append("; ".join(parts))
            else:
                result.append(str(item))
        return result

    @model_validator(mode="after")
    def _normalize_planned_chapter_count(self) -> "StoryPlan":
        if self.planned_chapter_count is None:
            self.planned_chapter_count = len(self.chapter_plan)
        return self


class ReviewPayload(BaseModel):
    # 三种审核类型: outline_review | chapter_pair_review | verification_review
    type: str = "outline_review"
    version: str = "v1"
    review_scope: str = ""
    summary: str
    story_plan: StoryPlan | None = None
    risk_flags: list[str] = Field(default_factory=list)
    # 大纲修订计数
    revision_count: int = 0
    # 大纲批次分步审核信息（与 chapter_pair 字段隔离）
    outline_batch: OutlineBatchInfo | None = None
    # 章节对审核时
    batch_index: int | None = None
    chapter_pair: list[ChapterDraft] | None = None
    completed_count: int | None = None
    total_chapters: int | None = None
    chapter_pair_revision_count: int = 0
    # 验证审核时
    verification_report: dict[str, Any] | None = None
    verification_revision_count: int = 0
    target_dimensions: list[str] = Field(default_factory=list)


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


class SubtaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DependencyEdge(BaseModel):
    upstream_subtask_id: str
    downstream_subtask_id: str
    kind: str = "finish_to_start"


class SubtaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("subtask"))
    kind: str
    title: str
    status: SubtaskStatus = SubtaskStatus.PENDING
    assigned_agent: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRunRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("agentrun"))
    subtask_id: str
    agent_name: str
    role: str
    status: AgentRunStatus = AgentRunStatus.PENDING
    input_ref: str | None = None
    output_ref: str | None = None


class SupervisorPlan(BaseModel):
    planner_version: str = "v1"
    subtasks: list[SubtaskRecord] = Field(default_factory=list)
    dependencies: list[DependencyEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    mode: TaskMode
    creative_mode: CreativeMode | None = None
    novel_size: NovelSize | None = None
    target_chapter_count: int | None = None
    chapter_count_min: int | None = None
    chapter_count_max: int | None = None
    chapter_word_min: int | None = None
    model_id: str = Field(default="", validation_alias=AliasChoices("model_id", "model", "default_model_id"))
    auto_review_model_mode: AutoReviewModelMode | None = None
    review_model_id: str = ""
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
    last_action_model_id: str = ""
    last_action_kind: str = ""
    storage_state: str = "runs"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    # 自动审核配置 [NEW]
    auto_review: bool | None = None
    auto_review_policy: dict[str, Any] = Field(default_factory=dict)
    auto_review_trace: list[dict[str, Any]] = Field(default_factory=list)
    supervisor_plan: SupervisorPlan | None = None
    agent_runs: list[AgentRunRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_task_record(self) -> "TaskRecord":
        input_data = self.input
        if self.creative_mode is None:
            self.creative_mode = input_data.creative_mode or TaskInput._derive_creative_mode(self.mode)
        if self.novel_size is None:
            self.novel_size = input_data.novel_size or TaskInput._derive_novel_size(self.mode)
        if self.target_chapter_count is None:
            self.target_chapter_count = input_data.target_chapter_count or TaskInput._default_target_chapter_count(
                self.novel_size
            )
        if self.chapter_count_min is None:
            self.chapter_count_min = input_data.chapter_count_min
        if self.chapter_count_max is None:
            self.chapter_count_max = input_data.chapter_count_max
        if self.chapter_word_min is None:
            self.chapter_word_min = input_data.chapter_word_min or 1800
        if input_data.mode is None:
            input_data.mode = self.mode
        if input_data.creative_mode is None:
            input_data.creative_mode = self.creative_mode
        if input_data.novel_size is None:
            input_data.novel_size = self.novel_size
        if input_data.target_chapter_count is None:
            input_data.target_chapter_count = self.target_chapter_count
        if input_data.chapter_word_min is None:
            input_data.chapter_word_min = self.chapter_word_min
        return self

class TaskSummary(BaseModel):
    task_id: str
    title: str
    mode: TaskMode
    creative_mode: CreativeMode | None = None
    novel_size: NovelSize | None = None
    chapter_word_min: int | None = None
    model_id: str
    creative_model_id: str = Field(
        default="",
        validation_alias=AliasChoices("creative_model_id", "default_model_id"),
    )
    last_action_model_id: str = ""
    last_action_kind: str = ""
    auto_review_model_mode: AutoReviewModelMode | None = None
    review_model_id: str = ""
    model_capabilities: dict[str, Any] | None = None
    status: TaskStatus
    current_stage: str
    current_unit: str | None = None
    progress: int
    chapter_count: int | None = None
    word_count: int | None = None
    updated_at: datetime
    summary: str
    error_message: str | None = None
    auto_review: bool = False
    last_error_detail: str | None = None
    storage_state: str
    entry_refs: dict[str, str] | None = None


class DashboardResponse(BaseModel):
    continue_tasks: list[TaskSummary]
    running_tasks: list[TaskSummary]
    failed_tasks: list[TaskSummary]
    completed_tasks: list[TaskSummary] = Field(default_factory=list)
    model_summary: dict[str, Any]
    system_summary: dict[str, Any]
    continue_total: int = 0
    running_total: int = 0
    failed_total: int = 0
    completed_total: int = 0


class ChapterCatalogItem(BaseModel):
    """工作台章节目录项，不携带正文内容。"""

    number: int
    title: str = ""
    goal: str = ""
    summary: str = ""
    status: str = "pending_outline"
    progress: int = 0
    outline_batch_no: int | None = None
    generation_batch_no: int | None = None
    updated_at: datetime | None = None
    content_available: bool = False


class WorkspaceResponse(BaseModel):
    meta: TaskSummary
    recent_events: list[TaskEvent]
    active_trace_summary: str | None = None
    available_tabs: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    blocked_reason: str = ""
    state_reconciled: bool = False
    reconciliation_kind: str = ""
    reconciliation_summary: str = ""
    recovery_options: list[RecoveryOption] = Field(default_factory=list)
    request_preview: dict[str, Any] = Field(default_factory=dict)
    context_status: dict[str, Any] = Field(default_factory=dict)
    response_cache_status: dict[str, Any] = Field(default_factory=dict)
    pending_review_summary: dict[str, Any] = Field(default_factory=dict)
    rag_status: dict[str, Any] = Field(default_factory=dict)
    llm_report: dict[str, Any] = Field(default_factory=dict)
    novel_progress: dict[str, Any] = Field(default_factory=dict)
    chapter_catalog: list[ChapterCatalogItem] = Field(default_factory=list)
    sources: list[SourceAsset] = Field(default_factory=list)
    supervisor_plan: SupervisorPlan | None = None
    agent_runs: list[AgentRunRecord] = Field(default_factory=list)
    auto_review_trace: list[dict[str, Any]] = Field(default_factory=list)
    # 大纲批次分步状态
    outline_phase: str = ""
    outline_completed_count: int = 0
    outline_total_count: int = 0


class ReviewResponse(BaseModel):
    meta: TaskSummary
    review_type: str
    review_version: str
    summary: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    blocked_reason: str = ""
    state_reconciled: bool = False
    reconciliation_kind: str = ""
    reconciliation_summary: str = ""
    recovery_options: list[RecoveryOption] = Field(default_factory=list)
    outline_markdown: str | None = None
    outline_md_ref: str | None = None
    revision_count: int = 0
    review_history: list[dict[str, Any]] = Field(default_factory=list)
    # 自动审核追踪 [NEW]
    auto_review_trace: list[dict[str, Any]] = Field(default_factory=list)
    # 结构化大纲数据（供前端 MasterOutlineSection 渲染）
    story_plan: dict[str, Any] | None = None
    # 大纲批次状态（供前端区分总纲与章节计划审核）
    outline_batch: dict[str, Any] | None = None
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
    story_plan: dict[str, Any] | None = None


# ─────────────────────────────────────────────
# 自动审核相关模型
# ─────────────────────────────────────────────


class ReviewMode(str, Enum):
    """审核模式"""

    FULL_AUTO = "full_auto"  # 完全自动，Agent 决策即最终决策
    ADVISORY = "advisory"  # Agent 提供审核意见，最终决策仍由人工
    SEMI_AUTO = "semi_auto"  # 自动过审，驳回时升级人工


class Strictness(str, Enum):
    """审核严格度"""

    LENIENT = "lenient"  # 宽松
    BALANCED = "balanced"  # 平衡
    STRICT = "strict"  # 严格


class AutoReviewPolicy(BaseModel):
    """自动审核策略配置"""

    mode: ReviewMode = ReviewMode.FULL_AUTO
    # 评分阈值
    outline_pass_threshold: float = 70.0
    chapter_pass_threshold: float = 65.0
    verification_pass_threshold: float = 80.0
    # 升级规则
    auto_escalate_on_critical: bool = True  # 遇到 critical 问题时升级人工
    auto_escalate_on_low_score: bool = True  # 低于阈值时升级人工
    outline_auto_escalate_on_critical: bool | None = None
    chapter_auto_escalate_on_critical: bool | None = None
    # Agent 模型选择（跟随模式由调用方注入当前创作模型）
    auto_review_model_mode: AutoReviewModelMode = AutoReviewModelMode.FOLLOW_CREATIVE
    auditor_model: str = ""
    synthesis_model: str = ""
    # 多 Agent 并行
    parallel_sub_agents: bool = True  # 子 Agent 是否并行执行
    max_sub_agents: int = 3  # 最大并行子 Agent 数
    # 修订策略
    allow_self_revisions: bool = True  # 是否允许自动修订（不打回主流程）
    max_auto_revisions: int = 2  # 自动修订次数上限
    outline_max_auto_revisions: int | None = None
    chapter_max_auto_revisions: int | None = None
    # 审核严格度
    strictness: Strictness = Strictness.BALANCED

    @model_validator(mode="before")
    @classmethod
    def _infer_auto_review_model_mode(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("auto_review_model_mode"):
            return data
        next_data = dict(data)
        if str(next_data.get("auditor_model") or "").strip() or str(next_data.get("synthesis_model") or "").strip():
            next_data["auto_review_model_mode"] = AutoReviewModelMode.FIXED.value
        else:
            next_data["auto_review_model_mode"] = AutoReviewModelMode.FOLLOW_CREATIVE.value
        return next_data

    def get_pass_threshold(self, review_type: str) -> float:
        """根据审核类型获取对应的通过阈值"""
        thresholds = {
            "outline_review": self.outline_pass_threshold,
            "chapter_pair_review": self.chapter_pass_threshold,
            "verification_review": self.verification_pass_threshold,
        }
        return thresholds.get(review_type, 70.0)

    def get_max_auto_revisions(self, review_type: str) -> int:
        if review_type == "outline_review" and self.outline_max_auto_revisions is not None:
            return self.outline_max_auto_revisions
        if review_type == "chapter_pair_review" and self.chapter_max_auto_revisions is not None:
            return self.chapter_max_auto_revisions
        return self.max_auto_revisions

    def should_auto_escalate_on_critical(self, review_type: str) -> bool:
        if review_type == "outline_review" and self.outline_auto_escalate_on_critical is not None:
            return self.outline_auto_escalate_on_critical
        if review_type == "chapter_pair_review" and self.chapter_auto_escalate_on_critical is not None:
            return self.chapter_auto_escalate_on_critical
        return self.auto_escalate_on_critical


class AgentResult(BaseModel):
    """单个 Agent 的执行结果"""

    agent_id: str = Field(default_factory=lambda: new_id("agent"))
    agent_name: str  # 如 "OutlineAuditor", "StructureAgent"
    role: str  # 如 "structure", "consistency", "creativity", "synthesis"
    execution_kind: str | None = None  # main_agent | subagent | synthesis
    parent_agent_id: str | None = None
    created_by: str | None = None
    invocation_kind: str | None = None
    status: str = "pending"  # pending | running | completed | failed
    score: float | None = None  # 评分 0-100
    issues: list[dict[str, Any]] = Field(default_factory=list)  # 发现的问题列表
    warnings: list[dict[str, Any]] = Field(default_factory=list)  # 警告列表
    highlights: list[str] = Field(default_factory=list)  # 亮点列表
    reasoning: str = ""  # 分析推理过程
    raw_response: dict[str, Any] | None = None  # 原始 LLM 输出
    error: str | None = None  # 错误信息
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_ms(self) -> int | None:
        """计算执行耗时（毫秒）"""
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return None


class ReviewDecision(BaseModel):
    """自动审核的最终决策结果"""

    approved: bool  # 是否通过
    comment: str = ""  # 审核意见（注入到 workflow state）
    reasoning: str = ""  # 决策依据摘要
    agent_trace: list[AgentResult] = Field(default_factory=list)  # 各子 Agent 执行追踪
    auto_escalated: bool = False  # 是否升级（超过阈值需人工介入）
    overall_score: float | None = None  # 整体评分（0-100）
    # 扩展信息
    critical_issues: list[dict[str, Any]] = Field(default_factory=list)  # 严重问题列表
    warnings: list[dict[str, Any]] = Field(default_factory=list)  # 警告列表
    suggestions: list[str] = Field(default_factory=list)  # 改进建议
    revision_needed: bool = False  # 是否需要修订
    revision_scope: str | None = None  # 修订范围，如 "outline", "chapter_3", "full_story"


# ─────────────────────────────────────────────
# 流式聊天相关模型
# ─────────────────────────────────────────────


class ChatMessage(BaseModel):
    """单条聊天消息。"""

    role: str  # system | user | assistant
    content: str


class ChatRequest(BaseModel):
    """流式聊天请求。"""

    messages: list[ChatMessage]
    model: str | None = None
    stream: bool = True
    rag_enabled: bool = True
    rag_top_k: int | None = None
