export type TaskMode = "short_story" | "long_story" | "fanfic" | "style_remix";

export type TaskStatus =
  | "created"
  | "sources_ingested"
  | "planning"
  | "waiting_outline_review"
  | "drafting"
  | "waiting_manual_action"
  | "assembling"
  | "waiting_chapter_review"
  | "waiting_verification_review"
  | "completed"
  | "cancelled"
  | "failed";

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
  chapter_plan: ChapterPlan[];
}

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

export interface SourceAsset {
  id: string;
  filename: string;
  media_type: string;
  uploaded_at: string;
}

export interface TaskSummary {
  task_id: string;
  title: string;
  mode: TaskMode;
  model_id?: string;
  status: TaskStatus;
  current_stage: string;
  current_unit?: string | null;
  progress: number;
  updated_at: string;
  summary: string;
  storage_state?: string;
  entry_refs?: ArchiveEntryRefs;
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

export interface AgentTraceItem {
  agent_id: string;
  agent_name: string;
  role: string;
  status: "pending" | "running" | "completed" | "failed";
  score?: number;
  issues?: VerificationIssue[];
  highlights?: string[];
  reasoning?: string;
  error?: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
}

export interface RequestPreview {
  prompt: string;
  model_id?: string;
  genre?: string;
  style?: string;
  target_words?: number;
  audience?: string;
  banned?: string;
  title_hint?: string;
}

export interface WorkspaceResponse {
  meta: TaskSummary;
  recent_events: WorkspaceEvent[];
  active_trace_summary?: string;
  available_tabs?: string[];
  request_preview?: RequestPreview;
  context_status?: Record<string, unknown>;
  response_cache_status?: Record<string, unknown>;
  sources?: SourceAsset[];
}

export interface ReviewResponse {
  meta: TaskSummary;
  review_type: string;
  review_version: string;
  summary?: string;
  risk_flags: string[];
  outline_markdown?: string;
  outline_md_ref?: string | null;
  revision_count?: number;
  review_history?: ReviewHistoryItem[];
  auto_review_trace?: AgentTraceItem[];
  chapter_pair?: ReviewChapterItem[];
  batch_index?: number;
  completed_count?: number;
  total_chapters?: number;
  chapter_pair_revision_count?: number;
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
  meta: TaskSummary;
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

export interface ArchiveIndexResponse {
  items: TaskSummary[];
  total?: number;
  page?: number;
  page_size?: number;
  total_pages?: number;
}

export interface ArchiveDetailResponse {
  meta: TaskSummary;
  request_preview?: RequestPreview;
  sources?: SourceAsset[];
  recent_events: WorkspaceEvent[];
  result_summary?: string;
  result_markdown?: string;
  result_md_ref?: string | null;
  chapter_index: ResultChapterItem[];
  artifact_index: ArtifactIndexItem[];
  history_index?: ReviewHistoryItem[];
}
