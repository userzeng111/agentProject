import { expect, Locator, Page } from "@playwright/test";

export const SENSITIVE_TERMS = [
  "raw_response",
  "story_plan",
  "chapter_pair",
  "verification_report",
  "RAG 命中文本",
  "PLAYWRIGHT_SECRET_PROMPT",
  "PLAYWRIGHT_SECRET_RAW_RESPONSE",
  "PLAYWRIGHT_SECRET_RAG_HIT",
];

export async function expectNoSensitiveText(target: Page | Locator) {
  for (const term of SENSITIVE_TERMS) {
    await expect(target.getByText(term, { exact: false }), `不应展示敏感文本：${term}`).toHaveCount(0, {
      timeout: 1_000,
    });
  }
}

export async function expectVisibleTexts(page: Page, texts: string[]) {
  for (const text of texts) {
    await expect(page.getByText(text, { exact: false }).filter({ visible: true }).first(), `页面应展示：${text}`).toBeVisible();
  }
}
