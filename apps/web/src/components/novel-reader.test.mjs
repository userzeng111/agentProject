import { describe, it } from "node:test";
import assert from "node:assert";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

globalThis.React = React;

describe("NovelReader", () => {
  it("clamps requested page to the available chapter range", async () => {
    const { resolveNovelReaderPage } = await import("./novel-reader");
    const chapters = [
      { number: 1, title: "第一章", content: "第一章正文" },
      { number: 2, title: "第二章", content: "第二章正文" },
    ];

    assert.deepStrictEqual(resolveNovelReaderPage(chapters, -10), {
      page: 1,
      totalPages: 2,
      chapter: chapters[0],
    });
    assert.deepStrictEqual(resolveNovelReaderPage(chapters, 99), {
      page: 2,
      totalPages: 2,
      chapter: chapters[1],
    });
  });

  it("returns an empty reader state when there are no chapters", async () => {
    const { resolveNovelReaderPage } = await import("./novel-reader");

    assert.deepStrictEqual(resolveNovelReaderPage([], 1), {
      page: 1,
      totalPages: 0,
      chapter: null,
    });
  });

  it("does not render legacy hard-coded reader colors", async () => {
    const { NovelReader } = await import("./novel-reader");

    const html = renderToStaticMarkup(
      React.createElement(NovelReader, {
        chapters: [{ number: 1, title: "第一章", content: "第一章正文" }],
      }),
    );

    assert.doesNotMatch(html, /#fffaf2/i);
    assert.doesNotMatch(html, /#1d2a27/i);
  });
});
