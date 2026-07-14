import { describe, it } from "node:test";
import assert from "node:assert";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import muiStyles from "@mui/material/styles";

globalThis.React = React;
const { createTheme, ThemeProvider } = muiStyles;

describe("MarkdownContent", () => {
  it("渲染代码样式时不输出旧浅色硬编码，并保留链接与图片安全语义", async () => {
    const { default: MarkdownContent } = await import("./markdown-content");
    const markdown = [
      "正文里的 `inlineCode`。",
      "",
      "```ts",
      "const message = 'dark-code';",
      "```",
      "",
      "[危险链接](javascript:alert(1))",
      "",
      "![安全图片](data:image/png;base64,aGVsbG8=)",
    ].join("\n");

    const html = renderToStaticMarkup(
      React.createElement(
        ThemeProvider,
        { theme: createTheme({ palette: { mode: "dark" } }) },
        React.createElement(MarkdownContent, null, markdown),
      ),
    );

    assert.match(html, /<pre/i);
    assert.doesNotMatch(html, /href="javascript:/i);
    assert.doesNotMatch(html, /rgba\(0,\s*0,\s*0,\s*0\.06\)/i);
    assert.doesNotMatch(html, /background-color:\s*#f5f5f5/i);
    assert.doesNotMatch(html, /grey\.100/i);
    assert.match(html, /src="data:image\/png;base64,aGVsbG8="/i);
  });

  it("无语言代码块不会混入行内 code 样式", async () => {
    const { default: MarkdownContent } = await import("./markdown-content");
    const markdown = ["```", "plain fence", "```"].join("\n");

    const html = renderToStaticMarkup(
      React.createElement(
        ThemeProvider,
        { theme: createTheme({ palette: { mode: "dark" } }) },
        React.createElement(MarkdownContent, null, markdown),
      ),
    );

    assert.match(html, /<pre/i);
    assert.doesNotMatch(html, /<pre[\s\S]*border-color:\s*rgba\(148,\s*163,\s*184,\s*0\.28\)[\s\S]*<\/pre>/i);
  });
});
