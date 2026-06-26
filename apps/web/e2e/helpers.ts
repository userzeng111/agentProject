// apps/web/e2e/helpers.ts
import { Page } from '@playwright/test';
import { routes } from './routes';

export async function navigateToHome(page: Page) {
  await page.goto(routes.home);
}

export async function navigateToChat(page: Page) {
  await page.goto(routes.chat);
}

export async function navigateToSettings(page: Page) {
  await page.goto(routes.settings);
}

// TODO: 阶段 2 新增 helpers
// export async function createProject(...) { ... }
// export async function navigateToWorkspace(...) { ... }
