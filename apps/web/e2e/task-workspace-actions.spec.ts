import { expect, test } from "@playwright/test";
import { makeArchiveDetail, makeWorkspace, mockCommonApiRoutes, mockTaskWorkspace } from "./helpers/fixtures";

async function openWorkspace(page: import("@playwright/test").Page, status: string, taskId: string) {
  await mockCommonApiRoutes(page);
  const workspace = makeWorkspace(status, { task_id: taskId });
  await mockTaskWorkspace(page, workspace);
  await page.goto(`/p/${taskId}/`, { waitUntil: "commit" });
  return workspace;
}

test.describe("任务工作台动作分支", () => {
  test("created 分支点击开始执行会调用 run API", async ({ page }) => {
    const taskId = "task_action_created_fixture";
    await openWorkspace(page, "created", taskId);
    let runRequests = 0;
    await page.route(`**/api/tasks/${taskId}/run`, async (route) => {
      runRequests += 1;
      await route.fulfill({ json: { id: taskId, task_id: taskId, status: "planning" } });
    });

    const startButton = page.getByRole("button", { name: /开始/ });
    await expect(startButton).toBeEnabled();
    await startButton.click();
    await expect.poll(() => runRequests, { message: "开始执行应请求 run API" }).toBe(1);
  });

  test("ready_for_batch 分支点击继续创作会调用 continue API", async ({ page }) => {
    const taskId = "task_action_continue_fixture";
    await openWorkspace(page, "ready_for_batch", taskId);
    let continueRequests = 0;
    await page.route(`**/api/tasks/${taskId}/continue`, async (route) => {
      continueRequests += 1;
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      expect(payload.requested_chapter_count, "继续创作应带章节数量").toBeGreaterThan(0);
      expect(String(payload.continue_request_id || ""), "继续创作应带幂等请求 ID").not.toBe("");
      await route.fulfill({ json: { id: taskId, task_id: taskId, status: "drafting" } });
    });

    const continueButton = page.getByRole("button", { name: "继续创作" });
    await expect(continueButton).toBeEnabled();
    await continueButton.click();
    await expect.poll(() => continueRequests, { message: "继续创作应请求 continue API" }).toBe(1);
  });

  test("运行中分支点击取消任务会调用 cancel API", async ({ page }) => {
    const taskId = "task_action_cancel_fixture";
    await openWorkspace(page, "planning", taskId);
    let cancelRequests = 0;
    await page.route(`**/api/tasks/${taskId}/cancel`, async (route) => {
      cancelRequests += 1;
      await route.fulfill({ json: { id: taskId, task_id: taskId, status: "cancelled" } });
    });

    await page.getByRole("button", { name: /取消/ }).click();
    // WorkspaceActionBar 使用 MUI Dialog 确认
    await expect(page.getByRole("heading", { name: "取消任务" })).toBeVisible();
    await page.getByRole("button", { name: "确认取消" }).click();
    await expect.poll(() => cancelRequests, { message: "取消任务应请求 cancel API" }).toBe(1);
  });

  test("待审核与完成分支跳转到对应页面", async ({ page }) => {
    await openWorkspace(page, "waiting_outline_review", "task_action_review_fixture");
    await page.getByRole("link", { name: "进入审核" }).click();
    await expect(page).toHaveURL(/\/p\/task_action_review_fixture\/\?view=review/);

    await openWorkspace(page, "completed", "task_action_result_fixture");
    await page.getByRole("link", { name: "查看结果" }).click();
    await expect(page).toHaveURL(/\/p\/task_action_result_fixture\/\?view=result/);
  });

  test("完成分支确认归档会调用 archive API 并进入归档视图", async ({ page }) => {
    const taskId = "task_action_archive_fixture";
    const workspace = await openWorkspace(page, "completed", taskId);
    let archiveRequests = 0;

    await page.route(`**/api/tasks/${taskId}/archive`, async (route) => {
      archiveRequests += 1;
      expect(route.request().method()).toBe("POST");
      workspace.meta.storage_state = "archive";
      await route.fulfill({
        json: {
          id: taskId,
          task_id: taskId,
          status: "completed",
          storage_state: "archive",
        },
      });
    });
    await page.route(`**/api/archive/${taskId}`, async (route) => {
      const detail = makeArchiveDetail();
      await route.fulfill({
        json: {
          ...detail,
          meta: {
            ...detail.meta,
            id: taskId,
            task_id: taskId,
            title: "工作台归档测试任务",
          },
        },
      });
    });

    await page.getByRole("button", { name: "确认归档" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "归档任务" })).toBeVisible();
    await dialog.getByRole("button", { name: "确认归档" }).click();

    await expect.poll(() => archiveRequests, { message: "工作台确认归档应请求 archive API" }).toBe(1);
    await expect(page).toHaveURL(new RegExp(`/p/${taskId}/\\?view=archive`));
    await expect(page.getByRole("heading", { name: "归档详情" })).toBeVisible();
  });

  test("失败分支点击删除任务会调用 delete API", async ({ page }) => {
    const taskId = "task_action_delete_fixture";
    await openWorkspace(page, "failed", taskId);
    let deleteRequests = 0;
    await page.route(`**/api/tasks/${taskId}`, async (route) => {
      if (route.request().method() === "DELETE") {
        deleteRequests += 1;
        await route.fulfill({ json: { id: taskId, task_id: taskId, status: "deleted" } });
        return;
      }
      await route.fallback();
    });

    await page.getByRole("button", { name: /删除/ }).click();
    // WorkspaceActionBar 使用 MUI Dialog 确认
    await expect(page.getByRole("heading", { name: "删除任务" })).toBeVisible();
    await page.getByRole("button", { name: "确认删除" }).click();
    await expect.poll(() => deleteRequests, { message: "删除任务应请求 delete API" }).toBe(1);
  });
});
