import { expect, test } from "@playwright/test";
import { makeArchiveDetail, makeArchiveList, mockCommonApiRoutes } from "./helpers/fixtures";

function makeReview(reviewType = "outline") {
  const normalizedReviewType =
    reviewType === "chapter" ? "chapter_pair_review" : reviewType === "verification" ? "verification_review" : "outline_review";
  return {
    meta: {
      task_id: "task_review_fixture",
      title: "审核测试任务",
      status:
        reviewType === "chapter"
          ? "waiting_chapter_review"
          : reviewType === "verification"
            ? "waiting_verification_review"
            : "waiting_outline_review",
      summary: "审核摘要",
      creative_model_id: "gpt-5.4",
      default_model_id: "gpt-5.4",
      review_model_id: "gpt-5.4",
    },
    review_type: normalizedReviewType,
    review_version: "v1",
    revision_count: 0,
    summary: "审核测试摘要",
    risk_flags: [],
    outline_markdown: "# 测试大纲\n\n大纲摘要",
    story_plan: {
      working_title: "测试大纲",
      logline: "大纲摘要",
      world_notes: ["测试世界观"],
      character_notes: ["测试角色"],
      planned_chapter_count: 1,
    },
    outline_batch: {
      phase: "master",
      batch_index: 0,
      batch_size: 20,
      completed_count: 0,
      total_count: 1,
      current_batch_plans: [],
    },
    chapter_pair: [{ number: 1, title: "第一章", summary: "章节摘要", content: "内容占位" }],
    verification_report: {
      overall_score: 90,
      summary: "验证摘要",
      issues: [{ severity: "warning", message: "测试问题" }],
    },
    auto_review_trace: [],
    review_history: [],
    allowed_actions: [],
    recovery_options: [],
    recommended_action: "",
  };
}

test.describe("审核、结果、归档页面", () => {
  test("审核页缺少 id 时显示错误兜底", async ({ page }) => {
    await page.goto("/review", { waitUntil: "commit" });
    await expect(page.getByText(/缺少任务 ID|读取审核信息失败/)).toBeVisible();
  });

  test("审核页大纲分支展示审核操作", async ({ page }, testInfo) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/tasks/task_review_fixture/review", async (route) => {
      await route.fulfill({ json: makeReview("outline") });
    });
    await page.goto("/review/?id=task_review_fixture", { waitUntil: "commit" });
    await expect(page.getByTestId("project-shell")).toBeVisible();
    const stageNav = page.getByTestId("stage-nav");
    await expect(stageNav).toBeVisible();
    await expect(stageNav.locator('[data-stage-state="current"]')).toContainText("审核");
    const reviewMain = page.getByTestId("review-main");
    const reviewAside = page.getByTestId("review-aside");
    await expect(page.getByTestId("review-split-layout")).toBeVisible();
    await expect(reviewMain).toBeVisible();
    await expect(reviewAside).toBeVisible();
    if (testInfo.project.name === "chromium") {
      const mainBox = await reviewMain.boundingBox();
      const asideBox = await reviewAside.boundingBox();
      expect(mainBox).not.toBeNull();
      expect(asideBox).not.toBeNull();
      expect(asideBox!.x).toBeGreaterThan(mainBox!.x + mainBox!.width * 0.5);
    }
    await expect(page.getByRole("heading", { name: "大纲审核", exact: true })).toBeVisible();
    await expect(reviewAside.getByRole("heading", { name: "审核操作" })).toBeVisible();
    await expect(reviewAside.getByLabel("审核意见")).toBeVisible();
  });

  test("审核页章节与验证分支展示对应审核材料", async ({ page }) => {
    await mockCommonApiRoutes(page);
    await page.route("**/api/tasks/task_review_chapter_fixture/review", async (route) => {
      await route.fulfill({ json: makeReview("chapter") });
    });
    await page.goto("/review/?id=task_review_chapter_fixture", { waitUntil: "commit" });
    await expect(page.getByTestId("project-shell")).toBeVisible();
    await expect(page.getByTestId("stage-nav").locator('[data-stage-state="current"]')).toContainText("审核");
    await expect(page.getByText("章节摘要")).toBeVisible();
    let reviewAside = page.getByTestId("review-aside");
    await expect(reviewAside.getByRole("heading", { name: "审核操作" })).toBeVisible();
    await expect(reviewAside.getByLabel("审核意见")).toBeVisible();

    await page.route("**/api/tasks/task_review_verification_fixture/review", async (route) => {
      await route.fulfill({ json: makeReview("verification") });
    });
    await page.goto("/review/?id=task_review_verification_fixture", { waitUntil: "commit" });
    await expect(page.getByTestId("project-shell")).toBeVisible();
    await expect(page.getByTestId("stage-nav").locator('[data-stage-state="current"]')).toContainText("验证");
    await expect(page.getByText("验证摘要")).toBeVisible();
    await expect(page.getByRole("heading", { name: "发现的问题" })).toBeVisible();
    await expect(page.getByText("warning")).toBeVisible();
    reviewAside = page.getByTestId("review-aside");
    await expect(reviewAside.getByRole("heading", { name: "审核操作" })).toBeVisible();
    await expect(reviewAside.getByLabel("审核意见")).toBeVisible();
  });

  test("审核页移动端不产生横向滚动且保留决策区", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockCommonApiRoutes(page);
    await page.route("**/api/tasks/task_review_fixture/review", async (route) => {
      await route.fulfill({ json: makeReview("outline") });
    });

    await page.goto("/review/?id=task_review_fixture", { waitUntil: "commit" });
    await expect(page.getByTestId("review-split-layout")).toBeVisible();
    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);
    const reviewAside = page.getByTestId("review-aside");
    await expect(reviewAside.getByLabel("审核意见")).toBeVisible();
    await expect(reviewAside.getByRole("button", { name: /通过/ })).toBeVisible();
  });

  test("结果页缺少 id 时显示错误兜底", async ({ page }) => {
    await page.goto("/result", { waitUntil: "commit" });
    await expect(page.getByText(/缺少任务 ID|读取结果失败/)).toBeVisible();
  });

  test("结果页展示摘要、正文区、按章阅读器和章节索引", async ({ page }) => {
    await page.route("**/api/tasks/task_result_fixture/result", async (route) => {
      await route.fulfill({
        json: {
          meta: {
            task_id: "task_result_fixture",
            title: "结果测试任务",
            status: "completed",
            summary: "结果摘要",
          },
          result_summary: "结果摘要",
          result_markdown: "# 结果正文\n\n正文占位。",
          result_md_ref: "",
          chapter_index: [
            { number: 1, title: "第一章", summary: "章节摘要", content: "第一章正文占位" },
            { number: 2, title: "第二章", summary: "章节摘要", content: "第二章正文占位" },
          ],
          artifact_index: [],
          history_index: [],
        },
      });
    });
    await page.goto("/result/?id=task_result_fixture", { waitUntil: "commit" });
    await expect(page.getByTestId("project-shell")).toBeVisible();
    await expect(page.getByTestId("stage-nav").locator('[data-stage-state="current"]')).toContainText("结果");
    await expect(page.getByRole("heading", { name: "生成结果" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "结果摘要" })).toBeVisible();
    const reader = page.getByTestId("novel-reader");
    await expect(reader).toBeVisible();
    await expect(reader.getByTestId("novel-reader-content")).toContainText("第一章正文占位");
    await reader.getByRole("button", { name: "下一章" }).first().click();
    await expect(reader.getByTestId("novel-reader-content")).toContainText("第二章正文占位");
    await expect(page.getByRole("button", { name: "复制全文" })).toBeVisible();
    await expect(page.getByRole("button", { name: "导出 MD" })).toBeVisible();
    await page.getByRole("button", { name: "复制全文" }).click();
    await expect(page.getByText(/已复制到剪贴板|复制失败/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "章节索引" })).toBeVisible();
  });

  test("归档列表和详情 Tab 可渲染", async ({ page }) => {
    await page.route("**/api/archive**", async (route) => {
      if (route.request().url().includes("/api/archive/task_archive_fixture")) {
        await route.fulfill({ json: makeArchiveDetail() });
        return;
      }
      await route.fulfill({ json: makeArchiveList() });
    });

    await page.goto("/archive", { waitUntil: "commit" });
    const archiveCard = page.getByTestId("archive-card");
    await expect(archiveCard).toBeVisible();
    await expect(archiveCard).toContainText("归档测试任务");
    await expect(archiveCard).toContainText(/章节[:：]?\s*2|2\s*章/);
    await expect(archiveCard).toContainText(/字数[:：]?\s*1,?200|1,?200\s*字/);
    await expect(archiveCard).toContainText("全新原创 · 短篇");
    await expect(archiveCard).toContainText("gpt-5.4-archive-model-with-a-very-long-unbroken-identifier-20260630");
    await expect(archiveCard.getByRole("link", { name: "查看归档详情" })).toHaveAttribute(
      "href",
      "/archive/detail/?id=task_archive_fixture",
    );
    await page.goto("/archive/detail/?id=task_archive_fixture", { waitUntil: "commit" });
    await expect(page.getByTestId("project-shell")).toBeVisible();
    await expect(page.getByRole("heading", { name: "归档详情" })).toBeVisible();
    await expect(page.getByRole("tab", { name: /大纲|阅读|原始/ }).first()).toBeVisible();

    await page.goto("/archive/detail/?id=task_archive_fixture&tab=read", { waitUntil: "commit" });
    const reader = page.getByTestId("novel-reader");
    await expect(reader).toBeVisible();
    await expect(reader.getByTestId("novel-reader-content")).toContainText("章节内容占位");
    await reader.getByRole("button", { name: "下一章" }).first().click();
    await expect(reader.getByRole("heading", { name: /第二章/ })).toBeVisible();

    await page.getByRole("tab", { name: "原始信息" }).click();
    await expect(page).toHaveURL(/tab=meta/);
    await expect(page.getByRole("button", { name: "复制全文" })).toBeVisible();
    await expect(page.getByRole("button", { name: "导出 MD" })).toBeVisible();
    await page.getByRole("button", { name: "复制全文" }).click();
    await expect(page.getByText(/已复制到剪贴板|复制失败/)).toBeVisible();
  });

  test("归档列表移动端不产生横向滚动", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.route("**/api/archive**", async (route) => {
      await route.fulfill({ json: makeArchiveList() });
    });

    await page.goto("/archive", { waitUntil: "commit" });
    await expect(page.getByTestId("archive-card")).toBeVisible();
    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);
  });

  test("归档列表空态可渲染", async ({ page }) => {
    await page.route("**/api/archive**", async (route) => {
      await route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 10 } });
    });

    await page.goto("/archive", { waitUntil: "commit" });
    await expect(page.getByText(/暂无归档|还没有/)).toBeVisible();
  });
});
