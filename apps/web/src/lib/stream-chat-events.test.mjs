import test from "node:test";
import assert from "node:assert/strict";

import {
  createChatSseParser,
  getStreamChatErrorMessage,
} from "./stream-chat-events.mjs";

test("createChatSseParser 将 chat.error 事件的 message data 转成错误回调", () => {
  const chunks = [];
  const errors = [];
  const parser = createChatSseParser({
    onChunk: (chunk) => chunks.push(chunk),
    onError: (message) => errors.push(message),
  });

  parser.push("event: chat.error\ndata: {\"message\":\"上游模型连接失败\"}\n\n");
  parser.flush();

  assert.deepEqual(chunks, []);
  assert.deepEqual(errors, ["上游模型连接失败"]);
});

test("createChatSseParser 对同时包含内容、用量和结束标记的事件只派发一次", () => {
  const chunks = [];
  const parser = createChatSseParser({
    onChunk: (chunk) => chunks.push(chunk),
    onError: () => {},
  });

  parser.push('event: chat.chunk\ndata: {"content":"单次回复","usage":{"total_tokens":8},"finish_reason":"stop"}\n\n');
  parser.flush();

  assert.deepEqual(chunks, [
    { content: "单次回复", usage: { total_tokens: 8 }, finish_reason: "stop" },
  ]);
});

test("getStreamChatErrorMessage 为 fetch 网络失败提供中文兜底文案", () => {
  assert.equal(getStreamChatErrorMessage(new TypeError("fetch failed")), "fetch failed");
  assert.equal(getStreamChatErrorMessage("socket closed"), "socket closed");
  assert.equal(getStreamChatErrorMessage(null), "流式请求网络失败");
});
