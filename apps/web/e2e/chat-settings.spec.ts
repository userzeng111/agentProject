import { expect, test } from "@playwright/test";
import { mockCommonApiRoutes } from "./helpers/fixtures";

async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
  await expect
    .poll(async () =>
      page.evaluate(() =>
        document.documentElement.scrollWidth <= window.innerWidth &&
        document.body.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
}

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

  test("聊天页移动端长文本不溢出且思考过程支持键盘展开", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockCommonApiRoutes(page);
    const longToken = "LONG_CHAT_TOKEN_".repeat(24);
    await page.route("**/api/chat/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          `event: chat.chunk\ndata: ${JSON.stringify({ reasoning_content: `推理${longToken}` })}\n\n`,
          `event: chat.chunk\ndata: ${JSON.stringify({ content: `回复${longToken}`, usage: { total_tokens: 42 } })}\n\n`,
          'event: chat.done\ndata: {"finish_reason":"stop"}\n\n',
        ].join(""),
      });
    });

    await page.goto("/chat", { waitUntil: "commit" });
    await page.getByRole("textbox", { name: "输入消息，按回车发送..." }).fill(`用户${longToken}`);
    await page.getByRole("button", { name: "发送消息" }).click();

    await expect(page.getByText(`回复${longToken}`)).toBeVisible();
    const thinkingButton = page.getByRole("button", { name: /思考过程|正在思考/ });
    await expect(thinkingButton).toBeVisible();
    await expect(thinkingButton).toHaveAttribute("aria-expanded", "false");

    await thinkingButton.focus();
    await page.keyboard.press("Enter");
    await expect(thinkingButton).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByText(`推理${longToken}`)).toBeVisible();
    await page.keyboard.press("Space");
    await expect(thinkingButton).toHaveAttribute("aria-expanded", "false");
    await expectNoHorizontalOverflow(page);
  });

  test("聊天页 320px 移动端标题栏不产生横向溢出", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 740 });
    const longModelId = "gpt-5.4-chat-default-model-with-an-intentionally-long-unbroken-identifier-20260701";
    await page.route("**/api/models**", async (route) => {
      await route.fulfill({
        json: {
          data: [
            {
              id: longModelId,
              display_name: "GPT 5.4 Chat Mobile Overflow Regression Fixture With Long Name",
              provider: "gateway-provider-with-an-intentionally-long-unbroken-name",
              metadata: { source: "gateway:list_models" },
              capabilities: {
                features: ["novel"],
                context_window: { max_input_tokens: 8000, max_output_tokens: 4000 },
                cache: { runtime_context_cache: true, prompt_cache: true, response_cache: true },
                compression: { supported: true, strategy: "summary" },
              },
            },
          ],
          meta: { default_model: longModelId, cached: true },
        },
      });
    });
    await page.route("**/api/settings/rag**", async (route) => {
      await route.fulfill({
        json: {
          available: true,
          library_dir: "/tmp/rag",
          faiss_index_path: "/tmp/rag/index.faiss",
          sqlite_path: "/tmp/rag/meta.sqlite",
          sources: ["fixture"],
          last_result: null,
        },
      });
    });
    await page.route("**/api/model-validation**", async (route) => {
      await route.fulfill({ json: { model_id: longModelId, status: "unverified" } });
    });

    await page.goto("/chat", { waitUntil: "commit" });

    await expect(page.getByRole("button", { name: "打开会话列表" })).toBeVisible();
    await expect(page.getByRole("button", { name: "验证" })).toBeVisible();
    await expect(page.getByLabel("聊天模型")).toBeVisible();
    await expect(page.getByText(`默认：${longModelId}`)).toBeVisible();
    for (const name of ["首页", "AI 对话", "创建任务", "归档", "设置"]) {
      const box = await page.getByRole("link", { name }).boundingBox();
      expect(box, `${name} 顶部导航入口应可见`).not.toBeNull();
      expect(box!.width, `${name} 顶部导航触控宽度应不小于 44px`).toBeGreaterThanOrEqual(44);
      expect(box!.x, `${name} 顶部导航不应向左越界`).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width, `${name} 顶部导航不应向右越界`).toBeLessThanOrEqual(320);
    }
    await expectNoHorizontalOverflow(page);
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
