import { defineConfig } from '@playwright/test';

const webPort = process.env.LEARNGRAPH_E2E_WEB_PORT || '5173';
const apiPort = process.env.LEARNGRAPH_E2E_API_PORT || '8000';
const webURL = `http://127.0.0.1:${webPort}`;
const apiURL = `http://127.0.0.1:${apiPort}`;

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  use: { baseURL: webURL, trace: 'retain-on-failure' },
  webServer: [
    { command: `uv run --locked uvicorn learngraph_lite.bootstrap:create_business_fixture_app --factory --app-dir src --host 127.0.0.1 --port ${apiPort} --timeout-graceful-shutdown 2`, cwd: '..', url: `${apiURL}/api/health`, env: { LEARNGRAPH_DATABASE_PATH: process.env.LEARNGRAPH_E2E_DATABASE_PATH || '.local/e2e.sqlite3' }, reuseExistingServer: false },
    { command: `npm run dev -- --port ${webPort}`, url: webURL, env: { LEARNGRAPH_API_TARGET: apiURL }, reuseExistingServer: false },
  ],
});
