import assert from "node:assert/strict";
import test from "node:test";

import { resolveProjectActions } from "./project-action-availability.mjs";

test("新建任务可运行", () => {
  const actions = resolveProjectActions({ status: "created" });
  assert.equal(actions.runOrContinue.available, true);
  assert.equal(actions.runOrContinue.label, "开始创作");
  assert.equal(actions.archive.available, false);
  assert.equal(actions.review.available, false);
});

test("已入库任务可运行", () => {
  const actions = resolveProjectActions({ status: "sources_ingested" });
  assert.equal(actions.runOrContinue.available, true);
});

test("运行中任务不可运行", () => {
  const actions = resolveProjectActions({ status: "drafting" });
  assert.equal(actions.runOrContinue.available, false);
});

test("ready_for_batch 可继续创作", () => {
  const actions = resolveProjectActions({ status: "ready_for_batch" });
  assert.equal(actions.runOrContinue.available, true);
  assert.equal(actions.runOrContinue.label, "继续创作");
});

test("缺少模型时运行不可用", () => {
  const actions = resolveProjectActions({ status: "created" }, { hasValidModel: false });
  assert.equal(actions.runOrContinue.available, false);
  assert.ok(actions.runOrContinue.reason.includes("模型"));
});

test("操作进行中时所有写操作不可用", () => {
  const actions = resolveProjectActions({ status: "created" }, { running: true });
  assert.equal(actions.runOrContinue.available, false);
  assert.equal(actions.runOrContinue.reason, "操作进行中");
});

test("待审核状态可进入审核", () => {
  const states = ["waiting_outline_review", "waiting_chapter_review", "waiting_verification_review"];
  for (const s of states) {
    const actions = resolveProjectActions({ status: s });
    assert.equal(actions.review.available, true, `status=${s}`);
    assert.equal(actions.review.targetView, "review");
  }
});

test("大纲批次阶段审核按钮文案变更", () => {
  const actions = resolveProjectActions({ status: "waiting_outline_review" }, { outlinePhase: "chapter_batches" });
  assert.equal(actions.review.label, "进入章节计划审核");
});

test("已完成任务可查看结果和归档", () => {
  const actions = resolveProjectActions({ status: "completed" });
  assert.equal(actions.viewResult.available, true);
  assert.equal(actions.archive.available, true);
  assert.equal(actions.delete.available, true);
  assert.match(actions.delete.confirmPrompt, /不可恢复/);
  assert.ok(actions.recover.available === false);
});

test("归档任务不可再归档", () => {
  const actions = resolveProjectActions({ status: "completed", storage_state: "archive" });
  assert.equal(actions.archive.available, false);
  assert.equal(actions.runOrContinue.available, false);
  assert.equal(actions.viewResult.available, true);
});

test("可删除状态", () => {
  const deletable = [
    { status: "created", expect: true },
    { status: "failed", expect: true },
    { status: "cancelled", expect: true },
    { status: "completed", expect: true },
    { status: "drafting", expect: false },
  ];
  for (const { status, expect } of deletable) {
    const actions = resolveProjectActions({ status });
    assert.equal(actions.delete.available, expect, `status=${status}`);
  }
});

test("运行中任务可取消", () => {
  const actions = resolveProjectActions({ status: "drafting" });
  assert.equal(actions.cancel.available, true);
  assert.ok(actions.cancel.confirmPrompt);
});

test("failed 和 manual_action 可恢复", () => {
  const failed = resolveProjectActions({ status: "failed" });
  assert.equal(failed.recover.available, true);

  const manual = resolveProjectActions({ status: "waiting_manual_action" });
  assert.equal(manual.recover.available, true);
});

test("completed 状态不显示恢复", () => {
  const actions = resolveProjectActions({ status: "completed" });
  assert.equal(actions.recover.available, false);
});

test("归档已完成任务不可运行，原因明确", () => {
  const actions = resolveProjectActions({ status: "completed", storage_state: "archive" });
  assert.equal(actions.runOrContinue.available, false);
  assert.equal(actions.runOrContinue.reason, "任务已结束");
});

test("waiting_manual_action 可恢复但不可运行", () => {
  const actions = resolveProjectActions({ status: "waiting_manual_action" });
  assert.equal(actions.recover.available, true);
  assert.equal(actions.runOrContinue.available, false);
  assert.equal(actions.cancel.available, true);
});

test("已取消任务保留恢复入口", () => {
  const actions = resolveProjectActions({ status: "cancelled" });
  assert.equal(actions.recover.available, true);
  assert.equal(actions.recover.reason, null);
  assert.equal(actions.recover.label, "恢复任务");
});

test("已归档失败任务不可再归档", () => {
  const actions = resolveProjectActions({ status: "failed", storage_state: "archive" });
  assert.equal(actions.archive.available, false);
});

test("drafting 状态取消可用且确认文案正确", () => {
  const actions = resolveProjectActions({ status: "drafting" });
  assert.equal(actions.cancel.available, true);
  assert.ok(actions.cancel.confirmPrompt);
  assert.equal(actions.cancel.confirmPrompt, "确认取消此任务？已生成的内容不会丢失。");
});
