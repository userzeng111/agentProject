import assert from "node:assert/strict";
import test from "node:test";

import { reconcileTaskCreateModelSelection } from "./create-task-client.tsx";

test("刷新成功后固定审核模型不在当前可选目录时清空", () => {
  const selection = reconcileTaskCreateModelSelection(
    {
      model_id: "creative-model",
      review_model_id: "removed-review-model",
      auto_review_model_mode: "fixed",
    },
    [{ id: "creative-model" }, { id: "available-review-model" }],
  );

  assert.equal(selection.model_id, "creative-model");
  assert.equal(selection.review_model_id, "");
});

test("刷新失败时清空创作和固定审核模型选择", () => {
  const selection = reconcileTaskCreateModelSelection(
    {
      model_id: "creative-model",
      review_model_id: "review-model",
      auto_review_model_mode: "fixed",
    },
    [],
  );

  assert.equal(selection.model_id, "");
  assert.equal(selection.review_model_id, "");
});

test("跟随模式在刷新后继续同步任务创作模型", () => {
  const selection = reconcileTaskCreateModelSelection(
    {
      model_id: "creative-model",
      review_model_id: "stale-review-model",
      auto_review_model_mode: "follow_creative",
    },
    [{ id: "creative-model" }],
  );

  assert.equal(selection.model_id, "creative-model");
  assert.equal(selection.review_model_id, "creative-model");
});
