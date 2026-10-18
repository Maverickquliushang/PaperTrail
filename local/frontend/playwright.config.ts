import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: '../.tmp/playwright-results',
  timeout: 90000,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: process.env.PAPERTRAIL_TEST_URL || 'http://127.0.0.1:8765',
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
