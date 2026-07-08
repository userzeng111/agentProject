export type TaskMode = "short_story" | "long_story" | "fanfic" | "style_remix";
export type CreativeMode = "original" | "fanfic" | "style_remix";
export type NovelSize = "short" | "medium" | "long";
export type AutoReviewModelMode = "follow_creative" | "fixed";
export type TaskStatus =
  | "created"
  | "sources_ingested"
  | "planning"
  | "waiting_outline_review"
  | "ready_for_batch"
  | "drafting"
  | "waiting_manual_action"
  | "assembling"
  | "completed"
  | "cancelled"
  | "failed"
  | "waiting_chapter_review"
  | "waiting_verification_review";

export interface TaskInput {
  prompt: string;
  creative_mode: CreativeMode;
  novel_size: NovelSize;
  target_chapter_count?: number;
  genre: string;
  style: string;
  style_profile_id?: string;
  chapter_word_min: number;
  target_words?: number;
  audience: string;
  banned: string;
  title_hint: string;
  model_id?: string;
  creative_model_id?: string;
  auto_review_model_mode?: AutoReviewModelMode;
  review_model_id?: string;
}

export interface TaskCreatePayload extends TaskInput {
  auto_review?: boolean;
}

export type RecoveryMode = "recover_to_stable" | "restart_from_input";

export interface RecoveryPreview {
  target_stage: string;
  target_stage_label: string;
  target_chapter_number?: number | null;
  target_chapter_numbers?: number[];
  target_batch_no?: number | null;
  reuse_existing_draft?: boolean;
  will_resume_generation?: boolean;
  default_model_id?: string;
  last_action_model_id?: string;
  allowed_model_ids: string[];
  fallback_actions?: RecoveryMode[];
}

export interface RecoveryOption {
  action: RecoveryMode;
  label?: string;
  kind?: "primary" | "secondary";
  available: boolean;
  reason_unavailable?: string;
  preview?: RecoveryPreview | null;
}

export interface RecoveryContractFields {
  allowed_actions?: RecoveryMode[];
  recommended_action?: RecoveryMode;
  blocked_reason?: string;
  state_reconciled?: boolean;
  reconciliation_kind?: string;
  reconciliation_summary?: string;
  recovery_options?: RecoveryOption[];
}

export interface TaskActionPayload {
  model_id?: string;
}

export interface RecoverTaskPayload extends TaskActionPayload {
  recovery_mode?: RecoveryMode;
}

export interface ModelContextWindowCapability {
  max_input_tokens?: number;
  max_output_tokens?: number;
  max_total_tokens?: number;
  recommended_input_tokens?: number;
  recommended_prompt_budget?: number;
  compression_trigger_tokens?: number;
}

export interface ModelCacheCapability {
  runtime_context_cache?: boolean;
  prompt_cache?: boolean;
  response_cache?: boolean;
  cache_scope?: string;
  runtime_response_cache?: boolean;
  provider_prompt_cache?: string;
  cache_key_strategy?: string;
}

export interface ModelCompressionCapability {
  supported?: boolean;
  may_compress?: boolean;
  strategy?: string;
}

export interface ModelCapabilities {
  context_window?: ModelContextWindowCapability;
  cache?: ModelCacheCapability;
  compression?: ModelCompressionCapability;
  features?: string[] | Record<string, boolean>;
}

export type ModelValidationCheckStatus = "pending" | "running" | "passed" | "failed" | "skipped";
export type ModelValidationReportStatus = "unverified" | "running" | "verified" | "failed";
export type ModelValidationStatus = ModelValidationReportStatus | "cancelled";

export interface ModelValidationCheck {
  id: string;
  label?: string;
  status: ModelValidationCheckStatus;
  summary?: string;
  failure_reason?: string;
  evidence?: Record<string, unknown>;
}

export interface ModelValidationReport {
  model_id?: string;
  status: ModelValidationReportStatus;
  validated_at?: string;
  validator_version?: string;
  summary?: string;
  failure_reason?: string;
  last_error?: string;
  checks?: ModelValidationCheck[];
  evidence?: Record<string, unknown>;
}

export type ModelValidationEvent =
  | { type: "validation.started"; data: { model_id?: string; run_id?: string; validator_version?: string; status?: "running" } }
  | { type: "validation.check"; data: { model_id?: string; run_id?: string; check?: ModelValidationCheck } }
  | {
      type: "validation.chat_chunk";
      data: {
        model_id?: string;
        run_id?: string;
        content?: string;
        reasoning_signal?: boolean;
        reasoning_chars_delta?: number;
        usage?: Record<string, number>;
      };
    }
  | { type: "validation.done"; data: { model_id?: string; run_id?: string; status?: "verified"; report?: ModelValidationReport } }
  | {
      type: "validation.error";
      data: {
        model_id?: string;
        run_id?: string;
        status?: "failed";
        message?: string;
        check_id?: string;
        report?: ModelValidationReport;
      };
    };

export interface ModelMetadata {
  source?: string;
  compatibility?: string;
  profile_version?: string;
  protocol?: string;
  validation?: ModelValidationReport;
}

export interface StyleProfile {
  id: string;
  name: string;
  source_novel: string;
  source_author: string;
  genre: string;
  description: string;
  fidelity_score: number;
  trigger_keywords: string[];
}

export interface ModelOption {
  id: string;
  object?: string;
  owned_by?: string;
  display_name?: string;
  provider?: string;
  capabilities?: ModelCapabilities;
  metadata?: ModelMetadata;
}

export interface ModelRefreshState {
  loading: boolean;
  error: string;
  attemptedRefresh?: boolean;
  fetchedAt?: string;
  cacheAgeSeconds?: number;
  cacheTtlSeconds?: number;
  cached?: boolean;
  invalidated?: boolean;
  invalidatedModelLabel?: string;
}

export interface ModelListResponse {
  data: ModelOption[];
  meta?: {
    default_model?: string;
    capability_schema_version?: string;
    cache_ttl_seconds?: number;
    cache_age_seconds?: number;
    cached?: boolean;
    fetched_at?: string;
  };
}

export interface StyleProfileListResponse {
  items: StyleProfile[];
}

export interface ContextStatus {
  stage?: string;
  status?: string;
  summary?: string;
  current_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  max_input_tokens?: number;
  window_usage_ratio?: number;
  compression_applied?: boolean;
  compression_ratio?: number;
  compression_summary?: string;
  cache_hit?: boolean;
  cache_scope?: string;
  cache_key?: string;
  cached_segments?: number;
}

export interface ResponseCacheStatus {
  stage?: string;
  status?: string;
  summary?: string;
  cache_hit?: boolean;
  cache_scope?: string;
  cache_key?: string;
  history_count?: number;
  exchange_label?: string;
  model?: string;
}

export interface PendingReviewSummary {
  present?: boolean;
  review_type?: string;
  stage?: string;
  batch_index?: number | null;
  revision_count?: number;
  outline_phase?: string;
  summary?: string;
}

export interface RagStatus {
  enabled?: boolean;
  ready?: boolean;
  source?: string;
  summary?: string;
  last_query_stage?: string;
  last_error?: string;
  injected?: boolean;
  injection_evidence?: string;
}

export interface LlmUsageSummary {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cached_tokens?: number;
  cache_read_input_tokens?: number;
  usage_count?: number;
}

export interface LlmTimingDetail {
  stage?: string;
  exchange_label?: string;
  model?: string;
  duration_ms?: number;
  first_token_ms?: number;
  attempt?: number;
  finish_reason?: string | null;
  content_chars?: number;
  reasoning_chars?: number;
  status?: string;
  is_retry?: boolean;
  is_repair?: boolean;
}

export interface LlmTimingBucket {
  call_count?: number;
  total_duration_ms?: number;
  max_duration_ms?: number;
  max_first_token_ms?: number;
  retry_count?: number;
  repair_count?: number;
}

export interface LlmExchangeSummary {
  stage?: string;
  event_type?: string;
  unit_id?: string;
  exchange_label?: string;
  model?: string;
  cache_hit?: boolean;
  cache_key?: string;
  history_count?: number;
  parse_duration_ms?: number;
}

export interface LlmReport {
  usage_total?: LlmUsageSummary;
  usage_count?: number;
  request_count?: number;
  by_model?: Record<string, LlmUsageSummary>;
  by_stage?: Record<string, LlmUsageSummary>;
  exchange_count?: number;
  cache_hit_count?: number;
  runtime_response_cache_hit_count?: number;
  provider_prompt_cache_hit_count?: number;
  timing_count?: number;
  timing_by_stage?: Record<string, LlmTimingBucket>;
  slowest_step?: LlmTimingDetail;
  slowest_first_token?: LlmTimingDetail;
  latest_exchange?: LlmExchangeSummary;
  latest_usage?: LlmExchangeSummary & LlmUsageSummary;
}

export interface TaskRecord {
  id: string;
  mode: TaskMode;
  creative_mode?: CreativeMode;
  novel_size?: NovelSize;
  target_chapter_count?: number;
  chapter_count_min?: number;
  chapter_count_max?: number;
  chapter_word_min?: number;
  status: TaskStatus;
  current_stage: string;
  progress: number;
  input: TaskInput;
  error_message: string | null;
  model_id?: string;
  creative_model_id?: string;
  default_model_id?: string;
  last_action_model_id?: string;
  last_action_kind?: string;
  auto_review_model_mode?: AutoReviewModelMode;
  review_model_id?: string;
  created_at: string;
  updated_at: string;
}

export interface TaskCardSummary {
  task_id: string;
  title: string;
  mode: TaskMode;
  creative_mode?: CreativeMode;
  novel_size?: NovelSize;
  chapter_word_min?: number;
  model_id?: string;
  default_model_id?: string;
  last_action_model_id?: string;
  last_action_kind?: string;
  status: TaskStatus;
  current_stage: string;
  current_unit?: string | null;
  progress?: number;
  updated_at: string;
  summary: string;
  error_message?: string | null;
  auto_review_model_mode?: AutoReviewModelMode;
  review_model_id?: string;
  storage_state?: string;
}

export interface DashboardResponse {
  continue_tasks: TaskCardSummary[];
  running_tasks: TaskCardSummary[];
  failed_tasks: TaskCardSummary[];
  completed_tasks?: TaskCardSummary[];
  model_summary?: {
    default_model: string;
    supported_models: string[];
  };
  system_summary?: {
    active_runs: number;
    archived_runs: number;
  };
  continue_total?: number;
  running_total?: number;
  failed_total?: number;
  completed_total?: number;
}

export interface WorkspaceMeta {
  task_id: string;
  title: string;
  mode: TaskMode;
  creative_mode?: CreativeMode;
  novel_size?: NovelSize;
  chapter_word_min?: number;
  model_id?: string;
  creative_model_id?: string;
  default_model_id?: string;
  last_action_model_id?: string;
  last_action_kind?: string;
  auto_review_model_mode?: AutoReviewModelMode;
  review_model_id?: string;
  model_capabilities?: ModelCapabilities;
  status: TaskStatus;
  current_stage: string;
  current_unit?: string | null;
  progress: number;
  updated_at?: string;
  summary?: string;
  error_message?: string | null;
  storage_state?: string;
  auto_review?: boolean;
  last_error_detail?: string;
  context_status?: ContextStatus;
}

export interface WorkspaceEvent {
  event_id: string;
  task_id: string;
  event_type: string;
  stage: string;
  unit_id?: string | null;
  message: string;
  md_ref?: string | null;
  json_ref?: string | null;
  created_at: string;
  payload?: {
    chapter_number?: number;
    chapter_title?: string;
    chapter_summary?: string;
    summary?: string;
    kind?: string;
    title?: string;
    detail?: string;
    approved?: boolean;
    comment?: string;
    reason?: string;
    // 思考链（model.thinking 事件）
    reasoning_chunk?: string;
    accumulated_length?: number;
    model?: string;
    finish_reason?: string | null;
  };
}

export interface SourceAsset {
  id: string;
  filename: string;
  media_type: string;
  uploaded_at: string;
}

export interface WorkspaceResponse extends RecoveryContractFields {
  meta: WorkspaceMeta;
  recent_events: WorkspaceEvent[];
  active_trace_summary?: string;
  available_tabs?: string[];
  request_preview?: {
    prompt: string;
    creative_mode?: CreativeMode;
    novel_size?: NovelSize;
    target_chapter_count?: number;
    model_id?: string;
    creative_model_id?: string;
    default_model_id?: string;
    last_action_model_id?: string;
    last_action_kind?: string;
    auto_review_model_mode?: AutoReviewModelMode;
    review_model_id?: string;
    model_capabilities?: ModelCapabilities;
    genre?: string;
    style?: string;
    style_profile_id?: string;
    style_profile_name?: string;
    style_guidance?: string;
    canon_guidance?: string;
    style_profile?: Record<string, unknown>;
    chapter_word_min?: number;
    target_words?: number;
    audience?: string;
    banned?: string;
    title_hint?: string;
  };
  context_status?: ContextStatus;
  response_cache_status?: ResponseCacheStatus;
  context_snapshot?: ContextStatus;
  pending_review_summary?: PendingReviewSummary;
  rag_status?: RagStatus;
  llm_report?: LlmReport;
  novel_progress?: {
    target_chapter_count?: number;
    chapter_count_min?: number;
    chapter_count_max?: number;
    planned_chapter_count?: number;
    completed_chapter_count?: number;
    next_chapter_number?: number;
    current_generating_chapter_number?: number | null;
    remaining_chapter_count?: number;
    default_batch_size?: number;
  };
  sources?: SourceAsset[];
  supervisor_plan?: SupervisorPlanSnapshot | null;
  agent_runs?: AgentRunItem[];
  auto_review_trace?: AgentTraceItem[];
  // 大纲批次分步状态
  outline_phase?: string;
  outline_completed_count?: number;
  outline_total_count?: number;
}

export interface ContinueDraftPayload {
  requested_chapter_count: number;
  continue_request_id: string;
  model_id?: string;
}

export type SupervisorSubtaskStatus =
  | "pending"
  | "ready"
  | "running"
  | "blocked"
  | "completed"
  | "failed";

export interface DependencyEdge {
  upstream_subtask_id: string;
  downstream_subtask_id: string;
  kind: string;
}

export interface SupervisorSubtaskItem {
  id: string;
  kind: string;
  title: string;
  status: SupervisorSubtaskStatus;
  assigned_agent?: string;
  payload?: Record<string, unknown>;
}

export interface SupervisorPlanSnapshot {
  planner_version: string;
  subtasks: SupervisorSubtaskItem[];
  dependencies: DependencyEdge[];
  metadata?: Record<string, unknown>;
}

export interface AgentRunItem {
  id: string;
  subtask_id: string;
  agent_name: string;
  role: string;
  status: "pending" | "running" | "completed" | "failed";
  input_ref?: string | null;
  output_ref?: string | null;
}

export interface ReviewHistoryItem {
  version: string;
  action: string;
  comment?: string;
  created_at?: string;
}

export interface ReviewChapterItem {
  number: number;
  title: string;
  summary: string;
  content: string;
}

export interface VerificationIssue {
  severity: string;
  location: string;
  description: string;
  suggestion: string;
  dimension?: string;
}

/** 自动审核 Agent 执行追踪项 [NEW] */
export interface AgentTraceItem {
  __summary__?: boolean;
  agent_id?: string;
  agent_name?: string;  // 显示名称，如 "结构分析师"
  role?: string;  // internal role
  execution_kind?: "main_agent" | "subagent" | "synthesis";
  parent_agent_id?: string | null;
  created_by?: string | null;
  invocation_kind?: string | null;
  status?: "pending" | "running" | "completed" | "failed";
  score?: number;  // 评分 0-100
  issues?: VerificationIssue[];
  highlights?: string[];
  reasoning?: string;
  error?: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  overall_score?: number;
  approved?: boolean;
  auto_escalated?: boolean;
  comment?: string;
  warnings?: VerificationIssue[];
  raw_response?: Record<string, unknown> | null;
  trace_round?: number;
  review_type?: string;
  revision_count?: number;
  batch_index?: number | null;
  created_at?: string;
}

export interface ReviewChapterPlanItem {
  number: number;
  title: string;
  goal: string;
}

export interface ReviewResponse extends RecoveryContractFields {
  meta: WorkspaceMeta;
  review_type: string;
  review_version: string;
  summary?: string;
  risk_flags: string[];
  outline_markdown?: string;
  outline_md_ref?: string | null;
  revision_count?: number;
  review_history?: ReviewHistoryItem[];
  // 自动审核追踪 [NEW]
  auto_review_trace?: AgentTraceItem[];
  // 结构化大纲数据
  story_plan?: {
    working_title: string;
    logline: string;
    world_notes: string[];
    character_notes: string[];
    planned_chapter_count: number | null;
  };
  // 大纲批次分步审核
  outline_batch?: {
    phase: "master" | "chapter_batches";
    batch_index: number;
    batch_size: number;
    completed_count: number;
    total_count: number;
    current_batch_plans: ReviewChapterPlanItem[];
  };
  // 章节对审核
  chapter_pair?: ReviewChapterItem[];
  batch_index?: number;
  completed_count?: number;
  total_chapters?: number;
  chapter_pair_revision_count?: number;
  // 验证审核
  verification_report?: {
    issues?: VerificationIssue[];
    overall_score?: number;
    summary?: string;
  };
  verification_revision_count?: number;
}

export interface ResultChapterItem {
  number: number;
  title: string;
  summary?: string;
  md_ref?: string | null;
  content?: string | null;
}

export interface ChapterPlan {
  number: number;
  title: string;
  goal: string;
}

export interface StoryPlan {
  working_title: string;
  logline: string;
  world_notes: string[];
  character_notes: string[];
  planned_chapter_count?: number | null;
  chapter_plan: ChapterPlan[];
}

export interface ArtifactIndexItem {
  id: string;
  type: string;
  name: string;
  md_ref?: string | null;
  json_ref?: string | null;
  created_at?: string;
}

export interface ResultResponse {
  meta: WorkspaceMeta;
  result_summary?: string;
  result_markdown?: string;
  result_md_ref?: string | null;
  chapter_index: ResultChapterItem[];
  artifact_index: ArtifactIndexItem[];
  history_index?: ReviewHistoryItem[];
}

export interface ArchiveEntryRefs {
  meta_json?: string;
  events_tail_json?: string;
  result_json?: string;
}

export interface ArchiveTaskSummary extends TaskCardSummary {
  current_unit?: string | null;
  progress: number;
  chapter_count?: number | null;
  word_count?: number | null;
  storage_state: string;
  entry_refs?: ArchiveEntryRefs;
}

export interface ArchiveIndexResponse {
  items: ArchiveTaskSummary[];
  total?: number;
  page?: number;
  page_size?: number;
  total_pages?: number;
}

export interface ArchiveDetailResponse {
  meta: WorkspaceMeta;
  request_preview?: {
    prompt: string;
    creative_mode?: CreativeMode;
    novel_size?: NovelSize;
    model_id?: string;
    default_model_id?: string;
    last_action_model_id?: string;
    last_action_kind?: string;
    model_capabilities?: ModelCapabilities;
    genre?: string;
    style?: string;
    style_profile_id?: string;
    style_profile_name?: string;
    style_guidance?: string;
    canon_guidance?: string;
    style_profile?: Record<string, unknown>;
    chapter_word_min?: number;
    target_words?: number;
    audience?: string;
    banned?: string;
    title_hint?: string;
  };
  sources?: SourceAsset[];
  recent_events: WorkspaceEvent[];
  result_summary?: string;
  result_markdown?: string;
  result_md_ref?: string | null;
  chapter_index: ResultChapterItem[];
  artifact_index: ArtifactIndexItem[];
  history_index?: ReviewHistoryItem[];
  story_plan?: StoryPlan | null;
}


/* ── 流式聊天相关类型 ── */

export interface ChatStreamChunk {
  content: string;
  reasoning_content?: string;
  finish_reason?: string;
  usage?: Record<string, number>;
}

export interface ChatDoneEvent {
  model: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  reasoning_content?: string;
  isStreaming?: boolean;
}

export interface RagSyncResult {
  success: boolean;
  message: string;
  scanned_files: number;
  indexed_documents: number;
  output_dir: string;
  duration_ms: number;
  finished_at?: string;
  sources: string[];
  warnings: string[];
}

export interface RagSettingsStatus {
  available: boolean;
  library_dir: string;
  faiss_index_path: string;
  sqlite_path: string;
  sources: string[];
  last_result?: RagSyncResult | null;
}
