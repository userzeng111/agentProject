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

function makeChatModel(id: string) {
  return {
    id,
    display_name: `聊天模型 ${id}`,
    provider: "gateway",
    metadata: { source: "gateway:list_models", compatibility: "unverified" },
    capabilities: {
      features: ["chat"],
      context_window: { max_input_tokens: 8000, max_output_tokens: 4000 },
    },
  };
}

async function selectChatModel(
  page: import("@playwright/test").Page,
  optionName: string | RegExp,
  expectedModelId: string,
) {
  const modelSelect = page.getByRole("combobox", { name: "聊天模型" });
  await modelSelect.click();
  const modelOption = page.getByRole("option", { name: optionName });
  await expect(modelOption).toBeVisible();
  await modelOption.click();
  await expect(modelSelect).toContainText(expectedModelId);
}

function waitForModelCatalog(page: import("@playwright/test").Page) {
  return page.waitForResponse((response) => response.url().includes("/api/models") && response.status() === 200);
}

test.describe("聊天与设置页面", () => {
  test("聊天模型必须由用户显式选择，选择后才能发送和运行验证", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/model-validation**", async (route) => {
      await route.fulfill({ json: { model_id: "gpt-5.4", status: "unverified" } });
    });

    const modelsReady = waitForModelCatalog(page);
    await page.goto("/chat", { waitUntil: "commit" });
    await modelsReady;

    const sendButton = page.getByRole("button", { name: "发送消息" });
    const input = page.getByRole("textbox", { name: "输入消息，按回车发送..." });
    await input.fill("等待选择模型");
    await expect(sendButton).toBeDisabled();

    await selectChatModel(page, /GPT 5\.4/, "gpt-5.4");
    await expect(sendButton).toBeEnabled();

    const isMobile = await page.evaluate(() => window.matchMedia("(max-width: 599.95px)").matches);
    if (isMobile) {
      await page.getByRole("button", { name: "验证" }).click();
    }
    await expect(page.getByRole("button", { name: "运行验证" })).toBeEnabled();
  });

  test("模型目录加载期间刷新页面仍保留用户已选聊天模型", async ({ page }) => {
    const model = {
      id: "gpt-5.4",
      display_name: "GPT 5.4",
      provider: "gateway",
      metadata: { source: "gateway:list_models", compatibility: "unverified" },
    };
    let holdCatalog = false;
    const delayedResolvers: Array<() => void> = [];
    await page.route("**/api/models**", async (route) => {
      if (holdCatalog) {
        await new Promise<void>((resolve) => delayedResolvers.push(resolve));
      }
      await route.fulfill({ json: { data: [model], meta: { cached: true } } });
    });
    await page.route("**/api/settings/rag**", async (route) => {
      await route.fulfill({ json: { available: true, sources: [], last_result: null } });
    });
    await page.route("**/api/model-validation**", async (route) => {
      await route.fulfill({ json: { model_id: model.id, status: "unverified" } });
    });

    const firstCatalog = waitForModelCatalog(page);
    await page.goto("/chat", { waitUntil: "commit" });
    await firstCatalog;
    await selectChatModel(page, /GPT 5\.4/, model.id);
    await expect
      .poll(() =>
        page.evaluate(() => {
          const activeId = localStorage.getItem("chat_active_conversation");
          const conversations = JSON.parse(localStorage.getItem("chat_conversations") || "{}");
          return activeId ? conversations[activeId]?.model ?? "" : "";
        }),
      )
      .toBe(model.id);

    holdCatalog = true;
    await page.reload({ waitUntil: "commit" });
    await expect.poll(() => delayedResolvers.length).toBeGreaterThan(0);
    await expect
      .poll(() =>
        page.evaluate(() => {
          const activeId = localStorage.getItem("chat_active_conversation");
          const conversations = JSON.parse(localStorage.getItem("chat_conversations") || "{}");
          return activeId ? conversations[activeId]?.model ?? "" : "";
        }),
      )
      .toBe(model.id);

    holdCatalog = false;
    for (const resolve of delayedResolvers.splice(0)) {
      resolve();
    }
    await expect(page.getByRole("combobox", { name: "聊天模型" })).toContainText(model.id);
  });

  test("移动端长模型目录在视口内滚动而不穿透页面", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const models = Array.from({ length: 34 }, (_, index) => makeChatModel(`gateway-model-${String(index + 1).padStart(2, "0")}`));
    await page.route("**/api/models**", async (route) => {
      await route.fulfill({ json: { data: models, meta: { cached: true } } });
    });
    await page.route("**/api/settings/rag**", async (route) => {
      await route.fulfill({ json: { available: true, sources: [], last_result: null } });
    });

    const modelsReady = waitForModelCatalog(page);
    await page.goto("/chat", { waitUntil: "commit" });
    await modelsReady;
    await page.getByRole("combobox", { name: "聊天模型" }).click();

    const menu = page.locator('[role="listbox"]');
    await expect(menu).toBeVisible();
    const menuPaper = page.getByTestId("chat-model-menu");
    await expect(menuPaper).toBeVisible();
    const dimensions = await menuPaper.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
        top: rect.top,
        bottom: rect.bottom,
      };
    });

    expect(dimensions.clientHeight).toBeLessThanOrEqual(420);
    expect(dimensions.scrollHeight).toBeGreaterThan(dimensions.clientHeight);
    expect(dimensions.top).toBeGreaterThanOrEqual(0);
    expect(dimensions.bottom).toBeLessThanOrEqual(844);
    const lastModel = page.getByRole("option", { name: /gateway-model-34/ });
    await lastModel.scrollIntoViewIfNeeded();
    await lastModel.click();
    await expect(page.getByRole("combobox", { name: "聊天模型" })).toContainText("gateway-model-34");
    await expectNoHorizontalOverflow(page);
  });

  test("聊天页空输入保持禁用并展示流式错误", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/chat/stream", async (route) => {
      await route.fulfill({
        status: 503,
        json: { detail: "聊天服务不可用 fixture" },
      });
    });

    const modelsReady = waitForModelCatalog(page);
    await page.goto("/chat", { waitUntil: "commit" });
    await modelsReady;
    await expect(page.getByText("请选择当前在线模型后再发送消息")).toBeVisible();
    const sendButton = page.getByRole("button", { name: "发送消息" });
    await expect(sendButton).toBeDisabled();
    const input = page.getByRole("textbox", { name: "输入消息，按回车发送..." });
    await input.fill("触发错误");
    await expect(sendButton).toBeDisabled();
    await selectChatModel(page, /GPT 5\.4/, "gpt-5.4");
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

    const modelsReady = waitForModelCatalog(page);
    await page.goto("/chat", { waitUntil: "commit" });
    await modelsReady;
    const isMobile = await page.evaluate(() => window.matchMedia("(max-width: 599.95px)").matches);
    await expect(
      isMobile
        ? page.getByRole("button", { name: "打开会话列表" })
        : page.getByRole("button", { name: "新对话", exact: true }),
    ).toBeVisible();
    const input = page.getByRole("textbox", { name: "输入消息，按回车发送..." });
    await expect(input).toBeVisible();
    await input.fill("你好");
    await expect(input).toHaveValue("你好");
    await selectChatModel(page, /GPT 5\.4/, "gpt-5.4");
    await expect(page.getByRole("button", { name: "发送消息" })).toBeEnabled();
    await input.press("Enter");
    await expect(page.getByText("你好").first()).toBeVisible();
    await expect(page.getByText("自动化回复")).toBeVisible();
    await expect(page.getByText(/tokens/)).toBeVisible();
  });

  test("流式期间点击当前会话不会覆盖新消息或旧存档", async ({ page }) => {
    const conversationId = "conv_streaming_current_fixture";
    await page.addInitScript(({ id }) => {
      const now = Date.now();
      localStorage.setItem(
        "chat_conversations",
        JSON.stringify({
          [id]: {
            id,
            title: "流式回归会话",
            messages: [
              { role: "user", content: "旧问题", createdAt: now - 2_000 },
              { role: "assistant", content: "旧回复", createdAt: now - 1_000 },
            ],
            createdAt: now - 2_000,
            updatedAt: now - 1_000,
            model: "gpt-5.4",
          },
        }),
      );
      localStorage.setItem("chat_active_conversation", id);
    }, { id: conversationId });

    await mockCommonApiRoutes(page);
    let signalRequestStarted = () => {};
    const requestStarted = new Promise<void>((resolve) => {
      signalRequestStarted = resolve;
    });
    let releaseResponse = () => {};
    const responseGate = new Promise<void>((resolve) => {
      releaseResponse = resolve;
    });
    await page.route("**/api/chat/stream", async (route) => {
      signalRequestStarted();
      await responseGate;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'event: chat.chunk\ndata: {"content":"新回复","usage":{"total_tokens":8}}\n\n',
          'event: chat.done\ndata: {"finish_reason":"stop"}\n\n',
        ].join(""),
      });
    });

    const modelsReady = waitForModelCatalog(page);
    await page.goto("/chat", { waitUntil: "commit" });
    await modelsReady;
    await expect(page.getByRole("combobox", { name: "聊天模型" })).toContainText("gpt-5.4");

    const input = page.getByRole("textbox", { name: "输入消息，按回车发送..." });
    await input.fill("新问题");
    await input.press("Enter");
    await requestStarted;

    try {
      const isMobile = await page.evaluate(() => window.matchMedia("(max-width: 599.95px)").matches);
      if (isMobile) {
        await page.getByRole("button", { name: "打开会话列表" }).click();
      }
      await page
        .getByRole("list", { name: "会话列表" })
        .getByRole("button", { name: /旧问题/ })
        .click();
      await expect(page.getByText("新问题", { exact: true })).toBeVisible();
      await expect(page.getByText("旧回复", { exact: true })).toBeVisible();
    } finally {
      releaseResponse();
    }

    await expect(page.getByText("新回复", { exact: true })).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(() => {
          const activeId = localStorage.getItem("chat_active_conversation");
          const conversations = JSON.parse(localStorage.getItem("chat_conversations") || "{}") as Record<
            string,
            { messages?: Array<{ role: string; content: string }> }
          >;
          return activeId
            ? (conversations[activeId]?.messages ?? []).map(({ role, content }) => ({ role, content }))
            : [];
        }),
      )
      .toEqual([
        { role: "user", content: "旧问题" },
        { role: "assistant", content: "旧回复" },
        { role: "user", content: "新问题" },
        { role: "assistant", content: "新回复" },
      ]);
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

    const modelsReady = waitForModelCatalog(page);
    await page.goto("/chat", { waitUntil: "commit" });
    await modelsReady;
    await page.getByRole("textbox", { name: "输入消息，按回车发送..." }).fill(`用户${longToken}`);
    await selectChatModel(page, /GPT 5\.4/, "gpt-5.4");
    await page.getByRole("button", { name: "发送消息" }).click();

    await expect(page.getByText(`回复${longToken}`)).toBeVisible();
    const tokenUsage = page.getByTestId("chat-token-usage");
    const messageContent = page.getByTestId("chat-message-content").last();
    await expect(tokenUsage).toHaveText("42 tokens");
    const tokenWidth = await tokenUsage.boundingBox();
    const messageWidth = await messageContent.boundingBox();
    expect(tokenWidth, "token 用量应保持为紧凑元数据").not.toBeNull();
    expect(messageWidth, "助手消息正文应可见").not.toBeNull();
    expect(tokenWidth!.width, "token 用量不应撑满消息列").toBeLessThan(messageWidth!.width);

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
          meta: { cached: true },
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

    const modelsReady = waitForModelCatalog(page);
    await page.goto("/chat", { waitUntil: "commit" });
    await modelsReady;

    await expect(page.getByRole("button", { name: "打开会话列表" })).toBeVisible();
    await expect(page.getByRole("button", { name: "验证" })).toBeVisible();
    await expect(page.getByLabel("聊天模型")).toBeVisible();
    await expect(page.getByText("请选择当前在线模型后再发送消息")).toBeVisible();
    await selectChatModel(page, /GPT 5\.4 Chat Mobile Overflow Regression Fixture With Long Name/, longModelId);
    for (const name of ["首页", "AI 对话", "创建任务", "归档", "设置"]) {
      const box = await page.getByRole("link", { name }).boundingBox();
      expect(box, `${name} 顶部导航入口应可见`).not.toBeNull();
      expect(box!.width, `${name} 顶部导航触控宽度应不小于 44px`).toBeGreaterThanOrEqual(44);
      expect(box!.x, `${name} 顶部导航不应向左越界`).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width, `${name} 顶部导航不应向右越界`).toBeLessThanOrEqual(320);
    }
    await expectNoHorizontalOverflow(page);
  });

  test("RAG 设置子页在增量不可用时引导显式全量重建", async ({ page }) => {
    await mockCommonApiRoutes(page);
    let startRequests = 0;
    await page.route("**/api/settings/rag/plans", async (route) => {
      expect(route.request().postDataJSON()).toEqual({ mode: "incremental" });
      await route.fulfill({
        json: {
          plan_id: "",
          mode: "incremental",
          state: "full_rebuild_required",
          can_start: false,
          reason_code: "manifest_missing",
          reason: "现有索引缺少增量清单，请显式执行全量重建。",
          confirmation: { required: false },
        },
      });
    });
    await page.route("**/api/settings/rag/jobs", async (route) => {
      startRequests += 1;
      await route.fulfill({ status: 500, json: { detail: "不应创建作业" } });
    });
    await page.goto("/settings/rag/", { waitUntil: "commit" });
    await expect(page.getByText("小说 RAG 数据库")).toBeVisible();
    await expect(page.getByText(/数据库可用|尚未构建/)).toBeVisible();
    await page.getByTestId("rag-incremental-sync").click();
    await expect(page.getByText("现有索引缺少增量清单，请显式执行全量重建。")).toBeVisible();
    expect(startRequests).toBe(0);
  });

  test("设置子页仅在确认全量重建后创建后台作业并保存模型协议", async ({ page }) => {
    await mockCommonApiRoutes(page);
    let rebuildRequests = 0;
    let protocolRequests = 0;
    await page.route("**/api/settings/rag/plans", async (route) => {
      expect(route.request().postDataJSON()).toEqual({ mode: "full" });
      await route.fulfill({
        json: {
          plan_id: "rag_plan_fixture",
          mode: "full",
          state: "ready",
          can_start: true,
          summary: { scanned_sources: 2, embedded_documents: 3 },
          confirmation: { required: true, token: "confirm_fixture" },
        },
      });
    });
    await page.route("**/api/settings/rag/jobs/rag_job_fixture", async (route) => {
      await route.fulfill({
        json: {
          job_id: "rag_job_fixture",
          mode: "full",
          status: "succeeded",
          phase: "completed",
          phase_label: "同步完成",
          progress: 100,
          result: {
            success: true,
            message: "同步完成 fixture",
            scanned_files: 2,
            indexed_documents: 3,
            sync_mode: "full",
            embedded_documents: 3,
            reused_documents: 0,
            output_dir: "/tmp/rag",
            duration_ms: 12,
            sources: ["fixture"],
            warnings: [],
            finished_at: "2026-06-24T00:00:00.000Z",
          },
        },
      });
    });
    await page.route("**/api/settings/rag/jobs", async (route) => {
      rebuildRequests += 1;
      expect(route.request().postDataJSON()).toMatchObject({
        plan_id: "rag_plan_fixture",
        mode: "full",
        confirmation_token: "confirm_fixture",
      });
      await route.fulfill({
        status: 202,
        json: {
          job_id: "rag_job_fixture",
          mode: "full",
          status: "queued",
          phase: "queued",
          phase_label: "等待后台工作线程启动",
          progress: 0,
          poll_after_ms: 1,
        },
      });
    });
    await page.route("**/api/settings/protocols/gpt-5.4", async (route) => {
      protocolRequests += 1;
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      expect(payload.protocol).toBe("anthropic");
      await route.fulfill({ json: { model_id: "gpt-5.4", protocol: "anthropic" } });
    });

    await page.goto("/settings/rag/", { waitUntil: "commit" });
    await expect(page.getByText(/数据库可用|尚未构建/)).toBeVisible();
    await page.getByTestId("rag-full-rebuild").click();
    await expect(page.getByRole("dialog", { name: "确认全量重建 RAG 索引？" })).toBeVisible();
    expect(rebuildRequests).toBe(0);
    await page.getByRole("button", { name: "确认全量重建" }).click();
    await expect.poll(() => rebuildRequests, { message: "确认后应请求后台作业 API" }).toBe(1);
    await expect(page.getByText("同步完成 fixture")).toBeVisible();

    await page.goto("/settings/models/", { waitUntil: "commit" });
    await page.getByRole("combobox", { name: "协议", exact: true }).click();
    await page.getByRole("option", { name: "Anthropic" }).click();
    await expect.poll(() => protocolRequests, { message: "协议选择应请求保存接口" }).toBe(1);
    await expect(page.getByText("已保存：gpt-5.4 → anthropic")).toBeVisible();
  });

  test("RAG 设置子页全量作业创建失败时保留确认弹窗以便重试", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/settings/rag/plans", async (route) => {
      await route.fulfill({
        json: {
          plan_id: "rag_plan_retry_fixture",
          mode: "full",
          state: "ready",
          can_start: true,
          confirmation: { required: true, token: "confirm_retry_fixture" },
        },
      });
    });
    await page.route("**/api/settings/rag/jobs", async (route) => {
      await route.fulfill({ status: 409, json: { detail: "已有 RAG 同步任务正在运行，请等待其完成。" } });
    });

    await page.goto("/settings/rag/", { waitUntil: "commit" });
    await expect(page.getByText(/数据库可用|尚未构建/)).toBeVisible();
    await page.getByTestId("rag-full-rebuild").click();
    const dialog = page.getByRole("dialog", { name: "确认全量重建 RAG 索引？" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "确认全量重建" }).click();
    await expect(page.getByText("已有 RAG 同步任务正在运行，请等待其完成。")).toBeVisible();
    await expect(dialog).toBeVisible();
  });
});
