import { expect, test } from "@playwright/test";
import { apiPath, deleteTaskIfAllowed } from "./helpers/api";
import { mockCommonApiRoutes } from "./helpers/fixtures";

test.describe("真实浏览器任务生命周期", () => {
  test("创建页提交含素材任务后可进入工作台并删除清理", async ({ page, request }) => {
    let taskId = "";

    try {
      await mockCommonApiRoutes(page);
      await page.goto("/new/", { waitUntil: "commit" });
      await expect(page.getByRole("heading", { name: /创建小说任务/ })).toBeVisible();

      await expect(page.getByRole("combobox", { name: "任务创作模型", exact: true })).toBeVisible();
      await page.getByRole("combobox", { name: "任务创作模型", exact: true }).click();
      await page.getByRole("option", { name: /GPT 5\.4/ }).click();
      await page.getByLabel("目标总章节数").fill("4");
      await page.getByRole("textbox", { name: "创意提示词", exact: true }).fill("Playwright 真实浏览器链路测试：写一个海港灯塔里的短篇悬疑。");
      await page.getByLabel("题材").fill("悬疑");
      await page.getByLabel("风格").fill("冷静克制");
      await page.getByLabel("标题倾向").fill("灯塔证词");
      await page.locator('input[type="file"]').setInputFiles({
        name: "playwright-real-reference.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("这是 Playwright 真实浏览器链路测试素材，用于验证上传后任务状态可读。", "utf-8"),
      });
      await expect(page.getByRole("button", { name: /已选择：playwright-real-reference\.txt/ })).toBeVisible();

      await expect(page.getByRole("button", { name: "创建并进入任务页" })).toBeEnabled();
      await page.getByRole("button", { name: "创建并进入任务页" }).click();
      await expect(page).toHaveURL(/\/p\/task_/, { timeout: 30_000 });
      const currentUrl = new URL(page.url());
      taskId = currentUrl.pathname.split("/").filter(Boolean).at(1) ?? "";
      expect(taskId, "创建页跳转后应携带任务 id").toMatch(/^task_/);

      await expect
        .poll(async () => (await request.get(apiPath(`/api/tasks/${taskId}`))).status(), {
          message: "创建页跳转后，后端任务应可读取",
        })
        .toBe(200);
      await expect(page.getByText("灯塔证词", { exact: false }).first()).toBeVisible();
      await expect(page.getByText(/素材已入库|任务准备/).first()).toBeVisible();
      await expect(page.getByText("playwright-real-reference.txt", { exact: false }).first()).toBeVisible();
      await expect(page.getByRole("tab", { name: /实时日志/ })).toBeVisible();
      await expect(page.getByRole("tab", { name: /调试/ })).toBeVisible();

      page.once("dialog", async (dialog) => {
        expect(dialog.message()).toContain("确认删除");
        await dialog.accept();
      });
      await page.getByRole("button", { name: /删除/ }).click();
      await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });

      await expect
        .poll(async () => (await request.get(apiPath(`/api/tasks/${taskId}`))).status(), {
          message: "通过工作台删除后，后端任务应不存在",
        })
        .toBe(404);
      taskId = "";
    } finally {
      await deleteTaskIfAllowed(request, taskId);
    }
  });
});
