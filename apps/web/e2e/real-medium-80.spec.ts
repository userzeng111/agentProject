import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import { apiPath } from "./helpers/api";

/**
 * 此文件是真实模型慢测：只有显式设置 RUN_REAL_LLM_E2E=1 才会运行。
 * 所有会改变任务状态的操作均通过浏览器页面完成；接口调用只用于轮询状态和最终核验。
 */
const SHOULD_RUN_REAL_LLM = process.env.RUN_REAL_LLM_E2E === "1";
const REAL_MODEL_ID = process.env.REAL_LLM_MODEL_ID ?? "bailu-2.7-free";
const RESUME_TASK_ID = (process.env.REAL_LLM_E2E_TASK_ID ?? "").trim();
const REAL_RUN_TAG = (process.env.REAL_LLM_E2E_RUN_TAG ?? `real-e2e-${Date.now().toString(36)}`).trim();
const POLL_INTERVAL_MS = 10_000;
const DEFAULT_TIMEOUT_MS = 8 * 60 * 60 * 1_000;

const ACTIVE_STATUSES = new Set(["planning", "drafting", "assembling"]);
const REVIEW_STATUSES = new Set([
  "waiting_outline_review",
  "waiting_chapter_review",
  "waiting_verification_review",
]);
const TERMINAL_FAILURE_STATUSES = new Set(["failed", "cancelled"]);

type WorkspaceSnapshot = {
  meta: {
    status: string;
    current_stage?: string;
    current_unit?: string | null;
    error_message?: string | null;
    last_error_detail?: string;
  };
  novel_progress?: {
    completed_chapter_count?: number;
    planned_chapter_count?: number;
    remaining_chapter_count?: number;
    next_chapter_number?: number;
  };
  recent_events?: Array<{
    event_type?: string;
    stage?: string;
    message?: string;
    created_at?: string;
  }>;
};

type ReviewSnapshot = {
  review_type?: string;
  outline_batch?: {
    phase?: string;
    batch_index?: number;
    completed_count?: number;
    total_count?: number;
    current_batch_plans?: Array<{ number?: number }>;
  };
  chapter_pair?: Array<{ number?: number }>;
  batch_index?: number;
  completed_count?: number;
  total_chapters?: number;
  chapter_pair_revision_count?: number;
  verification_revision_count?: number;
};

type TaskSnapshot = {
  workspace: WorkspaceSnapshot;
  reviewSignature: string;
};

function resolveTimeoutMs() {
  const configured = Number(process.env.REAL_LLM_E2E_TIMEOUT_MS);
  return Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_TIMEOUT_MS;
}

async function readJson<T>(request: APIRequestContext, path: string, label: string): Promise<T> {
  const response = await request.get(apiPath(path), { timeout: 60_000 });
  if (!response.ok()) {
    throw new Error(`${label}失败，HTTP ${response.status()}：${(await response.text()).slice(0, 1_000)}`);
  }
  return response.json() as Promise<T>;
}

async function readWorkspace(request: APIRequestContext, taskId: string) {
  return readJson<WorkspaceSnapshot>(request, `/api/tasks/${taskId}/workspace`, "读取任务工作台");
}

async function readReview(request: APIRequestContext, taskId: string) {
  return readJson<ReviewSnapshot>(request, `/api/tasks/${taskId}/review`, "读取任务审核信息");
}

function reviewSignature(review: ReviewSnapshot) {
  const outline = review.outline_batch;
  return JSON.stringify({
    review_type: review.review_type,
    outline_phase: outline?.phase,
    outline_batch_index: outline?.batch_index,
    outline_completed_count: outline?.completed_count,
    outline_current_chapters: outline?.current_batch_plans?.map((item) => item.number),
    chapter_batch_index: review.batch_index,
    chapter_completed_count: review.completed_count,
    chapter_numbers: review.chapter_pair?.map((item) => item.number),
    chapter_revision_count: review.chapter_pair_revision_count,
    verification_revision_count: review.verification_revision_count,
  });
}

async function readTaskSnapshot(request: APIRequestContext, taskId: string): Promise<TaskSnapshot> {
  const workspace = await readWorkspace(request, taskId);
  if (!REVIEW_STATUSES.has(workspace.meta.status)) {
    return { workspace, reviewSignature: "" };
  }
  return { workspace, reviewSignature: reviewSignature(await readReview(request, taskId)) };
}

function describeWorkspace(workspace: WorkspaceSnapshot) {
  return JSON.stringify({
    status: workspace.meta.status,
    stage: workspace.meta.current_stage,
    unit: workspace.meta.current_unit,
    error: workspace.meta.error_message || workspace.meta.last_error_detail,
    novel_progress: workspace.novel_progress,
    latest_events: (workspace.recent_events ?? []).slice(-8),
  });
}

function throwIfTerminalFailure(workspace: WorkspaceSnapshot) {
  if (TERMINAL_FAILURE_STATUSES.has(workspace.meta.status)) {
    throw new Error(`真实 80 章任务异常停止：${describeWorkspace(workspace)}`);
  }
}

async function waitForProgressAfterAction(
  page: Page,
  request: APIRequestContext,
  taskId: string,
  before: TaskSnapshot,
  deadline: number,
) {
  while (Date.now() < deadline) {
    const current = await readTaskSnapshot(request, taskId);
    throwIfTerminalFailure(current.workspace);
    if (
      current.workspace.meta.status !== before.workspace.meta.status ||
      current.reviewSignature !== before.reviewSignature
    ) {
      return current;
    }
    await page.waitForTimeout(POLL_INTERVAL_MS);
  }
  throw new Error(`等待页面操作推进超时：${describeWorkspace(before.workspace)}`);
}

async function waitForActionableState(
  page: Page,
  request: APIRequestContext,
  taskId: string,
  deadline: number,
) {
  while (Date.now() < deadline) {
    const current = await readTaskSnapshot(request, taskId);
    throwIfTerminalFailure(current.workspace);
    if (!ACTIVE_STATUSES.has(current.workspace.meta.status)) {
      return current;
    }
    await page.waitForTimeout(POLL_INTERVAL_MS);
  }
  throw new Error("等待后台生成进入下一人工节点超时。");
}

async function openWorkspace(page: Page, taskId: string) {
  await page.goto(`/p/${taskId}/`, { waitUntil: "commit" });
  await expect(page.getByTestId("project-shell")).toBeVisible({ timeout: 60_000 });
}

async function openReview(page: Page, taskId: string) {
  await page.goto(`/p/${taskId}/?view=review`, { waitUntil: "commit" });
  await expect(page.getByTestId("review-workbench")).toBeVisible({ timeout: 60_000 });
}

async function createMediumNovelFromUi(page: Page, testInfo: TestInfo) {
  await page.goto("/new/", { waitUntil: "commit" });
  await expect(page.getByRole("heading", { name: "创建小说任务" })).toBeVisible({ timeout: 60_000 });

  const novelSizeSelect = page.getByRole("combobox", { name: /^篇幅规模/ });
  await novelSizeSelect.click();
  // MUI Select 的菜单通过 portal 挂载，直接定位 option 在不同浏览器下不稳定。
  // 默认值为短篇，键盘下移一项即为中篇，仍是标准浏览器交互。
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(novelSizeSelect).toContainText("中篇");
  await page.getByLabel("目标总章节数").fill("80");

  const modelSelect = page.getByRole("combobox", { name: /^任务创作模型/ });
  await expect(modelSelect).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "刷新模型", exact: true }).click();
  await modelSelect.click();
  await page.keyboard.type(REAL_MODEL_ID);
  await page.keyboard.press("Enter");
  await expect(modelSelect).toContainText(REAL_MODEL_ID);

  await page.getByRole("textbox", { name: "创意提示词", exact: true }).fill(
    "写一部 80 章的都市悬疑成长小说：失踪的城市测绘师留下会自行变化的旧城区地图，" +
      "女主角调查地图时发现每条被抹去的街道都对应一位失踪者。保持人物动机、时间线和伏笔回收一致，" +
      `章节结尾留下适度悬念，避免超自然万能解释。本次独立真实验证标识：${REAL_RUN_TAG}。`,
  );
  await page.getByLabel("题材").fill("都市悬疑");
  await page.getByLabel("标题倾向").fill("消失街区的地图");
  await page.getByLabel("目标读者").fill("偏好长线悬疑与成长叙事的成年读者");
  await page.getByRole("button", { name: "下一步", exact: true }).click();
  await page.getByRole("button", { name: /补充设定/ }).click();
  await page.getByLabel("风格").fill("冷静克制、细节扎实、人物关系渐进");
  await page.getByRole("button", { name: "下一步", exact: true }).click();
  await page.getByLabel("单章字数下限").fill("1800");
  await expect(page.getByLabel("启用自动审核")).toBeChecked();

  await page.getByRole("button", { name: "创建并进入任务页" }).click();
  await expect(page).toHaveURL(/\/p\/task_[^/]+\/?$/, { timeout: 60_000 });
  const taskId = new URL(page.url()).pathname.split("/").filter(Boolean).at(-1) ?? "";
  expect(taskId, "创建页应返回 task_ 前缀的真实任务 ID").toMatch(/^task_/);
  await testInfo.attach("真实80章任务ID.txt", { body: taskId, contentType: "text/plain" });
  console.log(`真实 80 章 UI 慢测任务已创建并保留：${taskId}`);
  return taskId;
}

async function approveOutlineFromUi(page: Page, taskId: string) {
  await openReview(page, taskId);
  const approve = page.getByRole("button", { name: /^(通过并进入章节计划设计|通过本批)$/ });
  await expect(approve).toBeEnabled({ timeout: 60_000 });
  await approve.click();
}

async function approveChapterFromUi(page: Page, taskId: string) {
  await openReview(page, taskId);
  const approve = page.getByRole("button", { name: "通过并进入下一步", exact: true });
  await expect(approve).toBeEnabled({ timeout: 60_000 });
  await approve.click();
}

async function approveVerificationFromUi(page: Page, taskId: string) {
  await openReview(page, taskId);
  const approve = page.getByRole("button", { name: "通过并完成任务", exact: true });
  await expect(approve).toBeEnabled({ timeout: 60_000 });
  await approve.click();
}

async function continueWindowFromUi(page: Page, taskId: string, workspace: WorkspaceSnapshot) {
  await openWorkspace(page, taskId);
  const remaining = workspace.novel_progress?.remaining_chapter_count ?? 20;
  const requested = Math.max(1, Math.min(20, remaining));
  await page.getByLabel("本次创建章节数").fill(String(requested));
  const continueButton = page.getByRole("button", { name: "继续创作", exact: true });
  await expect(continueButton).toBeEnabled({ timeout: 60_000 });
  await continueButton.click();
}

async function recoverFromUi(page: Page, taskId: string) {
  await openWorkspace(page, taskId);
  const recover = page.getByRole("button", { name: /查看恢复方案|恢复任务/ });
  await expect(recover).toBeEnabled({ timeout: 60_000 });
  await recover.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "恢复方案确认" })).toBeVisible({ timeout: 60_000 });
  await expect(dialog.getByRole("button", { name: "确认执行当前动作" })).toBeEnabled({ timeout: 60_000 });
  await dialog.getByRole("button", { name: "确认执行当前动作" }).click();
}

test.describe("真实模型中篇 80 章 UI 自动化", () => {
  test.skip(!SHOULD_RUN_REAL_LLM, "这是会消耗真实模型额度且耗时很长的慢测；请设置 RUN_REAL_LLM_E2E=1 后单独运行。");

  test("从创建开始推进 80 章四个窗口并保留生成任务", async ({ page, request }, testInfo) => {
    const timeoutMs = resolveTimeoutMs();
    testInfo.setTimeout(timeoutMs);
    page.setDefaultTimeout(60_000);
    page.setDefaultNavigationTimeout(60_000);
    const deadline = Date.now() + timeoutMs - 5 * 60 * 1_000;
    const taskId = RESUME_TASK_ID || await createMediumNovelFromUi(page, testInfo);
    if (RESUME_TASK_ID) {
      await testInfo.attach("真实80章续跑任务ID.txt", { body: taskId, contentType: "text/plain" });
      console.log(`真实 80 章 UI 慢测从现有任务继续：${taskId}`);
    }

    let snapshot = await readTaskSnapshot(request, taskId);
    let actionCount = 0;
    while (snapshot.workspace.meta.status !== "completed") {
      if (++actionCount > 100) {
        throw new Error(`人工节点推进次数异常，可能存在循环：${describeWorkspace(snapshot.workspace)}`);
      }

      const status = snapshot.workspace.meta.status;
      if (status === "waiting_manual_action") {
        await recoverFromUi(page, taskId);
        snapshot = await waitForProgressAfterAction(page, request, taskId, snapshot, deadline);
        continue;
      }

      if (status === "created" || status === "sources_ingested") {
        await openWorkspace(page, taskId);
        const start = page.getByRole("button", { name: "开始创作", exact: true });
        await expect(start).toBeEnabled({ timeout: 60_000 });
        await start.click();
        snapshot = await waitForProgressAfterAction(page, request, taskId, snapshot, deadline);
        continue;
      }

      if (status === "waiting_outline_review") {
        await approveOutlineFromUi(page, taskId);
        snapshot = await waitForProgressAfterAction(page, request, taskId, snapshot, deadline);
        continue;
      }

      if (status === "ready_for_batch") {
        await continueWindowFromUi(page, taskId, snapshot.workspace);
        snapshot = await waitForProgressAfterAction(page, request, taskId, snapshot, deadline);
        continue;
      }

      if (status === "waiting_chapter_review") {
        await approveChapterFromUi(page, taskId);
        snapshot = await waitForProgressAfterAction(page, request, taskId, snapshot, deadline);
        continue;
      }

      if (status === "waiting_verification_review") {
        await approveVerificationFromUi(page, taskId);
        snapshot = await waitForProgressAfterAction(page, request, taskId, snapshot, deadline);
        continue;
      }

      if (ACTIVE_STATUSES.has(status)) {
        snapshot = await waitForActionableState(page, request, taskId, deadline);
        continue;
      }

      throw new Error(`遇到未覆盖的任务状态：${describeWorkspace(snapshot.workspace)}`);
    }

    const chapters = await readJson<{ chapters?: Array<{ number?: number; content?: string }> }>(
      request,
      `/api/tasks/${taskId}/chapters`,
      "读取已生成章节",
    );
    expect(chapters.chapters, "任务完成后应可读取章节正文").toHaveLength(80);
    expect(chapters.chapters?.every((chapter) => typeof chapter.content === "string" && chapter.content.trim().length > 0)).toBe(true);

    await page.goto(`/p/${taskId}/?view=result`, { waitUntil: "commit" });
    await expect(page.getByTestId("project-shell")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { name: "生成结果" })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("novel-reader")).toBeVisible();
    await expect(page.getByRole("heading", { name: "章节索引" })).toBeVisible();
  });
});
