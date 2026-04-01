import {
  ArchiveDetailResponse,
  ArchiveIndexResponse,
  ModelListResponse,
  ModelOption,
  DashboardResponse,
  ResultResponse,
  ReviewResponse,
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

export async function updateDefaultModel(modelId: string) {
  return request<{ default_model: string; supported_models: string[] }>("/api/settings/default-model", {
    method: "PATCH",
    body: JSON.stringify({ model_id: modelId }),
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

export function getDashboard() {
  return request<DashboardResponse>("/api/dashboard");
}

export function getWorkspace(taskId: string) {
  return request<WorkspaceResponse>(`/api/tasks/${taskId}/workspace`);
}

export function getReview(taskId: string) {
  return request<ReviewResponse>(`/api/tasks/${taskId}/review`);
}

export function getResult(taskId: string) {
  return request<ResultResponse>(`/api/tasks/${taskId}/result`);
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
