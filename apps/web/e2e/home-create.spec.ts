import { expect, test } from "@playwright/test";
import { LONG_CREATED_TASK_ID, makeTask, makeWorkspace, mockCommonApiRoutes, mockTaskWorkspace } from "./helpers/fixtures";

function parseCssColor(color: string) {
  const channels = color.match(/\d+(\.\d+)?/g)?.map(Number) ?? [];
  const [red = 255, green = 255, blue = 255, alpha = 1] = channels;
  return {
    alpha,
    luminance: 0.2126 * red + 0.7152 * green + 0.0722 * blue,
  };
}

test.describe("首页 Dashboard 与创建任务", () => {
  test("首页以作品库项目卡片展示任务并在移动端无横向溢出", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      window.localStorage.setItem("theme-mode", "dark");
    });
    await mockCommonApiRoutes(page);
    await page.goto("/", { waitUntil: "commit" });

    const appHeader = page.getByTestId("app-header");
    await expect(appHeader).toBeVisible();
    await expect
      .poll(async () => {
        const headerColor = parseCssColor(
          await appHeader.evaluate((element) => window.getComputedStyle(element).backgroundColor),
        );
        return headerColor.alpha > 0.1 && headerColor.luminance < 128;
      })
      .toBe(true);

    await expect(page.getByRole("heading", { name: "作品库" })).toBeVisible();

    const card = page.getByTestId("project-card").filter({ hasText: "自动化测试-created" });
    await expect(card).toBeVisible();
    await expect(card.getByText("Playwright fixture 摘要")).toBeVisible();
    await expect(card.getByText("待启动")).toBeVisible();
    await expect(card.getByText("created", { exact: true })).toBeVisible();
    await expect(card.getByText("全新原创 · 短篇")).toBeVisible();
    await expect(card.getByText(`ID ${LONG_CREATED_TASK_ID}`)).toBeVisible();
    await expect(card.getByRole("link", { name: "进入项目" })).toHaveAttribute(
      "href",
      new RegExp(`/p/${LONG_CREATED_TASK_ID}/?$`),
    );

    const hasHorizontalOverflow = await page.evaluate(() => (
      document.documentElement.scrollWidth > document.documentElement.clientWidth
    ));
    expect(hasHorizontalOverflow).toBe(false);
    const cardHasHorizontalOverflow = await card.evaluate((element) => element.scrollWidth > element.clientWidth + 1);
    expect(cardHasHorizontalOverflow).toBe(false);
  });

  test("首页展示任务分组并支持失败任务重试跳转", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/tasks/task_failed_fixture", async (route) => {
      await route.fulfill({ json: makeTask("failed", "task_failed_fixture") });
    });
    await page.goto("/", { waitUntil: "commit" });

    for (const tab of ["待处理 (1)", "运行中 (1)", "失败 (1)", "已完成 (1)"]) {
      await expect(page.getByRole("tab", { name: tab })).toBeVisible();
    }

    await page.getByRole("tab", { name: "已完成 (1)" }).click();
    const completedCard = page.getByTestId("project-card").filter({ hasText: "自动化测试-completed" });
    await expect(completedCard.getByRole("link", { name: "进入项目" })).toHaveAttribute(
      "href",
      "/p/task_completed_fixture/?view=result",
    );

    await page.getByRole("tab", { name: "失败 (1)" }).click();
    await expect(page.getByRole("heading", { name: "自动化测试-failed" })).toBeVisible();
    await page.getByRole("link", { name: /重新创建/ }).click();
    await expect(page).toHaveURL(/\/new\/?\?retry_from=task_failed_fixture/);
  });

  test("首页支持删除失败任务且不暴露全局默认模型切换", async ({ page }) => {
    await mockCommonApiRoutes(page);
    let deleteRequests = 0;
    let defaultModelRequests = 0;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/settings/default-model") {
        defaultModelRequests += 1;
      }
    });
    await page.route("**/api/tasks/task_failed_fixture", async (route) => {
      if (route.request().method() === "DELETE") {
        deleteRequests += 1;
        await route.fulfill({ json: { id: "task_failed_fixture", status: "deleted" } });
        return;
      }
      await route.fallback();
    });

    await page.goto("/", { waitUntil: "commit" });
    await expect(page.getByText("小说工坊").first()).toBeVisible();
    await expect(page.getByRole("combobox", { name: /默认模型/ })).toHaveCount(0);
    await expect(page.getByText("全局默认模型")).toHaveCount(0);

    await page.getByRole("tab", { name: "失败 (1)" }).click();
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("确认删除");
      await dialog.accept();
    });
    await page.getByRole("button", { name: /删除/ }).click();
    await expect.poll(() => deleteRequests, { message: "删除失败任务应请求 delete API" }).toBe(1);
    expect(defaultModelRequests, "首页不应请求已废弃的全局默认模型设置接口").toBe(0);
  });

  test("创建页提交成功后进入任务工作台", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await mockTaskWorkspace(page, makeWorkspace("created", { task_id: "task_created_form_fixture" }));
    let createRequests = 0;
    await page.route("**/api/tasks", async (route) => {
      if (route.request().method() === "POST") {
        createRequests += 1;
        const payload = route.request().postDataJSON() as Record<string, unknown>;
        expect(payload.prompt).toContain("海港");
        expect(payload.genre).toBe("悬疑");
        expect(payload.style).toBe("克制");
        await route.fulfill({ json: { id: "task_created_form_fixture", task_id: "task_created_form_fixture", status: "created" } });
        return;
      }
      await route.fallback();
    });

    await page.goto("/new/", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: "创建小说任务" })).toBeVisible();
    const modelSelect = page.getByRole("combobox", { name: "任务创作模型", exact: true });
    await modelSelect.click();
    await page.getByRole("option", { name: /GPT 5.4/ }).click();
    await expect(page.getByTestId("model-select")).toHaveValue("gpt-5.4");
    await page.getByRole("textbox", { name: "创意提示词", exact: true }).fill("写一个潮湿海港里的悬疑故事。");
    await page.getByLabel("题材").fill("悬疑");
    await page.getByLabel("风格").fill("克制");
    const submit = page.getByRole("button", { name: "创建并进入任务页" });
    await expect(submit).toBeEnabled();
    await submit.click();

    await expect.poll(() => createRequests, { message: "创建页应提交任务" }).toBe(1);
    await expect(page).toHaveURL(/\/p\/task_created_form_fixture\/?$/);
  });

  test("创建页提交失败时展示错误提示", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/tasks", async (route) => {
      await route.fulfill({
        status: 400,
        json: { detail: "创建失败 fixture" },
      });
    });

    await page.goto("/new/", { waitUntil: "commit" });
    const modelSelect = page.getByRole("combobox", { name: "任务创作模型", exact: true });
    await modelSelect.click();
    await page.getByRole("option", { name: /GPT 5.4/ }).click();
    await expect(page.getByTestId("model-select")).toHaveValue("gpt-5.4");
    await page.getByRole("textbox", { name: "创意提示词", exact: true }).fill("失败分支测试。");
    const submit = page.getByRole("button", { name: "创建并进入任务页" });
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(page.getByText("创建失败 fixture")).toBeVisible();
  });
});
