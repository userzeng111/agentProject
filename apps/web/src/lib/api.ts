import {
  ArchiveDetailResponse,
  ArchiveIndexResponse,
  ModelListResponse,
  ModelOption,
  DashboardResponse,
  ResultResponse,
  ReviewResponse,
  RagSettingsStatus,
  RagSyncResult,
  StyleProfileListResponse,
  TaskCreatePayload,
  TaskRecord,
  WorkspaceResponse,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "请求失败");
  }

  return response.json() as Promise<T>;
}

export function getApiBase() {
  return API_BASE;
}

export function createTask(payload: TaskCreatePayload) {
  return request<TaskRecord>("/api/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getModels() {
  const response = await request<ModelListResponse>("/api/models");
  return response.data ?? [];
}

export async function getStyleProfiles() {
  const response = await request<StyleProfileListResponse>("/api/style-profiles");
  return Array.isArray(response.items) ? response.items : [];
}

export async function updateDefaultModel(modelId: string) {
  return request<{ default_model: string; supported_models: string[] }>("/api/settings/default-model", {
    method: "PATCH",
    body: JSON.stringify({ model_id: modelId }),
  });
}

export function getRagSettings() {
  return request<RagSettingsStatus>("/api/settings/rag");
}

export function rebuildRagLibrary() {
  return request<RagSyncResult>("/api/settings/rag/rebuild", {
    method: "POST",
  });
}

export function uploadAsset(taskId: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return request<TaskRecord>(`/api/tasks/${taskId}/assets`, {
    method: "POST",
    body: formData,
  });
}

export function runTask(taskId: string) {
  return request<TaskRecord>(`/api/tasks/${taskId}/run`, {
    method: "POST",
  });
}

export function resumeTask(taskId: string, approved: boolean, comment: string) {
  return request<TaskRecord>(`/api/tasks/${taskId}/resume`, {
    method: "POST",
    body: JSON.stringify({ approved, comment }),
  });
}

export function recoverTask(taskId: string) {
  return request<TaskRecord>(`/api/tasks/${taskId}/recover`, {
    method: "POST",
  });
}

export function getDashboard() {
  return request<DashboardResponse>("/api/dashboard");
}

export function getTask(taskId: string) {
  return request<TaskRecord>(`/api/tasks/${taskId}`);
}

export function getWorkspace(taskId: string) {
  return request<WorkspaceResponse>(`/api/tasks/${taskId}/workspace`);
}

export function getSupervisor(taskId: string) {
  return request<{
    planner_version: string;
    subtasks: Array<{
      id: string;
      kind: string;
      title: string;
      status: string;
      assigned_agent?: string;
      payload?: Record<string, unknown>;
    }>;
    dependencies: Array<{
      upstream_subtask_id: string;
      downstream_subtask_id: string;
      kind: string;
    }>;
    metadata?: Record<string, unknown>;
    agent_runs?: WorkspaceResponse["agent_runs"];
  }>(`/api/tasks/${taskId}/supervisor`);
}

export function getReview(taskId: string) {
  return request<ReviewResponse>(`/api/tasks/${taskId}/review`);
}

export function getResult(taskId: string) {
  return request<ResultResponse>(`/api/tasks/${taskId}/result`);
}

export function getCurrentChapters(taskId: string) {
  return request<{ task_id: string; chapters: Array<{ number: number; title: string; summary: string; content: string }> }>(`/api/tasks/${taskId}/chapters`);
}

export function getArchiveList(page?: number, pageSize?: number) {
  const params = new URLSearchParams();
  if (page !== undefined) params.set("page", String(page));
  if (pageSize !== undefined) params.set("page_size", String(pageSize));
  const query = params.toString();
  return request<ArchiveIndexResponse>(`/api/archive${query ? `?${query}` : ""}`);
}

export function getArchiveDetail(taskId: string) {
  return request<ArchiveDetailResponse>(`/api/archive/${taskId}`);
}

export async function fetchTextRef(ref: string) {
  const target = ref.startsWith("http") ? ref : `${API_BASE}${ref.startsWith("/") ? ref : `/${ref}`}`;
  const response = await fetch(target, { cache: "no-store" });
  if (!response.ok) {
    throw new Error("读取文本引用失败");
  }
  return response.text();
}

export async function fetchJsonRef<T>(ref: string) {
  const target = ref.startsWith("http") ? ref : `${API_BASE}${ref.startsWith("/") ? ref : `/${ref}`}`;
  const response = await fetch(target, { cache: "no-store" });
  if (!response.ok) {
    throw new Error("读取 JSON 引用失败");
  }
  return response.json() as Promise<T>;
}

export function normalizeModelOptions(models: ModelOption[]) {
  return models
    .filter((item) => typeof item?.id === "string" && item.id.trim())
    .map((item) => ({
      ...item,
      id: item.id.trim(),
      display_name: typeof item.display_name === "string" && item.display_name.trim() ? item.display_name.trim() : undefined,
      provider: typeof item.provider === "string" && item.provider.trim() ? item.provider.trim() : undefined,
      capabilities: item.capabilities
        ? {
            context_window: item.capabilities.context_window
              ? {
                  max_input_tokens: item.capabilities.context_window.max_input_tokens,
                  max_output_tokens: item.capabilities.context_window.max_output_tokens,
                  max_total_tokens: item.capabilities.context_window.max_total_tokens,
                  recommended_input_tokens: item.capabilities.context_window.recommended_input_tokens,
                  recommended_prompt_budget: item.capabilities.context_window.recommended_prompt_budget,
                  compression_trigger_tokens: item.capabilities.context_window.compression_trigger_tokens,
                }
              : undefined,
            cache: item.capabilities.cache
              ? {
                  runtime_context_cache: item.capabilities.cache.runtime_context_cache,
                  prompt_cache: item.capabilities.cache.prompt_cache,
                  response_cache: item.capabilities.cache.response_cache,
                  cache_scope: item.capabilities.cache.cache_scope,
                  runtime_response_cache: item.capabilities.cache.runtime_response_cache,
                  provider_prompt_cache: item.capabilities.cache.provider_prompt_cache,
                  cache_key_strategy: item.capabilities.cache.cache_key_strategy,
                }
              : undefined,
            compression: item.capabilities.compression
              ? {
                  supported: item.capabilities.compression.supported,
                  may_compress: item.capabilities.compression.may_compress,
                  strategy: item.capabilities.compression.strategy,
                }
              : undefined,
            features: Array.isArray(item.capabilities.features)
              ? item.capabilities.features.filter((feature): feature is string => typeof feature === "string" && feature.trim().length > 0)
              : item.capabilities.features && typeof item.capabilities.features === "object"
                ? Object.entries(item.capabilities.features)
                    .filter(([, enabled]) => Boolean(enabled))
                    .map(([feature]) => feature)
                : undefined,
          }
        : undefined,
      metadata: item.metadata
        ? {
            source: typeof item.metadata.source === "string" && item.metadata.source.trim() ? item.metadata.source.trim() : undefined,
            profile_version:
              typeof item.metadata.profile_version === "string" && item.metadata.profile_version.trim()
                ? item.metadata.profile_version.trim()
                : undefined,
          }
        : undefined,
    }));
}


import { ChatStreamChunk, ChatDoneEvent } from "@/lib/types";

/**
 * 流式聊天 - 逐 chunk 读取 SSE 事件并回调
 */
export async function streamChat(
  messages: Array<{ role: string; content: string }>,
  model: string | undefined,
  ragEnabled: boolean,
  onChunk: (chunk: ChatStreamChunk) => void,
  onDone: (event: ChatDoneEvent | null) => void,
  onError: (message: string) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, model, stream: true, rag_enabled: ragEnabled }),
  });

  if (!response.ok) {
    const text = await response.text();
    onError(text || "流式请求失败");
    return;
  }

  if (!response.body) {
    onError("响应体为空");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        if (trimmed.startsWith("event:")) {
          // 检查错误事件类型
          const eventType = trimmed.slice(6).trim();
          if (eventType === "chat.error") {
            // 下一个 data: 行包含错误信息
          }
          continue;
        }
        if (trimmed.startsWith("data:")) {
          const jsonStr = trimmed.slice(5).trim();
          try {
            const data = JSON.parse(jsonStr);
            if (data.error) {
              onError(typeof data.error === "string" ? data.error : JSON.stringify(data.error));
              return;
            }
            if (data.content !== undefined || data.reasoning_content !== undefined) {
              onChunk(data);
            }
            if (data.finish_reason) {
              onChunk(data);
            }
            if (data.usage) {
              onChunk(data);
            }
          } catch {
            // 忽略解析失败的行
          }
        }
      }
    }

    onDone({ model: model ?? "" });
  } catch (err) {
    onError(err instanceof Error ? err.message : "流式读取中断");
  }
}
