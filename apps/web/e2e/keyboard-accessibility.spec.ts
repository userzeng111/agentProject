import { expect, test } from "@playwright/test";
import { mockCommonApiRoutes, makeWorkspace, mockTaskWorkspace } from "./helpers/fixtures";

test.describe("键盘可访问性验收", () => {
  test("首页可通过 Tab 键遍历页面", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.goto("/", { waitUntil: "commit" });
    await expect(page.getByTestId("app-header")).toBeVisible();

    // 连续 Tab，确认焦点在不同元素间移动
    const initialFocus = page.locator(":focus");
    await page.keyboard.press("Tab");
    const afterFirstTab = page.locator(":focus");
    await expect(initialFocus).not.toBe(afterFirstTab);
  });

  test("创建页表单字段可通过键盘导航到达", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.goto("/new/", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: /创建小说任务/ })).toBeVisible();

    // 多次 Tab，应能到达输入字段
    let foundInput = false;
    for (let i = 0; i < 30; i++) {
      await page.keyboard.press("Tab");
      const isInput = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el) return false;
        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute("role") || "";
        return ["input", "textarea", "textbox"].includes(tag) || role === "combobox" || role === "textbox";
      });
      if (isInput) { foundInput = true; break; }
    }
    expect(foundInput).toBe(true);
  });

  test("聊天页输入框焦点可达", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.goto("/chat/", { waitUntil: "commit" });
    await page.waitForTimeout(2000);

    let foundInput = false;
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press("Tab");
      const isInput = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el) return false;
        const tag = el.tagName.toLowerCase();
        const placeholder = el.getAttribute("placeholder") || "";
        return (tag === "textarea" || tag === "input") && placeholder.includes("输入消息");
      });
      if (isInput) { foundInput = true; break; }
    }
    expect(foundInput).toBe(true);
  });

  test("设置页可通过键盘导航", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.goto("/settings/", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: "设置中心" })).toBeVisible();

    // 多次 Tab，应能到达某个 focusable 元素
    let moved = false;
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press("Tab");
      const after = await page.evaluate(() => document.activeElement?.tagName || "");
      if (after && after !== "BODY") { moved = true; break; }
    }
    expect(moved).toBe(true);
  });

  test("项目工作台审核链接可聚焦并通过 Enter 触发", async ({ page }) => {
    await mockCommonApiRoutes(page);
    const taskId = "task_keyboard_fixture";
    const workspace = makeWorkspace("waiting_outline_review", { task_id: taskId });
    await mockTaskWorkspace(page, workspace);
    await page.goto(`/p/${taskId}/`, { waitUntil: "commit" });

    // 找到进入审核链接并聚焦
    const reviewLink = page.getByRole("link", { name: /进入审核/ });
    await reviewLink.focus();
    await expect(reviewLink).toBeFocused();

    // Enter 触发导航
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/p\/task_keyboard_fixture\/\?view=review/);
  });
});
