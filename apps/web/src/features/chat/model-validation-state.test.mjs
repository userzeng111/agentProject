import test from "node:test";
import assert from "node:assert/strict";

import {
  CHECK_IDS,
  applyValidationChatChunkToMessage,
  buildValidationSessionMessages,
  buildValidationChatUrl,
  createInitialValidationState,
  extractCompatibilityErrorModelId,
  getValidationLinkFromError,
  parseValidationSearch,
  reduceValidationEvent,
} from "./model-validation-state.mjs";

test("createInitialValidationState initializes all checks as pending", () => {
  const state = createInitialValidationState("K2.7");

  assert.equal(state.modelId, "K2.7");
  assert.equal(state.status, "unverified");
  assert.deepEqual(state.checks.map((item) => item.id), CHECK_IDS);
  assert.equal(state.checks.every((item) => item.status === "pending"), true);
});

test("buildValidationChatUrl encodes model id", () => {
  assert.equal(buildValidationChatUrl("vendor/model 1"), "/chat?model=vendor%2Fmodel%201&validate=1");
});

test("parseValidationSearch reads encoded model and validate flag", () => {
  assert.deepEqual(parseValidationSearch("?model=vendor%2Fmodel%201&validate=1"), {
    modelId: "vendor/model 1",
    shouldOpen: true,
  });
  assert.deepEqual(parseValidationSearch("?model=K2.7"), {
    modelId: "K2.7",
    shouldOpen: false,
  });
});

test("reduceValidationEvent updates check status and report", () => {
  let state = createInitialValidationState("K2.7");
  state = reduceValidationEvent(state, {
    type: "validation.started",
    data: { model_id: "K2.7", run_id: "run-1", status: "running" },
  });
  assert.equal(state.status, "running");
  assert.equal(state.runId, "run-1");

  state = reduceValidationEvent(state, {
    type: "validation.check",
    data: { check: { id: "streaming", status: "passed", summary: "收到 chunk", evidence: { chunk_count: 1 } } },
  });
  assert.equal(state.checks.find((item) => item.id === "streaming").status, "passed");
  assert.equal(state.checks.find((item) => item.id === "streaming").summary, "收到 chunk");

  state = reduceValidationEvent(state, {
    type: "validation.done",
    data: { status: "verified", report: { status: "verified", checks: [] } },
  });
  assert.equal(state.status, "verified");
  assert.equal(state.report.status, "verified");
});

test("reduceValidationEvent stores reasoning metadata without reasoning content", () => {
  let state = createInitialValidationState("K2.7");
  state = reduceValidationEvent(state, {
    type: "validation.chat_chunk",
    data: { content: "正文", reasoning_signal: true, reasoning_chars_delta: 24 },
  });

  assert.equal(state.chatContent, "正文");
  assert.equal(state.reasoningSignal, true);
  assert.equal(state.reasoningChars, 24);
  assert.equal("reasoning_content" in state, false);
});

test("validation session messages keep reasoning metadata separate from reasoning content", () => {
  const [, assistant] = buildValidationSessionMessages("K2.7", "run-1");
  const updated = applyValidationChatChunkToMessage(assistant, {
    content: "验证正文",
    reasoning_signal: true,
    reasoning_chars_delta: 18,
  });

  assert.equal(updated.content, "验证正文");
  assert.deepEqual(updated.validation_meta, {
    reasoningSignal: true,
    reasoningChars: 18,
    runId: "run-1",
  });
  assert.equal("reasoning_content" in updated, false);
});

test("validation error stores failed report and failure message", () => {
  let state = createInitialValidationState("K2.7");
  state = reduceValidationEvent(state, {
    type: "validation.error",
    data: {
      status: "failed",
      message: "未收到推理信号",
      check_id: "reasoning_signal",
      report: { status: "failed", failure_reason: "未收到推理信号", checks: [] },
    },
  });

  assert.equal(state.status, "failed");
  assert.equal(state.failureReason, "未收到推理信号");
  assert.equal(state.report.status, "failed");
});

test("cancelled is frontend-only temporary state", () => {
  let state = createInitialValidationState("K2.7");
  state = reduceValidationEvent(state, { type: "validation.cancelled", data: { message: "用户取消验证" } });
  assert.equal(state.status, "cancelled");
  assert.equal(state.report, null);
});

test("getValidationLinkFromError returns encoded chat validation link for compatibility errors", () => {
  assert.equal(
    getValidationLinkFromError("当前所选模型未完成小说工作流兼容性验证，请改用已验证模型。", "vendor/model 1"),
    "/chat?model=vendor%2Fmodel%201&validate=1",
  );
  assert.equal(
    extractCompatibilityErrorModelId("模型 vendor/model 2 未完成兼容性验证，暂不支持小说任务流。"),
    "vendor/model 2",
  );
  assert.equal(
    getValidationLinkFromError("模型 vendor/model 2 未完成兼容性验证，暂不支持小说任务流。", "wrong-model"),
    "/chat?model=vendor%2Fmodel%202&validate=1",
  );
  assert.equal(
    getValidationLinkFromError("暂不支持小说任务流，请先完成兼容性验证。", "K2.7"),
    "/chat?model=K2.7&validate=1",
  );
  assert.equal(getValidationLinkFromError("读取模型列表失败", "K2.7"), null);
  assert.equal(getValidationLinkFromError("未完成兼容性验证", ""), null);
});
