from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    auto_review: bool = False  # 是否开启自动审核 [NEW]


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
    # 自动审核配置 [NEW]
    auto_review: bool = False
    auto_review_policy: dict[str, Any] = Field(default_factory=dict)
    auto_review_trace: list[dict[str, Any]] = Field(default_factory=list)


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
    entry_refs: dict[str, str] | None = None


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
    revision_count: int = 0
    review_history: list[dict[str, Any]] = Field(default_factory=list)
    # 自动审核追踪 [NEW]
    auto_review_trace: list[dict[str, Any]] = Field(default_factory=list)
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
    # Agent 模型选择
    auditor_model: str = "MiniMax-M2.7-highspeed"
    synthesis_model: str = "MiniMax-M2.7-highspeed"
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
    status: str = "pending"  # pending | running | completed | failed
    score: float | None = None  # 评分 0-100
    issues: list[dict[str, Any]] = Field(default_factory=list)  # 发现的问题列表
    highlights: list[str] = Field(default_factory=list)  # 亮点列表
    reasoning: str = ""  # 分析推理过程
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
