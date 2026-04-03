export type TaskMode = "short_story" | "long_story" | "fanfic" | "style_remix";
export type TaskStatus =
  | "created"
  | "sources_ingested"
  | "planning"
  | "waiting_outline_review"
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
  genre: string;
  style: string;
  target_words: number;
  audience: string;
  banned: string;
  title_hint: string;
  model_id?: string;
}

export interface TaskCreatePayload extends TaskInput {
  mode: TaskMode;
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

export interface ModelMetadata {
  source?: string;
  profile_version?: string;
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

export interface ModelListResponse {
  data: ModelOption[];
  meta?: {
    default_model?: string;
    capability_schema_version?: string;
  };
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

export interface TaskRecord {
  id: string;
  mode: TaskMode;
  status: TaskStatus;
  current_stage: string;
  progress: number;
  input: TaskInput;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskCardSummary {
  task_id: string;
  title: string;
  mode: TaskMode;
  model_id?: string;
  status: TaskStatus;
  current_stage: string;
  current_unit?: string | null;
  progress?: number;
  updated_at: string;
  summary: string;
  storage_state?: string;
}

export interface DashboardResponse {
  continue_tasks: TaskCardSummary[];
  running_tasks: TaskCardSummary[];
  failed_tasks: TaskCardSummary[];
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
}

export interface WorkspaceMeta {
  task_id: string;
  title: string;
  mode: TaskMode;
  model_id?: string;
  model_capabilities?: ModelCapabilities;
  status: TaskStatus;
  current_stage: string;
  current_unit?: string | null;
  progress: number;
  updated_at?: string;
  summary?: string;
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
  };
}

export interface SourceAsset {
  id: string;
  filename: string;
  media_type: string;
  uploaded_at: string;
}

export interface WorkspaceResponse {
  meta: WorkspaceMeta;
  recent_events: WorkspaceEvent[];
  active_trace_summary?: string;
  available_tabs?: string[];
  request_preview?: {
    prompt: string;
    model_id?: string;
    model_capabilities?: ModelCapabilities;
    genre?: string;
    style?: string;
    target_words?: number;
    audience?: string;
    banned?: string;
    title_hint?: string;
  };
  context_status?: ContextStatus;
  response_cache_status?: ResponseCacheStatus;
  context_snapshot?: ContextStatus;
  sources?: SourceAsset[];
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
}

/** 自动审核 Agent 执行追踪项 [NEW] */
export interface AgentTraceItem {
  agent_id: string;
  agent_name: string;  // 显示名称，如 "结构分析师"
  role: string;  // internal role
  status: "pending" | "running" | "completed" | "failed";
  score?: number;  // 评分 0-100
  issues?: VerificationIssue[];
  highlights?: string[];
  reasoning?: string;
  error?: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
}

export interface ReviewResponse {
  meta: WorkspaceMeta;
  review_type: string;
  review_version: string;
  summary?: string;
  risk_flags: string[];
  outline_markdown?: string;
  outline_md_ref?: string | null;
  review_history?: ReviewHistoryItem[];
  // 自动审核追踪 [NEW]
  auto_review_trace?: AgentTraceItem[];
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

export interface ArchiveMeta {
  task_id: string;
  title: string;
  mode: TaskMode;
  model_id?: string;
  status: TaskStatus;
  current_stage: string;
  current_unit?: string | null;
  progress: number;
  updated_at: string;
  error_message?: string | null;
  storage_state: string;
}

export interface ArchiveResultFile {
  title: string;
  summary: string;
  body: string;
  chapters: Array<{
    number: number;
    title: string;
    summary: string;
    content: string;
  }>;
}

export interface ArchiveEventsFile {
  task_id: string;
  items: WorkspaceEvent[];
}

export interface ArchiveDetailResponse {
  meta: WorkspaceMeta;
  request_preview?: {
    prompt: string;
    model_id?: string;
    model_capabilities?: ModelCapabilities;
    genre?: string;
    style?: string;
    target_words?: number;
    audience?: string;
    banned?: string;
    title_hint?: string;
  };
  context_status?: ContextStatus;
  context_snapshot?: ContextStatus;
  recent_events: WorkspaceEvent[];
  result_summary?: string;
  result_markdown?: string;
  result_md_ref?: string | null;
  chapter_index: ResultChapterItem[];
  artifact_index: ArtifactIndexItem[];
  history_index?: ReviewHistoryItem[];
}
