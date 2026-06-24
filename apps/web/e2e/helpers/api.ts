import { APIRequestContext, expect } from "@playwright/test";

export const FRONTEND_URL = process.env.PLAYWRIGHT_FRONTEND_URL ?? "http://127.0.0.1:3000";
export const BACKEND_URL = process.env.PLAYWRIGHT_BACKEND_URL ?? "http://127.0.0.1:8000";

export type TestTask = {
  id: string;
  status?: string;
};

export function apiPath(path: string) {
  return `${BACKEND_URL}${path}`;
}

export async function expectJsonOk<T = Record<string, unknown>>(
  response: Awaited<ReturnType<APIRequestContext["get"]>>,
  label: string,
): Promise<T> {
  expect(response.ok(), `${label} status=${response.status()}`).toBeTruthy();
  return response.json() as Promise<T>;
}

export async function chooseTaskModel(request: APIRequestContext): Promise<string> {
  const response = await request.get(apiPath("/api/models"));
  const payload = await expectJsonOk<{ data?: Array<{ id: string; metadata?: Record<string, unknown> }> }>(
    response,
    "读取模型列表",
  );
  const models = payload.data ?? [];
  return (
    models.find((item) => item.id === "gpt-5.4")?.id ||
    models.find((item) => String(item.metadata?.source ?? "").includes("gateway"))?.id ||
    models[0]?.id ||
    "gpt-5.4"
  );
}

export async function createDraftTask(request: APIRequestContext, titleHint = "Playwright 自动化测试") {
  const modelId = await chooseTaskModel(request);
  const response = await request.post(apiPath("/api/tasks"), {
    data: {
      creative_mode: "original",
      novel_size: "short",
      target_chapter_count: 8,
      prompt: "Playwright 自动化测试任务，请勿进入真实生成流程。",
      genre: "自动化",
      style: "清晰克制",
      chapter_word_min: 1000,
      audience: "测试读者",
      banned: "",
      title_hint: titleHint,
      model_id: modelId,
      auto_review: false,
    },
  });
  return expectJsonOk<TestTask>(response, "创建测试任务");
}

export async function deleteTaskIfAllowed(request: APIRequestContext, taskId?: string) {
  if (!taskId) {
    return;
  }
  const response = await request.delete(apiPath(`/api/tasks/${taskId}`));
  expect([200, 400, 404, 409], `清理测试任务 status=${response.status()}`).toContain(response.status());
}

export async function uploadTextAsset(
  request: APIRequestContext,
  taskId: string,
  filename = "playwright-reference.txt",
  content = "这是 Playwright 自动化测试素材。",
) {
  const response = await request.post(apiPath(`/api/tasks/${taskId}/assets`), {
    multipart: {
      file: {
        name: filename,
        mimeType: "text/plain",
        buffer: Buffer.from(content, "utf-8"),
      },
    },
  });
  return expectJsonOk<TestTask>(response, "上传测试素材");
}

export async function readWorkspace(request: APIRequestContext, taskId: string) {
  const response = await request.get(apiPath(`/api/tasks/${taskId}/workspace`));
  return expectJsonOk<Record<string, unknown>>(response, "读取工作台");
}

export async function expectLocalCorsAllowed(request: APIRequestContext) {
  const response = await request.fetch(apiPath("/api/health"), {
    method: "OPTIONS",
    headers: {
      Origin: "http://localhost:3000",
      "Access-Control-Request-Method": "GET",
    },
  });
  expect(response.status(), "本地 CORS 预检状态").toBe(200);
  expect(response.headers()["access-control-allow-origin"], "本地 CORS allow-origin").toBe("http://localhost:3000");
}
