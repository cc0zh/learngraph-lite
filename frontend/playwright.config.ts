import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  webServer: [
    { command: 'uv run --locked uvicorn learngraph_lite.bootstrap:create_business_fixture_app --factory --app-dir src --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 2', cwd: '..', url: 'http://127.0.0.1:8000/api/health', env: { LEARNGRAPH_DATABASE_PATH: '.local/e2e.sqlite3' }, reuseExistingServer: false },
    { command: 'npm run dev', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
  ],
});
