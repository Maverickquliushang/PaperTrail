import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: '../.tmp/playwright-results',
  timeout: 90000,
  workers: 1,
  reporter: 'list',
  webServer: process.env.PAPERTRAIL_TEST_SERVER === '1' ? {
    command: 'npm run dev -- --port 8769 --strictPort',
    url: 'http://127.0.0.1:8769',
    reuseExistingServer: false,
  } : undefined,
  use: {
    channel: process.env.PAPERTRAIL_BROWSER_CHANNEL || undefined,
    baseURL: process.env.PAPERTRAIL_TEST_URL || 'http://127.0.0.1:8765',
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
