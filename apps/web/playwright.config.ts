import { defineConfig, devices } from "@playwright/test";

const frontendURL = process.env.PLAYWRIGHT_FRONTEND_URL ?? "http://127.0.0.1:3000";
const backendURL = process.env.PLAYWRIGHT_BACKEND_URL ?? "http://127.0.0.1:8000";
const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  expect: {
    timeout: 15_000,
  },
  use: {
    baseURL: frontendURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    extraHTTPHeaders: {
      "X-Request-ID": "playwright-e2e",
    },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 5"] },
    },
  ],
  webServer: [
    {
      command:
        "cd ../.. && RATE_LIMIT_GENERAL_PER_MINUTE=1000 RATE_LIMIT_CHAT_PER_MINUTE=200 uv run --project apps/agent-runtime python -m uvicorn app.main:app --host 127.0.0.1 --port 8000",
      url: `${backendURL}/api/health`,
      reuseExistingServer: !isCI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `NEXT_PUBLIC_API_BASE_URL=${backendURL} npm run dev -- --hostname 127.0.0.1 --port 3000`,
      url: frontendURL,
      reuseExistingServer: !isCI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
