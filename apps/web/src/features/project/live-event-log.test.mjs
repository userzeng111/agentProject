import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToString } from "react-dom/server";

let ConnectionBadge;

test("setup - 加载 ConnectionBadge 组件", async () => {
  // 通过全局 React 解决 tsx JSX 编译后的 React.createElement 引用问题
  globalThis.React = React;
  const mod = await import("./live-event-log.tsx");
  ConnectionBadge = mod.ConnectionBadge;
});

test("ConnectionBadge connected 状态显示已连接", () => {
  const element = React.createElement(ConnectionBadge, { status: "connected" });
  const html = renderToString(element);
  assert.ok(html.includes("已连接"), "Connected 状态渲染应包含 已连接 文本");
});

test("ConnectionBadge error 状态显示连接异常", () => {
  const element = React.createElement(ConnectionBadge, { status: "error" });
  const html = renderToString(element);
  assert.ok(html.includes("连接异常"), "Error 状态渲染应包含 连接异常 文本");
});
