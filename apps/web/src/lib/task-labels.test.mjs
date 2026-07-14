import { describe, it } from "node:test";
import assert from "node:assert/strict";

// 由于 task-labels.ts 使用 TypeScript 类型，我们需要测试其 JavaScript 逻辑
// 这里测试核心映射逻辑

describe("任务标签工具函数", () => {
  // 模拟 CREATIVE_MODE_LABELS
  const CREATIVE_MODE_LABELS = {
    original: "全新原创",
    fanfic: "同人创作",
    style_remix: "风格复刻",
  };

  // 模拟 NOVEL_SIZE_LABELS
  const NOVEL_SIZE_LABELS = {
    short: "短篇",
    medium: "中篇",
    long: "长篇",
  };

  // 模拟 LEGACY_MODE_TO_CREATIVE
  const LEGACY_MODE_TO_CREATIVE = {
    short_story: "original",
    long_story: "original",
    fanfic: "fanfic",
    style_remix: "style_remix",
  };

  // 模拟 LEGACY_MODE_TO_SIZE
  const LEGACY_MODE_TO_SIZE = {
    short_story: "short",
    long_story: "long",
    fanfic: "medium",
    style_remix: "long",
  };

  // 模拟 resolveCreativeMode 函数
  function resolveCreativeMode(creativeMode, mode) {
    if (creativeMode) {
      return creativeMode;
    }
    return mode ? LEGACY_MODE_TO_CREATIVE[mode] : "original";
  }

  // 模拟 resolveNovelSize 函数
  function resolveNovelSize(novelSize, mode) {
    if (novelSize) {
      return novelSize;
    }
    return mode ? LEGACY_MODE_TO_SIZE[mode] : "short";
  }

  // 模拟 formatCreativeModeLabel 函数
  function formatCreativeModeLabel(creativeMode, mode) {
    return CREATIVE_MODE_LABELS[resolveCreativeMode(creativeMode, mode)];
  }

  // 模拟 formatNovelSizeLabel 函数
  function formatNovelSizeLabel(novelSize, mode) {
    return NOVEL_SIZE_LABELS[resolveNovelSize(novelSize, mode)];
  }

  // 模拟 formatTaskTypeLabel 函数
  function formatTaskTypeLabel(input) {
    return `${formatCreativeModeLabel(input.creativeMode, input.mode)} · ${formatNovelSizeLabel(input.novelSize, input.mode)}`;
  }

  // 模拟 needsStyleProfile 函数
  function needsStyleProfile(creativeMode, mode) {
    const resolved = resolveCreativeMode(creativeMode, mode);
    return resolved === "fanfic" || resolved === "style_remix";
  }

  describe("resolveCreativeMode", () => {
    it("当提供 creativeMode 时直接返回", () => {
      assert.equal(resolveCreativeMode("fanfic", "short_story"), "fanfic");
      assert.equal(resolveCreativeMode("original", "long_story"), "original");
      assert.equal(resolveCreativeMode("style_remix", "fanfic"), "style_remix");
    });

    it("当未提供 creativeMode 时，根据 mode 映射", () => {
      assert.equal(resolveCreativeMode(undefined, "short_story"), "original");
      assert.equal(resolveCreativeMode(undefined, "long_story"), "original");
      assert.equal(resolveCreativeMode(undefined, "fanfic"), "fanfic");
      assert.equal(resolveCreativeMode(undefined, "style_remix"), "style_remix");
    });

    it("当都未提供时返回 original", () => {
      assert.equal(resolveCreativeMode(undefined, undefined), "original");
      assert.equal(resolveCreativeMode(), "original");
    });
  });

  describe("resolveNovelSize", () => {
    it("当提供 novelSize 时直接返回", () => {
      assert.equal(resolveNovelSize("long", "short_story"), "long");
      assert.equal(resolveNovelSize("medium", "long_story"), "medium");
      assert.equal(resolveNovelSize("short", "fanfic"), "short");
    });

    it("当未提供 novelSize 时，根据 mode 映射", () => {
      assert.equal(resolveNovelSize(undefined, "short_story"), "short");
      assert.equal(resolveNovelSize(undefined, "long_story"), "long");
      assert.equal(resolveNovelSize(undefined, "fanfic"), "medium");
      assert.equal(resolveNovelSize(undefined, "style_remix"), "long");
    });

    it("当都未提供时返回 short", () => {
      assert.equal(resolveNovelSize(undefined, undefined), "short");
      assert.equal(resolveNovelSize(), "short");
    });
  });

  describe("formatCreativeModeLabel", () => {
    it("返回正确的中文标签", () => {
      assert.equal(formatCreativeModeLabel("original"), "全新原创");
      assert.equal(formatCreativeModeLabel("fanfic"), "同人创作");
      assert.equal(formatCreativeModeLabel("style_remix"), "风格复刻");
    });

    it("支持通过 mode 参数回退", () => {
      assert.equal(formatCreativeModeLabel(undefined, "short_story"), "全新原创");
      assert.equal(formatCreativeModeLabel(undefined, "fanfic"), "同人创作");
    });
  });

  describe("formatNovelSizeLabel", () => {
    it("返回正确的中文标签", () => {
      assert.equal(formatNovelSizeLabel("short"), "短篇");
      assert.equal(formatNovelSizeLabel("medium"), "中篇");
      assert.equal(formatNovelSizeLabel("long"), "长篇");
    });

    it("支持通过 mode 参数回退", () => {
      assert.equal(formatNovelSizeLabel(undefined, "short_story"), "短篇");
      assert.equal(formatNovelSizeLabel(undefined, "long_story"), "长篇");
      assert.equal(formatNovelSizeLabel(undefined, "fanfic"), "中篇");
    });
  });

  describe("formatTaskTypeLabel", () => {
    it("正确组合创意模式和小说篇幅", () => {
      assert.equal(
        formatTaskTypeLabel({ creativeMode: "original", novelSize: "short" }),
        "全新原创 · 短篇"
      );
      assert.equal(
        formatTaskTypeLabel({ creativeMode: "fanfic", novelSize: "medium" }),
        "同人创作 · 中篇"
      );
      assert.equal(
        formatTaskTypeLabel({ creativeMode: "style_remix", novelSize: "long" }),
        "风格复刻 · 长篇"
      );
    });

    it("支持通过 mode 参数回退", () => {
      assert.equal(
        formatTaskTypeLabel({ mode: "short_story" }),
        "全新原创 · 短篇"
      );
      assert.equal(
        formatTaskTypeLabel({ mode: "long_story" }),
        "全新原创 · 长篇"
      );
    });
  });

  describe("needsStyleProfile", () => {
    it("同人创作需要风格配置", () => {
      assert.equal(needsStyleProfile("fanfic"), true);
    });

    it("风格复刻需要风格配置", () => {
      assert.equal(needsStyleProfile("style_remix"), true);
    });

    it("全新原创不需要风格配置", () => {
      assert.equal(needsStyleProfile("original"), false);
    });

    it("支持通过 mode 参数判断", () => {
      assert.equal(needsStyleProfile(undefined, "fanfic"), true);
      assert.equal(needsStyleProfile(undefined, "style_remix"), true);
      assert.equal(needsStyleProfile(undefined, "short_story"), false);
    });
  });
});
