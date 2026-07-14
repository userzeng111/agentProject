import test from "node:test";
import assert from "node:assert/strict";

import {
  getModelValidationLabel,
  isGatewayBackedModel,
  resolveChatSelectValue,
  resolveConversationModel,
} from "./model-selection.mjs";

const registryOnlyModels = [
  { id: "outline-local", metadata: { source: "registry" } },
  { id: "style-local", metadata: { source: "registry" } },
];

const mixedModels = [
  { id: "outline-local", metadata: { source: "registry" } },
  { id: "gateway-chat", metadata: { source: "gateway:list_models" } },
  { id: "gateway-alt", metadata: { source: "gateway:list_models" } },
];

test("isGatewayBackedModel 只识别 gateway 来源", () => {
  assert.equal(isGatewayBackedModel(registryOnlyModels[0]), false);
  assert.equal(isGatewayBackedModel(mixedModels[1]), true);
});

test("resolveConversationModel 会忽略保存的 registry 模型", () => {
  assert.equal(resolveConversationModel("outline-local", mixedModels), "");
});

test("resolveConversationModel 保留保存的 gateway 模型", () => {
  assert.equal(resolveConversationModel("gateway-alt", mixedModels), "gateway-alt");
});

test("resolveChatSelectValue 避免选择器使用不存在的模型值", () => {
  assert.equal(resolveChatSelectValue("outline-local", mixedModels), "");
  assert.equal(resolveChatSelectValue("missing-model", mixedModels), "");
  assert.equal(resolveChatSelectValue("gateway-alt", mixedModels), "gateway-alt");
});

test("getModelValidationLabel 返回验证状态标签", () => {
  assert.equal(getModelValidationLabel({ metadata: { compatibility: "verified" } }), "已验证");
  assert.equal(getModelValidationLabel({ metadata: { validation: { status: "failed" } } }), "最近验证失败");
  assert.equal(getModelValidationLabel({ metadata: { compatibility: "unverified" } }), "未验证");
  assert.equal(getModelValidationLabel({ metadata: {} }), "未验证");
});
