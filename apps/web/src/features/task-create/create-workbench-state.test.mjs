import assert from "node:assert/strict";
import test from "node:test";

import {
  CREATE_WORKBENCH_STAGES,
  resolveCreateWorkbenchReadiness,
  resolveCreateWorkbenchStages,
} from "./create-workbench-state.mjs";

const completePayload = {
  creative_mode: "original",
  prompt: "一场跨越星海的归乡",
  model_id: "creative-model",
  target_chapter_count: 24,
  auto_review: true,
  auto_review_model_mode: "follow_creative",
};

test("创建工作台固定提供故事、参考与执行三阶段", () => {
  assert.deepEqual(
    CREATE_WORKBENCH_STAGES.map((stage) => stage.key),
    ["story", "reference", "execution"],
  );
});

test("基础 payload 完整时三个阶段均完成且没有缺项", () => {
  const options = { payload: completePayload, ragAvailable: true };
  const readiness = resolveCreateWorkbenchReadiness(options);

  assert.equal(readiness.firstIncomplete, null);
  assert.ok(readiness.items.every((item) => item.complete));
  assert.ok(resolveCreateWorkbenchStages(options).every((stage) => stage.complete));
});

test("准备度按固定顺序返回第一个缺项", () => {
  const readiness = resolveCreateWorkbenchReadiness({
    payload: { ...completePayload, prompt: "", model_id: "", target_chapter_count: 0 },
    ragAvailable: false,
  });

  assert.equal(readiness.firstIncomplete?.key, "prompt");
  assert.deepEqual(
    readiness.items.filter((item) => !item.complete).map((item) => item.key),
    ["prompt", "creative-model", "chapters", "rag"],
  );
});

test("同人和风格复刻才显示并校验参考实例", () => {
  const fanficOptions = {
    payload: { ...completePayload, creative_mode: "fanfic", style_profile_id: "" },
    ragAvailable: true,
  };

  assert.equal(resolveCreateWorkbenchReadiness(fanficOptions).firstIncomplete?.key, "style-profile");
  assert.equal(resolveCreateWorkbenchStages(fanficOptions).find((stage) => stage.key === "reference")?.complete, false);
  assert.equal(
    resolveCreateWorkbenchReadiness({ payload: completePayload, ragAvailable: true }).items.some(
      (item) => item.key === "style-profile",
    ),
    false,
  );
});

test("固定审核模型仅在启用固定审核时成为缺项，并采用外部有效性校验", () => {
  const readiness = resolveCreateWorkbenchReadiness({
    payload: {
      ...completePayload,
      auto_review_model_mode: "fixed",
      review_model_id: "review-model",
    },
    ragAvailable: true,
    hasValidCreativeModel: true,
    hasValidReviewModel: false,
  });

  assert.equal(readiness.firstIncomplete?.key, "review-model");
  assert.equal(resolveCreateWorkbenchStages({
    payload: { ...completePayload, auto_review_model_mode: "fixed", review_model_id: "review-model" },
    ragAvailable: true,
    hasValidCreativeModel: true,
    hasValidReviewModel: false,
  }).find((stage) => stage.key === "execution")?.complete, false);
});
