import {
  ArchiveDetailResponse,
  ArchiveIndexResponse,
  ContinueDraftPayload,
  ModelListResponse,
  ModelValidationEvent,
  ModelValidationReport,
  ModelOption,
  DashboardResponse,
  RecoverTaskPayload,
  ResultResponse,
  ReviewResponse,
  RagSettingsStatus,
  RagSyncResult,
  StyleProfileListResponse,
  TaskActionPayload,
  TaskCreatePayload,
  TaskRecord,
  WorkspaceResponse,
} from "@/lib/types";
import { createChatSseParser, getStreamChatErrorMessage } from "@/lib/stream-chat-events.mjs";
import { createModelValidationSseParser } from "@/lib/model-validation-events.mjs";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type RequestLogContext = Record<string, unknown>;

interface RequestOptions {
  logContext?: RequestLogContext;
}

interface ApiRequestErrorOptions {
  status: number | null;
  path: string;
  requestId: string;
  detail: string;
  retryable: boolean;
}

export class ApiRequestError extends Error {
  readonly status: number | null;
  readonly path: string;
  readonly requestId: string;
  readonly detail: string;
  readonly retryable: boolean;

  constructor({ status, path, requestId, detail, retryable }: ApiRequestErrorOptions) {
    super(detail);
    this.name = "ApiRequestError";
    this.status = status;
    this.path = path;
    this.requestId = requestId;
    this.detail = detail;
    this.retryable = retryable;
  }
}

function isRetryableHttpStatus(method: string, status: number) {
  if (method !== "GET") return false;
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

function logRequestStart(path: string, method: string, logContext?: RequestLogContext) {
  console.info("http.request.start", {
    method,
    path,
    ...(logContext ?? {}),
  });
}

function logRequestEnd(
  path: string,
  method: string,
  durationMs: number,
  httpStatus: number | null,
  requestId: string,
  logContext?: RequestLogContext,
) {
  console.info("http.request.end", {
    method,
    path,
    http_status: httpStatus,
    request_id: requestId,
    client_duration_ms: durationMs,
    ...(logContext ?? {}),
  });
}

async function request<T>(path: string, init?: RequestInit, options?: RequestOptions): Promise<T> {
  const url = `${API_BASE}${path}`;
  const method = (init?.method ?? "GET").toUpperCase();
  const startedAt = Date.now();
  logRequestStart(path, method, options?.logContext);

  const makeRequest = async (): Promise<Response> => {
    const response = await fetch(url, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
      signal: AbortSignal.timeout(30000),
    });
    return response;
  };

  const canRetry = method === "GET";

  let response: Response;
  try {
    try {
      response = await makeRequest();
    } catch (err) {
      if (canRetry) {
        console.warn(`请求失败，准备重试: ${url}`, err instanceof Error ? err.message : String(err));
        try {
          response = await makeRequest();
        } catch (retryErr) {
          console.error(`请求重试后仍失败: ${url}`, retryErr instanceof Error ? retryErr.message : String(retryErr));
          throw retryErr;
        }
      } else {
        console.error(`请求失败（写操作不重试）: ${url}`, err instanceof Error ? err.message : String(err));
        throw err;
      }
    }
  } catch (err) {
    logRequestEnd(path, method, Date.now() - startedAt, null, "", options?.logContext);
    const detail = err instanceof Error ? err.message : "请求失败";
    throw new ApiRequestError({
      status: null,
      path,
      requestId: "",
      detail,
      retryable: canRetry,
    });
  }

  const httpStatus = response.status;
  const requestId = response.headers.get("X-Request-ID") ?? "";

  if (!response.ok) {
    let errorMessage = "请求失败";
    try {
      const data = await response.clone().json();
      errorMessage = typeof data?.detail === "string" ? data.detail : JSON.stringify(data);
    } catch {
      const text = await response.text();
      errorMessage = text ? text.slice(0, 500) : `HTTP ${response.status}`;
    }
    logRequestEnd(path, method, Date.now() - startedAt, httpStatus, requestId, options?.logContext);
    throw new ApiRequestError({
      status: httpStatus,
      path,
      requestId,
      detail: errorMessage,
      retryable: isRetryableHttpStatus(method, httpStatus),
    });
  }

  logRequestEnd(path, method, Date.now() - startedAt, httpStatus, requestId, options?.logContext);
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

export function getModelCatalog(options?: { refresh?: boolean }) {
  return request<ModelListResponse>(`/api/models${options?.refresh ? "?refresh=true" : ""}`);
}

export function getProtocolSettings() {
  return request<{ default_protocol: string; overrides: Record<string, string> }>("/api/settings/protocols");
}

export function getModelValidation(modelId: string) {
  return request<ModelValidationReport>(`/api/model-validation?model_id=${encodeURIComponent(modelId)}`);
}

export function clearModelValidation(modelId: string) {
  return request<ModelValidationReport>("/api/model-validation", {
    method: "DELETE",
    body: JSON.stringify({ model_id: modelId }),
  });
}

export function setModelProtocol(modelId: string, protocol: string) {
  return request<{ model_id: string; protocol: string }>(`/api/settings/protocols/${encodeURIComponent(modelId)}`, {
    method: "PATCH",
    body: JSON.stringify({ protocol }),
  });
}

export async function getStyleProfiles() {
  const response = await request<StyleProfileListResponse>("/api/style-profiles");
  return Array.isArray(response.items) ? response.items : [];
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

export function runTask(taskId: string, payload?: TaskActionPayload) {
  return request<TaskRecord>(`/api/tasks/${taskId}/run`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function resumeTask(taskId: string, approved: boolean, comment: string, modelId?: string) {
  return request<TaskRecord>(`/api/tasks/${taskId}/resume`, {
    method: "POST",
    body: JSON.stringify(
      modelId && modelId.trim()
        ? { approved, comment, model_id: modelId.trim() }
        : { approved, comment },
    ),
  });
}

export function rollbackChapterPlan(taskId: string, keepBatchCount: number) {
  return request<TaskRecord>(`/api/tasks/${taskId}/rollback-chapter-plan`, {
    method: "POST",
    body: JSON.stringify({ keep_batch_count: keepBatchCount }),
  });
}

export function continueTask(taskId: string, payload: ContinueDraftPayload, logContext?: RequestLogContext) {
  return request<TaskRecord>(`/api/tasks/${taskId}/continue`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, {
    logContext,
  });
}

export function recoverTask(taskId: string, payload?: RecoverTaskPayload) {
  return request<TaskRecord>(`/api/tasks/${taskId}/recover`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export function deleteTask(taskId: string) {
  return request<{ task_id: string; message: string }>(`/api/tasks/${taskId}`, {
    method: "DELETE",
  });
}

export function cancelTask(taskId: string, comment?: string) {
  return request<TaskRecord>(`/api/tasks/${taskId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ comment: comment ?? "" }),
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

export function getReview(taskId: string) {
  return request<ReviewResponse>(`/api/tasks/${taskId}/review`);
}

export function getResult(taskId: string) {
  return request<ResultResponse>(`/api/tasks/${taskId}/result`);
}

export function archiveTask(taskId: string) {
  return request<TaskRecord>(`/api/tasks/${taskId}/archive`, {
    method: "POST",
  });
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
            compatibility:
              typeof item.metadata.compatibility === "string" && item.metadata.compatibility.trim()
                ? item.metadata.compatibility.trim()
                : undefined,
            profile_version:
              typeof item.metadata.profile_version === "string" && item.metadata.profile_version.trim()
                ? item.metadata.profile_version.trim()
                : undefined,
            validation:
              item.metadata.validation && typeof item.metadata.validation === "object"
                ? item.metadata.validation
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
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, model, stream: true, rag_enabled: ragEnabled }),
      signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      console.log("streamChat 用户主动取消");
      onDone(null);
      return;
    }
    const msg = getStreamChatErrorMessage(err);
    console.error("streamChat 网络请求异常:", msg);
    onError(msg);
    return;
  }

  if (!response.ok) {
    let errorMessage = "流式请求失败";
    try {
      const data = await response.json();
      errorMessage = typeof data?.detail === "string" ? data.detail : JSON.stringify(data);
    } catch {
      const text = await response.text();
      errorMessage = text ? text.slice(0, 500) : `HTTP ${response.status}`;
    }
    console.error("streamChat 请求失败:", errorMessage);
    onError(errorMessage);
    return;
  }

  if (!response.body) {
    onError("响应体为空");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createChatSseParser({
    onChunk,
    onError: (message: string) => {
      console.error("streamChat 收到错误事件:", message);
      onError(message);
    },
  });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const shouldContinue = parser.push(decoder.decode(value, { stream: true }));
      if (!shouldContinue) {
        return;
      }
    }

    if (!parser.flush()) {
      return;
    }
    onDone({ model: model ?? "" });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      console.log("streamChat 用户主动取消");
      onDone(null);
      return;
    }
    const msg = err instanceof Error ? err.message : "流式读取中断";
    console.error("streamChat 流式读取异常:", msg);
    onError(msg);
  }
}

export async function streamModelValidation(
  modelId: string,
  callbacks: {
    onEvent: (event: ModelValidationEvent) => void;
    onError: (message: string) => void;
    onDone?: () => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/model-validation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId }),
      signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      callbacks.onDone?.();
      return;
    }
    callbacks.onError(getStreamChatErrorMessage(err));
    return;
  }

  if (!response.ok) {
    let errorMessage = "模型验证请求失败";
    try {
      const data = await response.json();
      errorMessage = typeof data?.detail === "string" ? data.detail : JSON.stringify(data);
    } catch {
      const text = await response.text();
      errorMessage = text ? text.slice(0, 500) : `HTTP ${response.status}`;
    }
    callbacks.onError(errorMessage);
    return;
  }

  if (!response.body) {
    callbacks.onError("模型验证响应体为空");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createModelValidationSseParser({
    onEvent: callbacks.onEvent,
    onError: callbacks.onError,
  });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
    }
    parser.flush();
    callbacks.onDone?.();
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      callbacks.onDone?.();
      return;
    }
    callbacks.onError(err instanceof Error ? err.message : "模型验证流式读取中断");
  }
}
