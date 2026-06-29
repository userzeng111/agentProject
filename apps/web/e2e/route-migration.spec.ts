import { expect, test } from "@playwright/test";
import { makeWorkspace, mockCommonApiRoutes, mockTaskWorkspace } from "./helpers/fixtures";

test.describe("阶段 2A 路由迁移", () => {
  test("新建作品规范路由可打开创建页", async ({ page }) => {
    await mockCommonApiRoutes(page);

    await page.goto("/new", { waitUntil: "commit" });

    await expect(page).toHaveURL(/\/new\/?$/);
    await expect(page.getByRole("heading", { name: "创建小说任务" })).toBeVisible();
  });

  test("创建成功后进入项目工作台规范路由", async ({ page }) => {
    const taskId = "task_route_created_fixture";
    await mockCommonApiRoutes(page);
    await mockTaskWorkspace(page, makeWorkspace("created", { task_id: taskId }));
    await page.route("**/api/tasks", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({ json: { id: taskId, task_id: taskId, status: "created" } });
        return;
      }
      await route.fallback();
    });

    await page.goto("/new", { waitUntil: "commit" });
    await page.getByRole("combobox", { name: /^创作模型$/ }).click();
    await page.getByRole("option", { name: /GPT 5.4/ }).click();
    await page.getByLabel("创意提示词").fill("写一个路由迁移测试故事。");
    await page.getByRole("button", { name: "创建并进入任务页" }).click();

    await expect(page).toHaveURL(new RegExp(`/p/${taskId}/?$`));
    await expect(page.getByText(`自动化测试-created`, { exact: false }).first()).toBeVisible();
  });

  test("旧创建页入口跳转到新建作品规范路由并保留重试参数", async ({ page }) => {
    await mockCommonApiRoutes(page);

    await page.goto("/create?retry_from=task_retry_fixture", { waitUntil: "commit" });

    await expect(page).toHaveURL(/\/new\/?\?retry_from=task_retry_fixture$/);
    await expect(page.getByRole("heading", { name: "创建小说任务" })).toBeVisible();
  });

  test("旧工作台入口跳转到项目工作台规范路由", async ({ page }) => {
    const taskId = "task_route_workspace_fixture";
    await mockCommonApiRoutes(page);
    await mockTaskWorkspace(page, makeWorkspace("created", { task_id: taskId }));

    await page.goto(`/tasks?id=${taskId}`, { waitUntil: "commit" });

    await expect(page).toHaveURL(new RegExp(`/p/${taskId}/?$`));
    await expect(page.getByText(`自动化测试-created`, { exact: false }).first()).toBeVisible();
  });
});
