import { expect, test, type Page } from "@playwright/test";
import {
  makeArchiveDetail,
  makeArchiveList,
  makeWorkspace,
  mockCommonApiRoutes,
  mockTaskWorkspace,
} from "./helpers/fixtures";

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

async function mockProjectPage(page: Page, workspace: ReturnType<typeof makeWorkspace>) {
  await mockCommonApiRoutes(page);
  await mockTaskWorkspace(page, workspace);
}

test.describe("审核、结果、归档页面", () => {
  test("审核页缺少 id 时显示错误兜底", async ({ page }) => {
    await page.goto("/review", { waitUntil: "commit" });
    await page.waitForFunction(() => window.location.pathname === "/");
  });

  test("审核页默认展示追踪，按需打开审核决策抽屉", async ({ page }, testInfo) => {
    const workspace = makeWorkspace("waiting_outline_review", { task_id: "task_review_fixture" });
    await mockProjectPage(page, workspace);
    await page.route("**/api/tasks/task_review_fixture/review", async (route) => {
      await route.fulfill({ json: makeReview("outline") });
    });
    await page.goto("/p/task_review_fixture/?view=review", { waitUntil: "commit" });
    await expect(page.getByTestId("review-workbench")).toBeVisible();
    const stageNav = page.getByTestId("review-context-pane");
    if (testInfo.project.name === "chromium") {
      await expect(stageNav).toBeVisible();
    } else {
      await expect(stageNav).toBeHidden();
    }
    await expect(stageNav.locator('[data-stage-state="current"]')).toContainText("审核");
    const reviewMain = page.getByTestId("review-main");
    const reviewTrace = page.getByTestId("review-agent-trace");
    const reviewTrigger = page.getByTestId("review-decision-trigger");
    await expect(page.getByTestId("review-split-layout")).toBeVisible();
    await expect(reviewMain).toBeVisible();
    await expect(reviewTrace).toBeVisible();
    await expect(reviewTrigger).toBeVisible();
    await expect(page.getByTestId("review-decision-drawer")).toHaveCount(0);
    await expect(page.getByTestId("review-content-scroll")).toHaveCSS("overflow-y", "auto");
    await expect(page.getByRole("heading", { name: "大纲审核", exact: true })).toBeVisible();
    if (testInfo.project.name === "chromium") {
      const contentScroll = page.getByTestId("review-content-scroll");
      const before = await reviewTrigger.boundingBox();
      const dimensions = await contentScroll.evaluate((element) => ({
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
      }));
      expect(dimensions.scrollHeight).toBeGreaterThan(dimensions.clientHeight);
      await contentScroll.evaluate((element) => {
        element.scrollTop = element.scrollHeight;
      });
      const after = await reviewTrigger.boundingBox();
      expect(before).not.toBeNull();
      expect(after).not.toBeNull();
      expect(Math.abs(after!.y - before!.y)).toBeLessThanOrEqual(1);
    }
    await reviewTrigger.click();
    const reviewDrawer = page.getByTestId("review-decision-drawer");
    await expect(reviewDrawer).toBeVisible();
    await expect(reviewDrawer.getByText("审核决策", { exact: true })).toBeVisible();
    await expect(reviewDrawer.getByLabel("审核意见")).toBeVisible();
    await expect(reviewDrawer.getByRole("button", { name: /通过/ })).toBeVisible();
    await reviewDrawer.getByRole("button", { name: "关闭审核决策" }).click();
    await expect(reviewDrawer).toHaveCount(0);
    await expect(reviewTrace).toBeVisible();
  });

  test("章节计划审核展示已确认和待审核的大纲", async ({ page }) => {
    const workspace = makeWorkspace("waiting_outline_review", { task_id: "task_review_outline_batches" });
    await mockProjectPage(page, workspace);
    const review = makeReview("outline");
    await page.route("**/api/tasks/task_review_outline_batches/review", async (route) => {
      await route.fulfill({
        json: {
          ...review,
          meta: { ...review.meta, task_id: "task_review_outline_batches" },
          outline_markdown: "# 批次大纲\n\n- [已确认] 第1章 雾起：发现线索\n- [已确认] 第2章 旧案：锁定嫌疑人",
          story_plan: {
            ...review.story_plan,
            planned_chapter_count: 3,
            chapter_plan: [
              { number: 1, title: "雾起", goal: "发现线索" },
              { number: 2, title: "旧案", goal: "锁定嫌疑人" },
              { number: 3, title: "追踪", goal: "确认真相" },
            ],
          },
          outline_batch: {
            phase: "chapter_batches",
            batch_index: 2,
            batch_size: 2,
            completed_count: 2,
            total_count: 3,
            current_batch_plans: [{ number: 3, title: "追踪", goal: "确认真相" }],
          },
        },
      });
    });

    await page.goto("/p/task_review_outline_batches/?view=review", { waitUntil: "commit" });
    const confirmed = page.getByTestId("confirmed-outline-batches");
    await expect(confirmed).toBeVisible();
    await expect(confirmed).toContainText("已确认 2 章");
    await expect(confirmed).toContainText("第1章 雾起");
    await expect(confirmed).toContainText("第2章 旧案");
    await expect(page.getByText("待审核批次（第3-3章）")).toBeVisible();
    await expect(page.getByText("第3章 追踪")).toBeVisible();
  });

  test("章节审核在中等桌面宽度保留左侧追踪，材料区不被顶部导航挤压", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const workspace = makeWorkspace("waiting_chapter_review", { task_id: "task_review_side_layout" });
    await mockProjectPage(page, workspace);
    const review = makeReview("chapter");
    await page.route("**/api/tasks/task_review_side_layout/review", async (route) => {
      await route.fulfill({
        json: {
          ...review,
          meta: { ...review.meta, task_id: "task_review_side_layout" },
          chapter_pair: [
            {
              number: 1,
              title: "雾中发现",
              summary: "退休刑侦林远在浓雾晨间巡逻时，于海岸发现一具无名尸体，其身上的神秘物品与二十年前悬案高度相似。",
              content: "章节正文占位。",
            },
          ],
        },
      });
    });

    await page.goto("/p/task_review_side_layout/?view=review", { waitUntil: "commit" });
    const navigation = page.getByTestId("review-context-pane");
    const content = page.getByTestId("review-content-scroll");
    await expect(navigation).toBeVisible();
    await expect(content).toBeVisible();

    const [navigationBox, contentBox] = await Promise.all([navigation.boundingBox(), content.boundingBox()]);
    expect(navigationBox).not.toBeNull();
    expect(contentBox).not.toBeNull();
    expect(navigationBox!.x + navigationBox!.width).toBeLessThanOrEqual(contentBox!.x);
    expect(contentBox!.height).toBeGreaterThan(600);

    const chapterHeader = page.getByTestId("chapter-review-header-1");
    const chapterTitle = chapterHeader.getByText("第 1 章：雾中发现", { exact: true });
    await expect(chapterTitle).toBeVisible();
    const titleBox = await chapterTitle.boundingBox();
    expect(titleBox).not.toBeNull();
    expect(titleBox!.width).toBeGreaterThan(180);
    expect(titleBox!.height).toBeLessThan(60);
  });

  test("审核决策抽屉只滚动内容区，决策操作保持固定", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 620 });
    const workspace = makeWorkspace("waiting_outline_review", { task_id: "task_review_scroll_fixture" });
    await mockProjectPage(page, workspace);
    await page.route("**/api/tasks/task_review_scroll_fixture/review", async (route) => {
      await route.fulfill({
        json: {
          ...makeReview("outline"),
          review_history: Array.from({ length: 16 }, (_, index) => ({
            version: `v${index + 1}`,
            action: "approved",
            comment: `第 ${index + 1} 次审核历史，保留用于验证抽屉滚动区域。`,
            created_at: "2026-07-20T08:00:00Z",
          })),
        },
      });
    });

    await page.goto("/p/task_review_scroll_fixture/?view=review", { waitUntil: "commit" });
    await page.getByTestId("review-decision-trigger").click();
    const reviewDrawer = page.getByTestId("review-decision-drawer");
    const decisionScroll = page.getByTestId("review-decision-scroll");
    const approveButton = reviewDrawer.getByRole("button", { name: /通过/ });
    await expect(decisionScroll).toHaveCSS("overflow-y", "auto");
    const before = await approveButton.boundingBox();
    const scrollState = await decisionScroll.evaluate((element) => {
      const scrollHeight = element.scrollHeight;
      const clientHeight = element.clientHeight;
      element.scrollTop = scrollHeight;
      return { scrollHeight, clientHeight, scrollTop: element.scrollTop };
    });
    expect(scrollState.scrollHeight).toBeGreaterThan(scrollState.clientHeight);
    expect(scrollState.scrollTop).toBeGreaterThan(0);
    const after = await approveButton.boundingBox();
    expect(before).not.toBeNull();
    expect(after).not.toBeNull();
    expect(Math.abs(after!.y - before!.y)).toBeLessThanOrEqual(1);
  });

  test("审核 Agent 行保持单一按钮语义并支持键盘展开", async ({ page }) => {
    const workspace = makeWorkspace("waiting_outline_review", { task_id: "task_review_agent_fixture" });
    await mockProjectPage(page, workspace);
    await page.route("**/api/tasks/task_review_agent_fixture/review", async (route) => {
      await route.fulfill({
        json: {
          ...makeReview("outline"),
          meta: {
            task_id: "task_review_agent_fixture",
            title: "审核 Agent 追踪测试",
            status: "waiting_outline_review",
            summary: "审核摘要",
            creative_model_id: "gpt-5.4",
            review_model_id: "gpt-5.4",
          },
          auto_review_trace: [
            {
              agent_id: "structure_agent",
              agent_name: "结构审稿 Agent",
              execution_kind: "subagent",
              status: "completed",
              score: 92,
              reasoning: "结构审稿详情",
              issues: [],
              warnings: [],
            },
          ],
        },
      });
    });

    await page.goto("/p/task_review_agent_fixture/?view=review", { waitUntil: "commit" });
    await expect(page.getByTestId("review-agent-trace")).toBeVisible();
    const agentRow = page.getByRole("button", { name: /结构审稿 Agent/ });
    await expect(agentRow).toHaveAttribute("aria-expanded", "false");
    await expect(agentRow.locator("button")).toHaveCount(0);

    await agentRow.focus();
    await page.keyboard.press("Enter");
    await expect(agentRow).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator("#agent-content-0")).toContainText("结构审稿详情");
  });

  test("审核页章节与验证分支展示对应审核材料", async ({ page }) => {
    const chapterWorkspace = makeWorkspace("waiting_chapter_review", { task_id: "task_review_chapter_fixture" });
    await mockProjectPage(page, chapterWorkspace);
    await page.route("**/api/tasks/task_review_chapter_fixture/review", async (route) => {
      await route.fulfill({ json: makeReview("chapter") });
    });
    await page.goto("/p/task_review_chapter_fixture/?view=review", { waitUntil: "commit" });
    await expect(page.getByTestId("review-workbench")).toBeVisible();
    await expect(page.getByTestId("review-context-pane").locator('[data-stage-state="current"]')).toContainText("审核");
    await expect(page.getByText("章节摘要")).toBeVisible();
    await page.getByTestId("review-decision-trigger").click();
    let reviewDrawer = page.getByTestId("review-decision-drawer");
    await expect(reviewDrawer.getByText("审核决策", { exact: true })).toBeVisible();
    await expect(reviewDrawer.getByLabel("审核意见")).toBeVisible();

    const verificationWorkspace = makeWorkspace("waiting_verification_review", { task_id: "task_review_verification_fixture" });
    await mockProjectPage(page, verificationWorkspace);
    await page.route("**/api/tasks/task_review_verification_fixture/review", async (route) => {
      await route.fulfill({ json: makeReview("verification") });
    });
    await page.goto("/p/task_review_verification_fixture/?view=review", { waitUntil: "commit" });
    await expect(page.getByTestId("review-workbench")).toBeVisible();
    await expect(page.getByTestId("review-context-pane").locator('[data-stage-state="current"]')).toContainText("验证");
    await expect(page.getByText("验证摘要")).toBeVisible();
    await expect(page.getByRole("heading", { name: "发现的问题" })).toBeVisible();
    await expect(page.getByText("warning")).toBeVisible();
    await page.getByTestId("review-decision-trigger").click();
    reviewDrawer = page.getByTestId("review-decision-drawer");
    await expect(reviewDrawer.getByText("审核决策", { exact: true })).toBeVisible();
    await expect(reviewDrawer.getByLabel("审核意见")).toBeVisible();
  });

  test("审核页移动端不产生横向滚动且以全屏抽屉承载决策", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const workspace = makeWorkspace("waiting_outline_review", { task_id: "task_review_fixture" });
    await mockProjectPage(page, workspace);
    await page.route("**/api/tasks/task_review_fixture/review", async (route) => {
      await route.fulfill({ json: makeReview("outline") });
    });

    await page.goto("/p/task_review_fixture/?view=review", { waitUntil: "commit" });
    await expect(page.getByTestId("review-split-layout")).toBeVisible();
    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);
    await expect(page.getByTestId("review-agent-trace")).toBeVisible();
    await page.getByTestId("review-decision-trigger").click();
    const reviewDrawer = page.getByTestId("review-decision-drawer");
    await expect(reviewDrawer.getByLabel("审核意见")).toBeVisible();
    await expect(reviewDrawer.getByRole("button", { name: /通过/ })).toBeVisible();
    const drawerBox = await reviewDrawer.boundingBox();
    expect(drawerBox).not.toBeNull();
    expect(Math.abs(drawerBox!.width - 390)).toBeLessThanOrEqual(2);
    expect(Math.abs(drawerBox!.height - 844)).toBeLessThanOrEqual(2);
  });

  test("结果页缺少 id 时显示错误兜底", async ({ page }) => {
    await page.goto("/result", { waitUntil: "commit" });
    await page.waitForFunction(() => window.location.pathname === "/");
  });

  test("结果页展示摘要、按章阅读器和章节索引，不重复展示全文", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      window.localStorage.setItem("theme-mode", "dark");
    });
    const codeFence = ["", "```ts", "const chapterSignal = 'dark-code';", "```"].join("\n");
    const workspace = makeWorkspace("completed", { task_id: "task_result_fixture" });
    await mockProjectPage(page, workspace);
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
          result_markdown: `# 结果正文\n\n正文占位。${codeFence}`,
          result_md_ref: "",
          chapter_index: [
            { number: 1, title: "第一章", summary: "章节摘要", content: `第一章正文占位${codeFence}` },
            { number: 2, title: "第二章", summary: "章节摘要", content: `第二章正文占位${codeFence}` },
          ],
          artifact_index: [],
          history_index: [],
        },
      });
    });
    await page.goto("/p/task_result_fixture/?view=result", { waitUntil: "commit" });
    await expect(page.getByTestId("project-shell")).toBeVisible();
    await expect(page.getByTestId("stage-nav").locator('[data-stage-state="current"]')).toContainText("结果");
    await expect(page.getByRole("heading", { name: "生成结果" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "结果摘要" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "正文内容", exact: true })).toHaveCount(0);
    const reader = page.getByTestId("novel-reader");
    await expect(reader).toBeVisible();
    await expect(reader.getByTestId("novel-reader-content")).toContainText("第一章正文占位");
    const readerCodeBlock = reader.getByTestId("novel-reader-content").locator("pre").last();
    await expect(readerCodeBlock).toBeVisible();
    await expect
      .poll(async () =>
        readerCodeBlock.evaluate((element) => {
          const color = getComputedStyle(element).backgroundColor;
          const match = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([.\d]+))?\)/i);
          if (!match) {
            return false;
          }
          const [, r, g, b, a] = match;
          const alpha = a === undefined ? 1 : Number(a);
          const luminance = 0.2126 * Number(r) + 0.7152 * Number(g) + 0.0722 * Number(b);
          return alpha > 0.1 && luminance < 96;
        }),
      )
      .toBe(true);
    await expect
      .poll(async () => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth))
      .toBe(false);
    await reader.getByRole("button", { name: "下一章" }).first().click();
    await expect(reader.getByTestId("novel-reader-content")).toContainText("第二章正文占位");
    await expect(page.getByRole("button", { name: "复制全文" })).toBeVisible();
    await expect(page.getByRole("button", { name: "导出 MD" })).toBeVisible();
    await page.getByRole("button", { name: "复制全文" }).click();
    await expect(page.getByText(/已复制到剪贴板|复制失败/)).toBeVisible();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出 MD" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("结果测试任务.md");
    await expect(page.getByRole("heading", { name: "章节索引" })).toBeVisible();
  });

  test("结果页确认归档后跳转到归档详情", async ({ page }) => {
    const workspace = makeWorkspace("completed", {
      task_id: "task_result_archive_fixture",
    });
    await mockProjectPage(page, workspace);
    let archiveRequests = 0;
    await page.route("**/api/tasks/task_result_archive_fixture/result", async (route) => {
      await route.fulfill({
        json: {
          meta: {
            task_id: "task_result_archive_fixture",
            title: "待确认归档任务",
            status: "completed",
            summary: "结果摘要",
            storage_state: "runs",
          },
          result_summary: "结果摘要",
          result_markdown: "# 待确认归档任务\n\n正文占位。",
          result_md_ref: "",
          chapter_index: [{ number: 1, title: "第一章", summary: "章节摘要", content: "第一章正文占位" }],
          artifact_index: [],
          history_index: [],
        },
      });
    });
    await page.route("**/api/tasks/task_result_archive_fixture/archive", async (route) => {
      archiveRequests += 1;
      expect(route.request().method()).toBe("POST");
      workspace.meta.storage_state = "archive";
      await route.fulfill({
        json: {
          task_id: "task_result_archive_fixture",
          id: "task_result_archive_fixture",
          status: "completed",
          storage_state: "archive",
        },
      });
    });
    await page.route("**/api/archive/task_result_archive_fixture", async (route) => {
      const detail = makeArchiveDetail();
      await route.fulfill({
        json: {
          ...detail,
          meta: {
            ...detail.meta,
            task_id: "task_result_archive_fixture",
            id: "task_result_archive_fixture",
            title: "待确认归档任务",
          },
        },
      });
    });

    await page.goto("/p/task_result_archive_fixture/?view=result", { waitUntil: "commit" });
    await expect(page.getByRole("button", { name: "确认归档" })).toBeVisible();
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("确认已检查生成结果并归档");
      await dialog.accept();
    });
    await page.getByRole("button", { name: "确认归档" }).click();

    await expect.poll(() => archiveRequests, { message: "确认归档应请求归档接口" }).toBe(1);
    await expect(page).toHaveURL(/\/p\/task_result_archive_fixture\/\?view=archive/);
    await expect(page.getByRole("heading", { name: "归档详情" })).toBeVisible();
  });

  test("归档列表和详情 Tab 可渲染", async ({ page }) => {
    const workspace = makeWorkspace("completed", {
      task_id: "task_archive_fixture",
      meta: { storage_state: "archive" },
    });
    await mockProjectPage(page, workspace);
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
      "/p/task_archive_fixture/?view=archive",
    );
    await page.goto("/p/task_archive_fixture/?view=archive", { waitUntil: "commit" });
    await expect(page.getByTestId("project-shell")).toBeVisible();
    await expect(page.getByRole("heading", { name: "归档详情" })).toBeVisible();
    await expect(page.getByRole("tab", { name: /大纲|阅读|原始/ }).first()).toBeVisible();

    await page.goto("/p/task_archive_fixture/?view=archive&tab=read", { waitUntil: "commit" });
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

  test("历史归档缺少章节计划时仍可显示大纲信息", async ({ page }) => {
    const workspace = makeWorkspace("completed", {
      task_id: "task_archive_legacy_outline",
      meta: { storage_state: "archive" },
    });
    await mockProjectPage(page, workspace);
    await page.route("**/api/archive/task_archive_legacy_outline", async (route) => {
      const detail = makeArchiveDetail();
      await route.fulfill({
        json: {
          ...detail,
          meta: { ...detail.meta, task_id: "task_archive_legacy_outline" },
          story_plan: { ...detail.story_plan, chapter_plan: undefined },
        },
      });
    });

    await page.goto("/p/task_archive_legacy_outline/?view=archive&tab=outline", { waitUntil: "commit" });
    await expect(page.getByRole("heading", { name: "故事梗概" })).toBeVisible();
    await expect(page.getByText("当前归档缺少章节计划明细。")).toBeVisible();
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
