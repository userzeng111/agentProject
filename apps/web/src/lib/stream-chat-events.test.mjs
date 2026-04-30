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

test("getStreamChatErrorMessage 为 fetch 网络失败提供中文兜底文案", () => {
  assert.equal(getStreamChatErrorMessage(new TypeError("fetch failed")), "fetch failed");
  assert.equal(getStreamChatErrorMessage("socket closed"), "socket closed");
  assert.equal(getStreamChatErrorMessage(null), "流式请求网络失败");
});
