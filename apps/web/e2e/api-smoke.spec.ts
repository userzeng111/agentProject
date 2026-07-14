import { expect, test } from "@playwright/test";
import {
  apiPath,
  createDraftTask,
  deleteTaskIfAllowed,
  expectJsonOk,
  expectLocalCorsAllowed,
  readWorkspace,
  uploadTextAsset,
} from "./helpers/api";

function expectOwnKeys(value: unknown, label: string, keys: string[]) {
  expect(value && typeof value === "object" && !Array.isArray(value), `${label} 应为对象`).toBeTruthy();
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    expect(Object.prototype.hasOwnProperty.call(record, key), `${label} 应包含字段 ${key}`).toBeTruthy();
  }
}

function expectOptionalOwnKeys(value: unknown, label: string, keys: string[]) {
  expect(value && typeof value === "object" && !Array.isArray(value), `${label} 应为对象`).toBeTruthy();
  if (Object.keys(value as Record<string, unknown>).length > 0) {
    expectOwnKeys(value, label, keys);
  }
}

test.describe("API 基线覆盖", () => {
  test("基础目录、设置与归档只读接口可用", async ({ request }) => {
    await expectJsonOk(await request.get(apiPath("/api/health")), "health");
    const models = await expectJsonOk<{ data?: unknown[] }>(await request.get(apiPath("/api/models")), "models");
    expect(Array.isArray(models.data), "models.data 应为数组").toBeTruthy();
    await expectJsonOk(await request.get(apiPath("/api/dashboard")), "dashboard");
    await expectJsonOk(await request.get(apiPath("/api/style-profiles")), "style-profiles");
    await expectJsonOk(await request.get(apiPath("/api/settings/rag")), "settings/rag");
    await expectJsonOk(await request.get(apiPath("/api/settings/protocols")), "settings/protocols");
    await expectJsonOk(await request.get(apiPath("/api/archive")), "archive");
    await expectLocalCorsAllowed(request);
  });

  test("任务轻量生命周期覆盖 created 与 sources_ingested", async ({ request }) => {
    let taskId = "";
    try {
      const task = await createDraftTask(request, "Playwright API 生命周期");
      taskId = task.id;

      await expectJsonOk(await request.get(apiPath(`/api/tasks/${taskId}`)), "任务详情");
      const workspace = await readWorkspace(request, taskId);
      expectOwnKeys(workspace, "workspace", [
        "meta",
        "recent_events",
        "active_trace_summary",
        "available_tabs",
        "allowed_actions",
        "recommended_action",
        "blocked_reason",
        "state_reconciled",
        "reconciliation_kind",
        "reconciliation_summary",
        "recovery_options",
        "request_preview",
        "context_status",
        "response_cache_status",
        "pending_review_summary",
        "rag_status",
        "llm_report",
        "novel_progress",
        "sources",
        "supervisor_plan",
        "agent_runs",
        "auto_review_trace",
        "outline_phase",
        "outline_completed_count",
        "outline_total_count",
      ]);
      expect(Array.isArray(workspace.recent_events), "workspace.recent_events 应为数组").toBeTruthy();
      expect(Array.isArray(workspace.available_tabs), "workspace.available_tabs 应为数组").toBeTruthy();
      expect(workspace.available_tabs, "workspace.available_tabs 应包含请求摘要").toContain("request");
      expect(workspace.available_tabs, "workspace.available_tabs 应包含事件日志").toContain("events");
      expect(workspace.available_tabs, "workspace.available_tabs 应包含 Supervisor").toContain("supervisor");
      expect(Array.isArray(workspace.sources), "workspace.sources 应为数组").toBeTruthy();
      expect(Array.isArray(workspace.agent_runs), "workspace.agent_runs 应为数组").toBeTruthy();
      expect(Array.isArray(workspace.auto_review_trace), "workspace.auto_review_trace 应为数组").toBeTruthy();
      expectOwnKeys(workspace.pending_review_summary, "pending_review_summary", [
        "present",
        "review_type",
        "stage",
        "batch_index",
        "revision_count",
        "outline_phase",
        "summary",
      ]);
      expectOwnKeys(workspace.rag_status, "rag_status", [
        "enabled",
        "ready",
        "source",
        "summary",
        "last_query_stage",
        "last_error",
        "injected",
        "injection_evidence",
      ]);
      expectOwnKeys(workspace.meta, "meta", ["model_id", "creative_model_id"]);
      expect(workspace.meta, "meta 不应返回旧默认模型字段").not.toHaveProperty("default_model_id");
      expectOwnKeys(workspace.request_preview, "request_preview", ["prompt", "model_id", "creative_model_id"]);
      expect(workspace.request_preview, "request_preview 不应返回旧默认模型字段").not.toHaveProperty("default_model_id");
      expectOptionalOwnKeys(workspace.context_status, "context_status", ["status", "summary"]);
      expectOptionalOwnKeys(workspace.response_cache_status, "response_cache_status", ["status", "summary"]);
      expectOptionalOwnKeys(workspace.llm_report, "llm_report", ["request_count", "usage_total"]);
      expectOptionalOwnKeys(workspace.novel_progress, "novel_progress", [
        "target_chapter_count",
        "planned_chapter_count",
        "completed_chapter_count",
      ]);

      await expectJsonOk(await request.get(apiPath(`/api/tasks/${taskId}/supervisor`)), "Supervisor");
      await expectJsonOk(await request.get(apiPath(`/api/tasks/${taskId}/chapters`)), "章节列表");
      await expectJsonOk(await request.get(apiPath(`/api/tasks/${taskId}/artifacts`)), "产物列表");

      const review = await request.get(apiPath(`/api/tasks/${taskId}/review`));
      expect([400, 404], "created 阶段 review 应未就绪").toContain(review.status());
      const result = await request.get(apiPath(`/api/tasks/${taskId}/result`));
      expect([400, 404], "created 阶段 result 应未就绪").toContain(result.status());

      const uploaded = await uploadTextAsset(request, taskId);
      expect(uploaded.id).toBe(taskId);
      await expectJsonOk(await request.get(apiPath(`/api/tasks/${taskId}`)), "素材上传后任务详情");

      const invalidRef = await request.get(apiPath("/api/file-text?ref=/tasklog/invalid/path.txt"));
      expect([400, 404], "无效 file-text ref").toContain(invalidRef.status());
      const invalidTaskFile = await request.get(apiPath(`/api/tasks/${taskId}/files/bad%20path.txt`));
      expect([400, 404], "非法任务文件路径").toContain(invalidTaskFile.status());
    } finally {
      await deleteTaskIfAllowed(request, taskId);
    }
  });

  test("写接口负例返回受控错误且不触发真实生成", async ({ request }) => {
    const deprecatedDefaultModel = await request.patch(apiPath("/api/settings/default-model"), {
      data: { model_id: "playwright-deprecated-model" },
    });
    expect(deprecatedDefaultModel.status(), "全局默认模型设置接口已废弃，应返回 410").toBe(410);

    const invalidProtocol = await request.patch(apiPath("/api/settings/protocols/playwright-invalid-model"), {
      data: { protocol: "invalid" },
    });
    expect(invalidProtocol.status(), "非法模型协议应返回 400").toBe(400);

    const missingTaskId = "task_playwright_missing";
    const taskWriteCases = [
      { label: "run", path: `/api/tasks/${missingTaskId}/run`, data: {} },
      { label: "cancel", path: `/api/tasks/${missingTaskId}/cancel`, data: { comment: "Playwright 负例" } },
      { label: "resume", path: `/api/tasks/${missingTaskId}/resume`, data: { approved: true, comment: "Playwright 负例" } },
      {
        label: "continue",
        path: `/api/tasks/${missingTaskId}/continue`,
        data: { requested_chapter_count: 1, continue_request_id: "playwright-negative" },
      },
      { label: "recover", path: `/api/tasks/${missingTaskId}/recover`, data: { recovery_mode: "recover_to_stable" } },
      { label: "rollback", path: `/api/tasks/${missingTaskId}/rollback-chapter-plan`, data: { keep_batch_count: 0 } },
    ];

    for (const item of taskWriteCases) {
      const response = await request.post(apiPath(item.path), { data: item.data });
      expect([400, 404, 409], `${item.label} 负例 status=${response.status()}`).toContain(response.status());
    }

    const invalidChatStream = await request.post(apiPath("/api/chat/stream"));
    expect(invalidChatStream.status(), "chat stream 缺少请求体应由 FastAPI 校验拦截").toBe(422);
    const invalidChatCompletions = await request.post(apiPath("/api/chat/completions"));
    expect(invalidChatCompletions.status(), "chat completions 缺少请求体应由 FastAPI 校验拦截").toBe(422);
  });
});
