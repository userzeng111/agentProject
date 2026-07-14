import test from "node:test";
import assert from "node:assert/strict";

import { isNovelTaskModelSupported, selectNovelTaskModels } from "./model-options.mjs";

const models = [
  { id: "registry-only", metadata: { source: "registry" } },
  { id: "unverified-gateway-model", metadata: { source: "gateway", compatibility: "unverified" } },
  { id: "verified-gateway-model", metadata: { source: "gateway+registry", compatibility: "verified" } },
];

test("小说任务只允许当前供应商目录中已完成兼容性验证的模型", () => {
  assert.equal(isNovelTaskModelSupported(models[1]), false);
  assert.equal(isNovelTaskModelSupported(models[2]), true);
  assert.deepEqual(
    selectNovelTaskModels(models).map((item) => item.id),
    ["verified-gateway-model"],
  );
});
