import { expect, test } from "@playwright/test";
import { makeWorkspace, mockCommonApiRoutes, mockTaskWorkspace } from "./helpers/fixtures";

test.describe("阶段 2A 路由迁移", () => {
  test("静态导出占位项目 ID 显示地址无效且不请求工作台", async ({ page }) => {
    let workspaceRequests = 0;
    await page.route("**/api/tasks/*/workspace", async (route) => {
      workspaceRequests += 1;
      await route.fulfill({ status: 500, json: { detail: "占位 ID 不应请求工作台" } });
    });

    await page.goto("/p/__placeholder__/", { waitUntil: "commit" });

    await expect(page.getByRole("heading", { name: "项目地址无效", exact: true })).toBeVisible();
    expect(workspaceRequests).toBe(0);
  });

  test("工作台返回 404 时显示项目不存在而非读取失败", async ({ page }) => {
    const taskId = "task_route_missing_fixture";
    await page.route(`**/api/tasks/${taskId}/workspace`, async (route) => {
      await route.fulfill({
        status: 404,
        headers: { "X-Request-ID": "req-route-missing" },
        json: { detail: "任务不存在" },
      });
    });

    await page.goto(`/p/${taskId}/`, { waitUntil: "commit" });

    await expect(page.getByRole("heading", { name: "项目不存在或已删除", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "读取项目失败", exact: true })).toHaveCount(0);
  });

  test("新建作品规范路由可打开创建页", async ({ page }) => {
    await mockCommonApiRoutes(page);

    await page.goto("/new/", { waitUntil: "commit" });

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

    await page.goto("/new/", { waitUntil: "commit" });
    await page.getByRole("combobox", { name: "任务创作模型", exact: true }).click();
    await page.getByRole("option", { name: /GPT 5.4/ }).click();
    await page.getByRole("textbox", { name: "创意提示词", exact: true }).fill("写一个路由迁移测试故事。");
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
