import assert from "node:assert/strict";
import test from "node:test";

import {
  isAsyncTaskInFlight,
  normalizeTaskActionErrorMessage,
  resolveTaskActionSuccessMessage,
} from "./task-action-state.mjs";

test("isAsyncTaskInFlight 识别后台运行态", () => {
  for (const status of ["planning", "drafting", "assembling"]) {
    assert.equal(isAsyncTaskInFlight(status), true, status);
  }

  for (const status of ["created", "waiting_manual_action", "completed", "failed"]) {
    assert.equal(isAsyncTaskInFlight(status), false, status);
  }
});

test("resolveTaskActionSuccessMessage 对后台接收态给出明确反馈", () => {
  assert.equal(
    resolveTaskActionSuccessMessage({ status: "planning" }, "开始执行"),
    "开始执行已提交，任务已进入后台执行，请查看实时日志。",
  );
  assert.equal(
    resolveTaskActionSuccessMessage({ status: "waiting_manual_action" }, "恢复任务"),
    "恢复任务已提交，任务需要人工处理，请查看恢复方案。",
  );
});

test("normalizeTaskActionErrorMessage 将重复提交转成后台运行提示", () => {
  assert.equal(
    normalizeTaskActionErrorMessage("任务正在运行中，请勿重复提交。"),
    "任务已在后台执行，请查看实时日志或稍后刷新状态。",
  );
  assert.equal(
    normalizeTaskActionErrorMessage("当前任务正在执行中，请勿重复提交。"),
    "任务已在后台执行，请查看实时日志或稍后刷新状态。",
  );
  assert.equal(normalizeTaskActionErrorMessage("模型不可用"), "模型不可用");
});
