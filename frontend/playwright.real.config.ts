import { defineConfig } from '@playwright/test';

if (process.env.LEARNGRAPH_REAL_BROWSER_APPROVED !== '1') throw new Error('Use npm run smoke:p0:browser:real (paid opt-in).');

export default defineConfig({
  testDir: './real-tests', fullyParallel: false, workers: 1, retries: 0,
  timeout: 540000, expect: { timeout: 150000 },
  outputDir: '../.local/real-browser-results',
  use: { baseURL: 'http://127.0.0.1:5183', trace: 'retain-on-failure' },
  webServer: [
    { command: 'uv run --locked uvicorn real_browser_app:create_app --factory --app-dir scripts --host 127.0.0.1 --port 8010 --timeout-graceful-shutdown 2',
      cwd: '..', url: 'http://127.0.0.1:8010/api/health', reuseExistingServer: false, timeout: 60000 },
    { command: 'node ../node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5183',
      url: 'http://127.0.0.1:5183', env: { LEARNGRAPH_API_TARGET: 'http://127.0.0.1:8010' }, reuseExistingServer: false },
  ],
});
