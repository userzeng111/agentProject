import { expect, test } from "@playwright/test";
import { expectNoSensitiveText } from "./helpers/assertions";
import { makeWorkspace, mockCommonApiRoutes, mockTaskWorkspace } from "./helpers/fixtures";

const statusCases = [
  { status: "created", label: "待启动" },
  { status: "sources_ingested", label: "素材已入库" },
  { status: "planning", label: "规划中" },
  { status: "drafting", label: "正文生成中" },
  { status: "assembling", label: "结果整理中" },
  { status: "ready_for_batch", label: "可继续创作" },
  { status: "waiting_outline_review", label: "待大纲审核" },
  { status: "waiting_chapter_review", label: "待章节审核" },
  { status: "waiting_verification_review", label: "待验证审核" },
  { status: "waiting_manual_action", label: "待人工处理" },
  { status: "failed", label: "失败" },
  { status: "cancelled", label: "已取消" },
  { status: "completed", label: "已完成" },
];

test.describe("任务工作台状态分支", () => {
  for (const item of statusCases) {
    test(`${item.status} 分支渲染关键动作`, async ({ page }) => {
      await mockCommonApiRoutes(page);
      const workspace = makeWorkspace(item.status, {
        task_id: `task_${item.status}_fixture`,
        ...(item.status === "completed"
          ? {
              recent_events: [
                {
                  event_id: "event_completed",
                  event_type: "task.completed",
                  stage: "completed",
                  message: "任务已完成",
                  created_at: new Date("2026-06-24T00:00:00.000Z").toISOString(),
                },
              ],
            }
          : {}),
      });
      await mockTaskWorkspace(page, workspace);
      await page.goto(`/p/${workspace.meta.task_id}`, { waitUntil: "commit" });

      await expect(page.getByTestId("project-shell")).toBeVisible();
      await expect(page.getByTestId("stage-nav")).toBeVisible();
      await expect(page.locator('[data-stage-state="current"]')).toBeVisible();
      await expect(page.getByText(item.label, { exact: true }).first()).toBeVisible();
      const debugTab = page.getByRole("tab", { name: /调试/ });
      await expect(debugTab).toBeVisible();
      await expect(debugTab).toBeEnabled();
      await debugTab.click({ timeout: 15000 });
      await expect(page.getByText("诊断结论", { exact: false })).toBeVisible();
      await expectNoSensitiveText(page);
    });
  }

  test("移动端工作台不产生横向滚动", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockCommonApiRoutes(page);
    const workspace = makeWorkspace("ready_for_batch", {
      task_id: "task_mobile_workspace_shell_fixture_with_a_very_long_unbroken_identifier_20260630",
      meta: {
        title: "",
      },
    });
    await mockTaskWorkspace(page, workspace);

    await page.goto(`/p/${workspace.meta.task_id}`, { waitUntil: "commit" });

    await expect(page.getByTestId("project-shell")).toBeVisible();
    await expect(page.getByTestId("stage-nav")).toBeVisible();
    await expect(page.getByRole("button", { name: "继续创作" })).toBeVisible();
    const viewportWidth = await page.evaluate(() => document.documentElement.clientWidth);
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(viewportWidth);
  });

  test("暗色移动端工作流图谱不使用旧浅色节点", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      window.localStorage.setItem("theme-mode", "dark");
    });
    await mockCommonApiRoutes(page);
    const workspace = makeWorkspace("ready_for_batch", {
      task_id: "task_dark_workflow_graph_mobile_fixture",
    });
    await mockTaskWorkspace(page, workspace);

    await page.goto(`/p/${workspace.meta.task_id}`, { waitUntil: "commit" });

    const graphCard = page.getByTestId("workflow-overview-card");
    await expect(graphCard).toBeVisible();
    await expect(graphCard.locator(".react-flow").first()).toBeVisible();

    await expect
      .poll(async () => {
        const nodeBackground = await graphCard
          .locator(".react-flow__node")
          .first()
          .locator("> div")
          .evaluate((node) => window.getComputedStyle(node).backgroundColor);
        const channels = nodeBackground.match(/\d+(\.\d+)?/g)?.slice(0, 3).map(Number) ?? [];
        return channels.length === 3 && !channels.every((value) => value >= 230);
      })
      .toBe(true);

    const viewportWidth = await page.evaluate(() => document.documentElement.clientWidth);
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(viewportWidth);
  });

  test("移动端章节进度可以打开正文并通过可访问名称关闭", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockCommonApiRoutes(page);
    const taskId = "task_chapter_progress_mobile_fixture";
    const chapterTitle =
      "第一章-极长极长极长极长极长极长极长极长极长极长极长极长的无空格章节标题用于移动端断词检查";
    const workspace = makeWorkspace("waiting_chapter_review", {
      task_id: taskId,
      novel_progress: {
        target_chapter_count: 8,
        planned_chapter_count: 8,
        completed_chapter_count: 1,
        next_chapter_number: 2,
        remaining_chapter_count: 7,
        default_batch_size: 3,
      },
      recent_events: [
        {
          event_id: "event_chapter_saved_mobile",
          event_type: "chapter.saved",
          stage: "drafting",
          unit_id: "chapter-01",
          message: "第一章已保存。",
          created_at: new Date("2026-06-24T00:00:00.000Z").toISOString(),
          payload: {
            chapter_number: 1,
            chapter_title: chapterTitle,
            chapter_summary: "第一章摘要",
          },
        },
      ],
    });
    await mockTaskWorkspace(page, workspace, [
      {
        number: 1,
        title: chapterTitle,
        summary: "第一章摘要",
        content: "第一章正文\n\n这里是 Playwright 验证用的章节正文。",
      },
    ]);

    await page.goto(`/p/${taskId}`, { waitUntil: "commit" });
    await page.getByRole("tab", { name: /章节进度/ }).click();

    await expect(page.getByTestId("chapter-progress-panel")).toBeVisible();
    await page.getByRole("button", { name: /查看第 1 章正文/ }).click();
    await expect(page.getByRole("dialog", { name: /第 1 章/ })).toBeVisible();
    await expect(page.getByText("第一章正文")).toBeVisible();
    await page.getByRole("button", { name: "关闭章节正文" }).click();
    await expect(page.getByRole("dialog")).toBeHidden();

    const viewportWidth = await page.evaluate(() => document.documentElement.clientWidth);
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(viewportWidth);
  });

  test("调试页状态不一致分支优先显示", async ({ page }) => {
    await mockCommonApiRoutes(page);
    const workspace = makeWorkspace("completed", {
      task_id: "task_state_conflict_fixture",
      supervisor_plan: {
        planner_version: "fixture",
        dependencies: [],
        subtasks: [
          {
            id: "still_running",
            kind: "agent",
            title: "仍在运行的子任务",
            status: "running",
          },
        ],
      },
    });
    await mockTaskWorkspace(page, workspace);

    await page.goto(`/p/${workspace.meta.task_id}`, { waitUntil: "commit" });
    await page.getByRole("tab", { name: /调试/ }).click();
    await expect(page.getByRole("heading", { name: "状态不一致" })).toBeVisible();
  });
});
