import { expect, test, type Locator, type Page } from "@playwright/test";
import { makeWorkspace, mockCommonApiRoutes, mockTaskWorkspace } from "./helpers/fixtures";

async function expectLeftSideNavigation(page: Page, navigation: Locator, content: Locator) {
  await expect(navigation).toBeVisible();
  await expect(content).toBeVisible();

  const [navigationBox, contentBox] = await Promise.all([
    navigation.boundingBox(),
    content.boundingBox(),
  ]);
  expect(navigationBox).not.toBeNull();
  expect(contentBox).not.toBeNull();
  expect(navigationBox!.x + navigationBox!.width).toBeLessThanOrEqual(contentBox!.x);
}

test.describe("中等桌面宽度的工作台侧栏", () => {
  test("项目追踪在左侧呈现，中央标题不重复导航说明", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 900 });
    await mockCommonApiRoutes(page);
    await mockTaskWorkspace(page, makeWorkspace("created", { task_id: "task_side_navigation" }));

    await page.goto("/p/task_side_navigation/", { waitUntil: "commit" });
    await expectLeftSideNavigation(
      page,
      page.getByTestId("stage-nav"),
      page.getByTestId("project-shell-content"),
    );
    await expect(page.getByText("小说任务跟踪", { exact: true })).toHaveCount(0);
  });

  test("设置导航在左侧呈现，不再与窄屏快捷入口重复", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 900 });
    await mockCommonApiRoutes(page);

    await page.goto("/settings/", { waitUntil: "commit" });
    await expectLeftSideNavigation(
      page,
      page.getByTestId("settings-side-navigation"),
      page.getByTestId("settings-overview-workbench-content"),
    );
    await expect(page.getByTestId("settings-mobile-navigation")).not.toBeVisible();
  });
});
