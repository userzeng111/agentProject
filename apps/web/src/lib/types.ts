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
}

export interface TaskCreatePayload extends TaskInput {
  mode: TaskMode;
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
  status: TaskStatus;
  current_stage: string;
  updated_at: string;
  summary: string;
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
}

export interface WorkspaceResponse {
  meta: WorkspaceMeta;
  recent_events: WorkspaceEvent[];
  active_trace_summary?: string;
  available_tabs?: string[];
  request_preview?: {
    prompt: string;
    genre?: string;
    style?: string;
  };
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
