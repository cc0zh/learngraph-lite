import { defineConfig } from '@playwright/test';

const baseURL = 'http://127.0.0.1:4174';

export default defineConfig({
  testDir: '.',
  testMatch: 'docs-site.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: 'list',
  // Playwright resolves these paths relative to this config in tests/.
  outputDir: '../test-results/docs',
  use: {
    baseURL,
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run docs:preview',
    cwd: '..',
    url: baseURL,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
