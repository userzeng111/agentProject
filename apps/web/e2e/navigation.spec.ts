import { expect, test } from "@playwright/test";
import { apiPath, createDraftTask, deleteTaskIfAllowed, expectJsonOk } from "./helpers/api";

test.describe("真实后端页面导航", () => {
  test("主要页面可达并展示核心标题", async ({ page }) => {
    await page.goto("/", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: "小说工坊", level: 4 })).toBeVisible();

    await page.goto("/new", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: /创建小说任务/ })).toBeVisible();

    await page.goto("/archive", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: /归档/ })).toBeVisible();

    await page.goto("/settings", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: /设置/ })).toBeVisible();

    await page.goto("/chat", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: "AI 对话" })).toBeVisible();
  });

  test("创建的轻量任务可进入工作台", async ({ page, request }) => {
    let taskId = "";
    try {
      const task = await createDraftTask(request, "Playwright 页面导航");
      taskId = task.id;
      await page.goto(`/p/${taskId}`, { waitUntil: "commit" });
      await expect(page).toHaveURL(new RegExp(`/p/${taskId}/?$`));
      await expect
        .poll(async () => (await request.get(apiPath(`/api/tasks/${taskId}/workspace`))).status(), {
          message: "进入工作台后，后端 workspace 应可读取",
        })
        .toBe(200);
      await expect(page.getByText("Playwright 页面导航", { exact: false }).first()).toBeVisible();
      await expect(page.getByRole("tab", { name: /实时日志/ })).toBeVisible();
      await expect(page.getByRole("tab", { name: /调试/ })).toBeVisible();
    } finally {
      await deleteTaskIfAllowed(request, taskId);
    }
  });

  test("归档详情在存在归档数据时可打开", async ({ page, request }) => {
    const archive = await expectJsonOk<{ items?: Array<{ task_id: string; title?: string }> }>(
      await request.get(apiPath("/api/archive")),
      "归档列表",
    );
    test.skip(!archive.items?.length, "当前没有归档任务可验证详情页");
    const archiveItem = archive.items![0];
    const archiveId = archiveItem.task_id;
    await page.goto(`/archive/detail/?id=${archiveId}`, { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: "归档详情" })).toBeVisible();
    await expect(page.getByText(archiveItem.title ?? archiveId, { exact: false }).first()).toBeVisible();
    await expect(page.getByRole("tab", { name: /概览|总览/ })).toBeVisible();
  });
});
