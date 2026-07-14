import { expect, test } from "@playwright/test";
import { createDraftTask, deleteTaskIfAllowed, readWorkspace } from "./helpers/api";
import { expectNoSensitiveText, SENSITIVE_TERMS } from "./helpers/assertions";

function expectOwnKeys(value: unknown, label: string, keys: string[]) {
  expect(value && typeof value === "object" && !Array.isArray(value), `${label} 应为对象`).toBeTruthy();
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    expect(Object.prototype.hasOwnProperty.call(record, key), `${label} 应包含字段 ${key}`).toBeTruthy();
  }
}

function expectNoSensitiveKeysOrText(value: unknown, label: string) {
  const serialized = JSON.stringify(value);
  for (const term of SENSITIVE_TERMS) {
    expect(serialized, `${label} 不应包含敏感字段或正文：${term}`).not.toContain(term);
  }
}

test.describe("a27c48b 调试中心回归监控", () => {
  test("workspace 调试摘要契约和 UI 入口保持可用", async ({ page, request }) => {
    let taskId = "";
    try {
      const task = await createDraftTask(request, "Playwright a27c48b 回归");
      taskId = task.id;
      const workspace = await readWorkspace(request, taskId);

      expectOwnKeys(workspace.pending_review_summary, "pending_review_summary", [
        "present",
        "review_type",
        "stage",
        "batch_index",
        "revision_count",
        "outline_phase",
        "summary",
      ]);
      expect(workspace.pending_review_summary).toMatchObject({
        present: false,
      });
      expectNoSensitiveKeysOrText(workspace.pending_review_summary, "pending_review_summary");
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
      expect(workspace.rag_status).toEqual(
        expect.objectContaining({
          enabled: expect.any(Boolean),
          ready: expect.any(Boolean),
          summary: expect.any(String),
        }),
      );
      expectNoSensitiveKeysOrText(workspace.rag_status, "rag_status");

      await page.goto(`/p/${taskId}/`, { waitUntil: "commit" });
      await expect(page.getByRole("tab", { name: /调试/ })).toBeVisible();
      await page.getByRole("tab", { name: /调试/ }).click();
      await expect(page.getByRole("heading", { name: "诊断结论" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "上下文/RAG" })).toBeVisible();
      await expect(page.getByRole("heading", { name: /^RAG/ })).toBeVisible();
      await expect(page.getByRole("heading", { name: "状态对账" })).toBeVisible();
      await expectNoSensitiveText(page);
    } finally {
      await deleteTaskIfAllowed(request, taskId);
    }
  });
});
