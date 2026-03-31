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

export function getArchiveList() {
  return request<ArchiveIndexResponse>("/api/archive");
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
    }));
}
