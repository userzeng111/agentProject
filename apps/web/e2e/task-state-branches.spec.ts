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
      await page.goto(`/tasks/?id=${workspace.meta.task_id}`, { waitUntil: "commit" });

      await expect(page.getByText(item.label, { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("tab", { name: /调试/ })).toBeVisible();
      await page.getByRole("tab", { name: /调试/ }).click();
      await expect(page.getByText("诊断结论", { exact: false })).toBeVisible();
      await expectNoSensitiveText(page);
    });
  }

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

    await page.goto(`/tasks/?id=${workspace.meta.task_id}`, { waitUntil: "commit" });
    await page.getByRole("tab", { name: /调试/ }).click();
    await expect(page.getByRole("heading", { name: "状态不一致" })).toBeVisible();
  });
});
