import { expect, test, type Page } from "@playwright/test";
import { mockCommonApiRoutes } from "./helpers/fixtures";

async function openCreateWorkbench(page: Page) {
  await mockCommonApiRoutes(page);
  await page.goto("/new/", { waitUntil: "commit" });
  await expect(page.getByTestId("task-create-workbench")).toBeVisible();
  await expect(page.getByRole("heading", { name: "创建小说任务", exact: true })).toBeVisible();
}

test.describe("创作工作台", () => {
  test("以分阶段工作台呈现创建任务，并保留步骤语义", async ({ page }) => {
    await openCreateWorkbench(page);

    const storyStep = page.getByTestId("create-step-story");
    const referenceStep = page.getByTestId("create-step-reference");
    const executionStep = page.getByTestId("create-step-execution");
    const readiness = page.getByTestId("create-readiness");

    await expect(storyStep).toHaveAttribute("aria-current", "step");
    await expect(referenceStep).not.toHaveAttribute("aria-current", "step");
    await expect(executionStep).not.toHaveAttribute("aria-current", "step");
    await expect(readiness).toBeVisible();
    await expect(page.getByRole("button", { name: "下一步" })).toBeVisible();
  });

  test("在阶段间切换不会丢失创意提示词", async ({ page }) => {
    await openCreateWorkbench(page);
    await expect(page.getByRole("button", { name: "刷新模型", exact: true })).toBeEnabled();

    const storyStep = page.getByTestId("create-step-story");
    const referenceStep = page.getByTestId("create-step-reference");
    const prompt = page.getByRole("textbox", { name: "创意提示词", exact: true });
    const promptText = "潮湿海港的夜航记录员发现一页被篡改的航海日志。";

    await prompt.fill(promptText);
    await page.getByRole("button", { name: "下一步" }).click();
    await expect(referenceStep).toHaveAttribute("aria-current", "step");
    await expect(page.getByRole("button", { name: "上一步" })).toBeVisible();

    await storyStep.click();
    await expect(storyStep).toHaveAttribute("aria-current", "step");
    await expect(prompt).toHaveValue(promptText);

    await referenceStep.click();
    await expect(referenceStep).toHaveAttribute("aria-current", "step");
    await storyStep.click();
    await expect(prompt).toHaveValue(promptText);
  });

  test("RAG 未就绪时提供前往知识库同步的明确入口", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/settings/rag", async (route) => {
      await route.fulfill({
        json: {
          available: false,
          library_dir: "",
          faiss_index_path: "",
          sqlite_path: "",
          sources: [],
          last_result: null,
        },
      });
    });
    await page.goto("/new/", { waitUntil: "commit" });

    const syncCta = page.getByRole("link", { name: "前往知识库同步", exact: true });
    await expect(syncCta).toBeVisible();
    await expect(syncCta).toHaveAttribute("href", "/settings/rag/");
  });

  test("移动端无横向溢出，底部主操作始终可达", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openCreateWorkbench(page);

    const mobileAction = page.getByTestId("create-mobile-action");
    const primaryAction = mobileAction.getByRole("button", { name: "创建并进入任务页", exact: true });
    await expect(mobileAction).toBeVisible();
    await expect(primaryAction).toBeVisible();

    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);

    const actionBox = await primaryAction.boundingBox();
    expect(actionBox).not.toBeNull();
    expect(actionBox!.x).toBeGreaterThanOrEqual(0);
    expect(actionBox!.x + actionBox!.width).toBeLessThanOrEqual(391);
    expect(actionBox!.y).toBeGreaterThanOrEqual(0);
    expect(actionBox!.y + actionBox!.height).toBeLessThanOrEqual(845);
  });

  test("1440px 起仅保留右侧摘要操作，避免与底部操作重复", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openCreateWorkbench(page);

    await expect(page.getByTestId("create-desktop-summary")).toBeVisible();
    await expect(page.getByTestId("create-mobile-action")).not.toBeVisible();
    await expect(page.getByTestId("create-readiness")).not.toBeVisible();
  });

  test("重置表单须经二次确认，确认后清空已填内容", async ({ page }) => {
    await openCreateWorkbench(page);

    const prompt = page.getByRole("textbox", { name: "创意提示词", exact: true });
    await prompt.fill("用于验证重置确认的创意提示词。");
    await page.getByRole("button", { name: "重置表单", exact: true }).click();

    const confirmation = page.getByRole("dialog");
    await expect(confirmation).toBeVisible();
    await expect(confirmation).toContainText("重置");
    await confirmation.getByRole("button", { name: "确认重置", exact: true }).click();
    await expect(prompt).toHaveValue("");
  });
});
