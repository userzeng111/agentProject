import test from "node:test";
import assert from "node:assert/strict";

import { isNovelTaskModelSupported, selectNovelTaskModels } from "./model-options.mjs";

const models = [
  { id: "registry-only", metadata: { source: "registry" } },
  { id: "new-gateway-model", metadata: { source: "gateway" } },
  { id: "known-gateway-model", metadata: { source: "gateway+registry" } },
];

test("AI 对话可用的 gateway 新模型可直接用于小说任务", () => {
  assert.equal(isNovelTaskModelSupported(models[1]), true);
  assert.deepEqual(
    selectNovelTaskModels(models).map((item) => item.id),
    ["new-gateway-model", "known-gateway-model"],
  );
});
