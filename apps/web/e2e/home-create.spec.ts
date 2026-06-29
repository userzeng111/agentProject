import { expect, test } from "@playwright/test";
import { makeTask, makeWorkspace, mockCommonApiRoutes, mockTaskWorkspace } from "./helpers/fixtures";

function modelCatalog(defaultModel = "gpt-5.4") {
  return {
    data: [
      {
        id: "gpt-5.4",
        display_name: "GPT 5.4",
        provider: "gateway",
        metadata: { source: "gateway:list_models" },
        capabilities: {
          features: ["novel"],
          context_window: { max_input_tokens: 8000, max_output_tokens: 4000 },
        },
      },
      {
        id: "gpt-5.5",
        display_name: "GPT 5.5",
        provider: "gateway",
        metadata: { source: "gateway:list_models" },
        capabilities: {
          features: ["novel"],
          context_window: { max_input_tokens: 16000, max_output_tokens: 8000 },
        },
      },
    ],
    meta: { default_model: defaultModel, cached: true },
  };
}

test.describe("首页 Dashboard 与创建任务", () => {
  test("首页展示任务分组并支持失败任务重试跳转", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/tasks/task_failed_fixture", async (route) => {
      await route.fulfill({ json: makeTask("failed", "task_failed_fixture") });
    });
    await page.goto("/", { waitUntil: "commit" });

    for (const tab of ["待处理 (1)", "运行中 (1)", "失败 (1)", "已完成 (1)"]) {
      await expect(page.getByRole("tab", { name: tab })).toBeVisible();
    }

    await page.getByRole("tab", { name: "失败 (1)" }).click();
    await expect(page.getByRole("heading", { name: "自动化测试-failed" })).toBeVisible();
    await page.getByRole("link", { name: /重新创建/ }).click();
    await expect(page).toHaveURL(/\/new\/?\?retry_from=task_failed_fixture/);
  });

  test("首页支持删除失败任务和切换默认模型", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/models**", async (route) => {
      await route.fulfill({ json: modelCatalog() });
    });
    let deleteRequests = 0;
    let defaultModelRequests = 0;
    await page.route("**/api/tasks/task_failed_fixture", async (route) => {
      if (route.request().method() === "DELETE") {
        deleteRequests += 1;
        await route.fulfill({ json: { id: "task_failed_fixture", status: "deleted" } });
        return;
      }
      await route.fallback();
    });
    await page.route("**/api/settings/default-model", async (route) => {
      defaultModelRequests += 1;
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      expect(payload.model_id).toBe("gpt-5.5");
      await route.fulfill({ json: { default_model: "gpt-5.5", supported_models: ["gpt-5.4", "gpt-5.5"] } });
    });

    await page.goto("/", { waitUntil: "commit" });
    await expect(page.getByText("小说工坊").first()).toBeVisible();
    await page.getByRole("combobox").click();
    await page.getByRole("option", { name: /GPT 5.5/ }).click();
    await expect.poll(() => defaultModelRequests, { message: "切换默认模型应请求设置接口" }).toBe(1);

    await page.getByRole("tab", { name: "失败 (1)" }).click();
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("确认删除");
      await dialog.accept();
    });
    await page.getByRole("button", { name: /删除/ }).click();
    await expect.poll(() => deleteRequests, { message: "删除失败任务应请求 delete API" }).toBe(1);
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

    await page.goto("/new", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: "创建小说任务" })).toBeVisible();
    await page.getByRole("combobox", { name: /^创作模型$/ }).click();
    await page.getByRole("option", { name: /GPT 5.4/ }).click();
    await expect(page.getByRole("combobox", { name: /^创作模型/ })).toContainText("GPT 5.4");
    await page.getByLabel("创意提示词").fill("写一个潮湿海港里的悬疑故事。");
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

    await page.goto("/new", { waitUntil: "commit" });
    await page.getByRole("combobox", { name: /^创作模型$/ }).click();
    await page.getByRole("option", { name: /GPT 5.4/ }).click();
    await expect(page.getByRole("combobox", { name: /^创作模型/ })).toContainText("GPT 5.4");
    await page.getByLabel("创意提示词").fill("失败分支测试。");
    const submit = page.getByRole("button", { name: "创建并进入任务页" });
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(page.getByText("创建失败 fixture")).toBeVisible();
  });
});
