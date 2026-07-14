import test from "node:test";
import assert from "node:assert/strict";

import { createModelValidationSseParser } from "./model-validation-events.mjs";

test("parses validation started check chat_chunk done and error events", () => {
  const events = [];
  const parser = createModelValidationSseParser({
    onEvent: (event) => events.push(event),
    onError: (message) => events.push({ type: "parser.error", message }),
  });

  parser.push("event: validation.started\n");
  parser.push('data: {"model_id":"K2.7","run_id":"run-1","status":"running"}\n\n');
  parser.push("event: validation.check\n");
  parser.push('data: {"check":{"id":"streaming","status":"passed","summary":"收到 chunk"}}\n\n');
  parser.push("event: validation.chat_chunk\n");
  parser.push('data: {"content":"片段","reasoning_signal":true,"reasoning_chars_delta":12}\n\n');
  parser.push("event: validation.done\n");
  parser.push('data: {"status":"verified","report":{"status":"verified"}}\n\n');
  parser.push("event: validation.error\n");
  parser.push('data: {"status":"failed","message":"未收到推理信号","check_id":"reasoning_signal"}\n\n');
  parser.flush();

  assert.deepEqual(events.map((event) => event.type), [
    "validation.started",
    "validation.check",
    "validation.chat_chunk",
    "validation.done",
    "validation.error",
  ]);
  assert.equal(events[1].data.check.id, "streaming");
  assert.equal(events[2].data.content, "片段");
  assert.equal(events[2].data.reasoning_chars_delta, 12);
  assert.equal(events[4].data.check_id, "reasoning_signal");
});

test("waits for blank line before dispatching standard SSE events", () => {
  const events = [];
  const parser = createModelValidationSseParser({
    onEvent: (event) => events.push(event),
    onError: (message) => events.push({ type: "parser.error", message }),
  });

  parser.push("event: validation.chat_chunk\n");
  assert.equal(events.length, 0);
  parser.push('data: {"content":"片段"}\n');
  assert.equal(events.length, 0);
  parser.push("\n");

  assert.equal(events.length, 1);
  assert.equal(events[0].type, "validation.chat_chunk");
  assert.equal(events[0].data.content, "片段");
});

test("reports invalid validation event data without stopping valid later events", () => {
  const events = [];
  const parser = createModelValidationSseParser({
    onEvent: (event) => events.push(event),
    onError: (message) => events.push({ type: "parser.error", message }),
  });

  parser.push("event: validation.check\n");
  parser.push("data: not-json\n\n");
  parser.push("event: validation.done\n");
  parser.push('data: {"status":"verified","report":{"status":"verified"}}\n\n');
  parser.flush();

  assert.equal(events[0].type, "parser.error");
  assert.match(events[0].message, /解析验证事件失败/);
  assert.equal(events[1].type, "validation.done");
});
