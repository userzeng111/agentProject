import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveProjectId,
  resolveProjectStageIndex,
  resolveProjectStages,
  resolveProjectAccess,
  normalizeView,
  normalizeArchiveTab,
} from "./project-state.mjs";

test("resolveProjectStageIndex 映射创建态到阶段 0", () => {
  assert.equal(resolveProjectStageIndex("created"), 0);
  assert.equal(resolveProjectStageIndex("sources_ingested"), 0);
});

test("resolveProjectStageIndex 映射规划态到阶段 1", () => {
  assert.equal(resolveProjectStageIndex("planning"), 1);
  assert.equal(resolveProjectStageIndex("waiting_outline_review"), 1);
});

test("resolveProjectStageIndex 映射审核态到阶段 2", () => {
  assert.equal(resolveProjectStageIndex("waiting_chapter_review"), 2);
  assert.equal(resolveProjectStageIndex("waiting_verification_review"), 2);
  assert.equal(resolveProjectStageIndex("waiting_manual_action"), 2);
  assert.equal(resolveProjectStageIndex("failed"), 2);
  assert.equal(resolveProjectStageIndex("cancelled"), 2);
});

test("resolveProjectStageIndex 映射创作态到阶段 3", () => {
  assert.equal(resolveProjectStageIndex("ready_for_batch"), 3);
  assert.equal(resolveProjectStageIndex("drafting"), 3);
  assert.equal(resolveProjectStageIndex("assembling"), 3);
});

test("resolveProjectStageIndex 映射完成态到阶段 4", () => {
  assert.equal(resolveProjectStageIndex("completed"), 4);
});

test("resolveProjectStageIndex 未知状态默认为阶段 0", () => {
  assert.equal(resolveProjectStageIndex("unknown_status"), 0);
  assert.equal(resolveProjectStageIndex(""), 0);
});

test("resolveProjectStages 返回五阶段与活跃索引", () => {
  const result = resolveProjectStages("waiting_chapter_review");
  assert.equal(result.stages.length, 5);
  assert.equal(result.activeStep, 2);
  assert.equal(result.stages[0].label, "创建");
  assert.equal(result.stages[4].label, "完成");
});

/* 视图可达性 */

test("resolveProjectAccess 正常运行任务可进入工作台和审核", () => {
  const access = resolveProjectAccess({
    status: "waiting_outline_review",
    storage_state: "runs",
  });
  assert.equal(access.canViewWorkspace, true);
  assert.equal(access.canViewReview, true);
  assert.equal(access.canViewResult, false);
  assert.equal(access.canViewArchive, false);
  assert.equal(access.reviewBlockReason, null);
  assert.equal(access.resultBlockReason, "结果尚未生成");
  assert.equal(access.archiveBlockReason, "任务尚未完成");
});

test("resolveProjectAccess 已完成任务可查看结果", () => {
  const access = resolveProjectAccess({
    status: "completed",
    storage_state: "runs",
  });
  assert.equal(access.canViewResult, true);
  assert.equal(access.canViewArchive, false);
  assert.equal(access.resultBlockReason, null);
  assert.equal(access.archiveBlockReason, "任务已完成但尚未归档");
});

test("resolveProjectAccess 归档任务可查看归档", () => {
  const access = resolveProjectAccess({
    status: "completed",
    storage_state: "archive",
  });
  assert.equal(access.canViewResult, true);
  assert.equal(access.canViewArchive, true);
  assert.equal(access.archiveBlockReason, null);
});

test("resolveProjectAccess 归档已完成任务可查看归档——存档视图可达", () => {
  const access = resolveProjectAccess({
    storage_state: "archive",
    status: "completed",
  });
  assert.equal(access.canViewArchive, true);
  assert.equal(access.archiveBlockReason, null);
});

test("resolveProjectAccess 已取消任务归档与结果视图不可达", () => {
  const access = resolveProjectAccess({ status: "cancelled" });
  assert.equal(access.canViewArchive, false);
  assert.equal(access.archiveBlockReason, "任务尚未完成");
  assert.equal(access.canViewResult, false);
});

test("resolveProjectAccess 非审核态返回不可审核", () => {
  const access = resolveProjectAccess({
    status: "ready_for_batch",
    storage_state: "runs",
  });
  assert.equal(access.canViewReview, false);
  assert.equal(access.reviewBlockReason, "当前任务不需要审核");
});

test("resolveProjectAccess 审核类型不匹配返回状态异常", () => {
  const access = resolveProjectAccess({
    status: "waiting_chapter_review",
    storage_state: "runs",
    review_type: "outline_review",
  });
  assert.equal(access.canViewReview, false);
  assert.equal(access.reviewBlockReason, "审核数据状态异常");
});

/* view/tab 规范化 */

test("normalizeView 空值返回 workspace", () => {
  assert.equal(normalizeView(null), "workspace");
  assert.equal(normalizeView(undefined), "workspace");
  assert.equal(normalizeView(""), "workspace");
});

test("normalizeView 合法视图原样返回", () => {
  assert.equal(normalizeView("workspace"), "workspace");
  assert.equal(normalizeView("review"), "review");
  assert.equal(normalizeView("result"), "result");
  assert.equal(normalizeView("archive"), "archive");
});

test("normalizeView 大小写不敏感", () => {
  assert.equal(normalizeView("REVIEW"), "review");
  assert.equal(normalizeView("Archive"), "archive");
});

test("normalizeView 非法视图返回 null", () => {
  assert.equal(normalizeView("invalid"), null);
  assert.equal(normalizeView("settings"), null);
});

test("normalizeArchiveTab 空值返回 overview", () => {
  assert.equal(normalizeArchiveTab(null), "overview");
  assert.equal(normalizeArchiveTab(undefined), "overview");
  assert.equal(normalizeArchiveTab(""), "overview");
});

test("normalizeArchiveTab 合法 tab 原样返回", () => {
  assert.equal(normalizeArchiveTab("overview"), "overview");
  assert.equal(normalizeArchiveTab("outline"), "outline");
  assert.equal(normalizeArchiveTab("read"), "read");
  assert.equal(normalizeArchiveTab("meta"), "meta");
});

test("normalizeArchiveTab 非法 tab 返回 overview", () => {
  assert.equal(normalizeArchiveTab("invalid"), "overview");
  assert.equal(normalizeArchiveTab("settings"), "overview");
});

/* resolveProjectId */

test("从规范项目路径解析真实任务 ID", () => {
  assert.equal(resolveProjectId("/p/task_prod_fixture"), "task_prod_fixture");
  assert.equal(resolveProjectId("/p/task_prod_fixture/"), "task_prod_fixture");
});

test("解码路径段并忽略后续路径", () => {
  assert.equal(resolveProjectId("/p/task%20with%20space"), "task with space");
  assert.equal(resolveProjectId("/p/task%2Fwith%2Fslash/logs"), "task/with/slash");
});

test("不会把静态导出占位参数当作真实任务 ID", () => {
  assert.equal(resolveProjectId("/p/__placeholder__/"), "");
});

test("非项目路径返回空", () => {
  assert.equal(resolveProjectId("/tasks/"), "");
  assert.equal(resolveProjectId("/"), "");
  assert.equal(resolveProjectId(""), "");
});
