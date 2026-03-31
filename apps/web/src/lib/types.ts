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
  | "failed";

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

export interface ModelOption {
  id: string;
  object?: string;
  owned_by?: string;
}

export interface ModelListResponse {
  data: ModelOption[];
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
}

export interface WorkspaceMeta {
  task_id: string;
  title: string;
  mode: TaskMode;
  model_id?: string;
  status: TaskStatus;
  current_stage: string;
  current_unit?: string | null;
  progress: number;
  updated_at?: string;
  summary?: string;
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
    genre?: string;
    style?: string;
    target_words?: number;
    audience?: string;
    banned?: string;
    title_hint?: string;
  };
  sources?: SourceAsset[];
}

export interface ReviewHistoryItem {
  version: string;
  action: string;
  comment?: string;
  created_at?: string;
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
    genre?: string;
    style?: string;
    target_words?: number;
    audience?: string;
    banned?: string;
    title_hint?: string;
  };
  recent_events: WorkspaceEvent[];
  result_summary?: string;
  result_markdown?: string;
  result_md_ref?: string | null;
  chapter_index: ResultChapterItem[];
  artifact_index: ArtifactIndexItem[];
  history_index?: ReviewHistoryItem[];
}
