// apps/web/e2e/helpers.ts
import { Page } from '@playwright/test';
import { routes } from './routes';

export async function navigateToHome(page: Page) {
  await page.goto(routes.home);
}

export async function navigateToNewProject(page: Page) {
  await page.goto(routes.newProject);
}

export async function navigateToWorkspace(page: Page, taskId: string) {
  await page.goto(routes.project(taskId));
}

export async function navigateToChat(page: Page) {
  await page.goto(routes.chat);
}

export async function navigateToSettings(page: Page) {
  await page.goto(routes.settings);
}
