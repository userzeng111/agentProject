import { expect, test } from "@playwright/test";
import { mockCommonApiRoutes } from "./helpers/fixtures";

test.describe("聊天与设置页面", () => {
  test("聊天页空输入保持禁用并展示流式错误", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/chat/stream", async (route) => {
      await route.fulfill({
        status: 503,
        json: { detail: "聊天服务不可用 fixture" },
      });
    });

    await page.goto("/chat", { waitUntil: "commit" });
    await expect(page.getByText("默认：gpt-5.4")).toBeVisible();
    const sendButton = page.getByRole("button", { name: "发送消息" });
    await expect(sendButton).toBeDisabled();
    const input = page.getByRole("textbox", { name: "输入消息，按回车发送..." });
    await input.fill("触发错误");
    await expect(sendButton).toBeEnabled();
    await input.press("Enter");
    await expect(page.getByText("触发错误").last()).toBeVisible();
    await expect(page.getByText(/错误: .*聊天服务不可用 fixture/)).toBeVisible();
  });

  test("聊天页支持新对话、输入和流式响应展示", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/chat/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'event: chat.chunk\ndata: {"reasoning_content":"思考中"}\n\n',
          'event: chat.chunk\ndata: {"content":"自动化回复","usage":{"total_tokens":12}}\n\n',
          'event: chat.done\ndata: {"finish_reason":"stop"}\n\n',
        ].join(""),
      });
    });

    await page.goto("/chat", { waitUntil: "commit" });
    await expect(page.getByRole("button", { name: /新对话/ })).toBeVisible();
    await expect(page.getByText("默认：gpt-5.4")).toBeVisible();
    const input = page.getByRole("textbox", { name: "输入消息，按回车发送..." });
    await expect(input).toBeVisible();
    await input.fill("你好");
    await expect(input).toHaveValue("你好");
    await expect(page.getByRole("button", { name: "发送消息" })).toBeEnabled();
    await input.press("Enter");
    await expect(page.getByText("你好").first()).toBeVisible();
    await expect(page.getByText("自动化回复")).toBeVisible();
    await expect(page.getByText(/tokens/)).toBeVisible();
  });

  test("设置页展示 RAG 状态并允许取消重建确认", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.goto("/settings", { waitUntil: "commit" });
    await expect(page.getByText("小说 RAG 数据库")).toBeVisible();
    await expect(page.getByText(/数据库可用|尚未构建/)).toBeVisible();
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("确认全量扫描");
      await dialog.dismiss();
    });
    await page.getByRole("button", { name: /全量重建索引/ }).click();
    await expect(page.getByText("模型协议配置")).toBeVisible();
  });

  test("设置页允许确认重建索引并保存模型协议", async ({ page }) => {
    await mockCommonApiRoutes(page);
    let rebuildRequests = 0;
    let protocolRequests = 0;
    await page.route("**/api/settings/rag/rebuild", async (route) => {
      rebuildRequests += 1;
      await route.fulfill({
        json: {
          success: true,
          message: "重建完成 fixture",
          scanned_files: 2,
          indexed_documents: 3,
          output_dir: "/tmp/rag",
          duration_ms: 12,
          sources: ["fixture"],
          warnings: [],
          finished_at: "2026-06-24T00:00:00.000Z",
        },
      });
    });
    await page.route("**/api/settings/protocols/gpt-5.4", async (route) => {
      protocolRequests += 1;
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      expect(payload.protocol).toBe("anthropic");
      await route.fulfill({ json: { model_id: "gpt-5.4", protocol: "anthropic" } });
    });

    await page.goto("/settings", { waitUntil: "commit" });
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("确认全量扫描");
      await dialog.accept();
    });
    await page.getByRole("button", { name: /全量重建索引/ }).click();
    await expect.poll(() => rebuildRequests, { message: "确认重建应请求 rebuild API" }).toBe(1);

    await page.getByLabel("协议").click();
    await page.getByRole("option", { name: "Anthropic" }).click();
    await expect.poll(() => protocolRequests, { message: "协议选择应请求保存接口" }).toBe(1);
    await expect(page.getByText("已保存：gpt-5.4 → anthropic")).toBeVisible();
  });
});
