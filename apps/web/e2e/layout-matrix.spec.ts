import { expect, test } from "@playwright/test";
import { mockCommonApiRoutes } from "./helpers/fixtures";

const VIEWPORTS = [
  { width: 320, height: 740, name: "320x740" },
  { width: 390, height: 844, name: "390x844" },
  { width: 768, height: 1024, name: "768x1024" },
  { width: 1280, height: 800, name: "1280x800" },
];

test.describe("布局矩阵 — 所有页面在各视口下无横向滚动", () => {
  for (const vp of VIEWPORTS) {
    test(`首页 ${vp.name}`, async ({ page }) => {
      await page.setViewportSize(vp);
      await mockCommonApiRoutes(page);
      await page.goto("/", { waitUntil: "commit" });
      await expect(page.getByTestId("app-header")).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      expect(overflow, `${vp.name} 首页无横向滚动`).toBe(false);
    });

    test(`创建页 ${vp.name}`, async ({ page }) => {
      await page.setViewportSize(vp);
      await mockCommonApiRoutes(page);
      await page.goto("/new/", { waitUntil: "commit" });
      await expect(page.getByRole("heading", { name: /创建小说任务/ })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      expect(overflow, `${vp.name} 创建页无横向滚动`).toBe(false);
    });

    test(`聊天页 ${vp.name}`, async ({ page }) => {
      await page.setViewportSize(vp);
      await mockCommonApiRoutes(page);
      await page.goto("/chat/", { waitUntil: "commit" });
      await page.waitForLoadState("networkidle");
      await expect(page).toHaveURL(/\/chat\/?$/);
      await page.waitForTimeout(500);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
      expect(overflow, `${vp.name} 聊天页无横向滚动`).toBe(false);
    });

    test(`设置页 ${vp.name}`, async ({ page }) => {
      await page.setViewportSize(vp);
      await mockCommonApiRoutes(page);
      await page.goto("/settings/", { waitUntil: "commit" });
      await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      expect(overflow, `${vp.name} 设置页无横向滚动`).toBe(false);
    });

    test(`归档页 ${vp.name}`, async ({ page }) => {
      await page.setViewportSize(vp);
      await mockCommonApiRoutes(page);
      await page.goto("/archive/", { waitUntil: "commit" });
      await expect(page.getByText("归档").first()).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      expect(overflow, `${vp.name} 归档页无横向滚动`).toBe(false);
    });
  }
});
