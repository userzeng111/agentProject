import assert from "node:assert/strict";
import test from "node:test";

import {
  formatModelRefreshStatus,
  isCurrentSelectionValid,
  resolveSelectionAfterRefresh,
} from "./model-refresh-state.mjs";

test("失效选择刷新后被清空", () => {
  const result = resolveSelectionAfterRefresh({
    currentModelId: "gpt-5.4",
    availableModels: [{ id: "glm-5.1" }],
  });

  assert.equal(isCurrentSelectionValid("gpt-5.4", [{ id: "glm-5.1" }]), false);
  assert.equal(result.selectedModelId, "");
  assert.equal(result.invalidated, true);
});

test("不允许自动回退到首项", () => {
  const result = resolveSelectionAfterRefresh({
    currentModelId: "gpt-5.4",
    availableModels: [{ id: "glm-5.1" }, { id: "deepseek-v3" }],
  });

  assert.equal(result.selectedModelId, "");
  assert.equal(result.invalidated, true);
  assert.notEqual(result.selectedModelId, "glm-5.1");
});

test("创建页刷新后模型失效时必须阻断并要求手动重选", () => {
  const result = resolveSelectionAfterRefresh({
    currentModelId: "gpt-5.4",
    availableModels: [{ id: "glm-5.1" }],
  });
  const statusText = formatModelRefreshStatus({
    fetchedAt: "2026-04-23T10:00:00Z",
    cacheAgeSeconds: 12,
    cached: false,
    invalidated: true,
    invalidatedModelLabel: "GPT-5.4",
  });

  assert.equal(result.selectedModelId, "");
  assert.equal(result.invalidated, true);
  assert.match(statusText, /已失效/);
  assert.match(statusText, /GPT-5.4/);
  assert.match(statusText, /手动重选/);
});

test("能格式化 fetched time、cache age 和 cached 状态", () => {
  const text = formatModelRefreshStatus({
    attemptedRefresh: true,
    fetchedAt: "2026-04-23T10:00:00Z",
    cacheAgeSeconds: 12,
    cached: true,
  });

  assert.match(text, /最近拉取/);
  assert.match(text, /2026-04-23/);
  assert.match(text, /12/);
  assert.match(text, /缓存/);
});

test("未手动刷新时展示页面加载态文案", () => {
  const text = formatModelRefreshStatus({
    fetchedAt: "2026-04-23T10:00:00Z",
    cacheAgeSeconds: 12,
    cached: true,
  });

  assert.match(text, /尚未手动刷新/);
  assert.doesNotMatch(text, /最近拉取/);
});

test("refresh error 能形成失败文案", () => {
  const text = formatModelRefreshStatus({
    error: "请求超时",
  });

  assert.match(text, /刷新失败/);
  assert.match(text, /请求超时/);
});
