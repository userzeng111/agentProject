import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const currentDir = dirname(fileURLToPath(import.meta.url));
const appSrcDir = join(currentDir, "..");

test("全局样式保留中文字体 CSS 变量并移除未使用的 next/font helper", () => {
  const globalsCss = readFileSync(join(appSrcDir, "app", "globals.css"), "utf-8");

  assert.match(globalsCss, /--font-sans-sc:/);
  assert.match(globalsCss, /--font-serif-sc:/);
  assert.equal(existsSync(join(currentDir, "fonts.ts")), false);
});
