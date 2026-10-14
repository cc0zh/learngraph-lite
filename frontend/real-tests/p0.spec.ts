import { test, expect } from '@playwright/test';
import { writeFileSync } from 'node:fs';

test('real P0: UI create → clarify → confirm → graph review → teach/tool → answer → recommendation → reload', async ({ page }) => {
  const report: Record<string, unknown> = { mode: 'real', scope: 'browser P0', started_at: new Date().toISOString(),
    checks: [], runs: [], limitations: ['one small sample, not 20-case model quality evaluation', 'no real failure/cancel/retry coverage'] };
  const checks = report.checks as string[];
  const runs = report.runs as Record<string, unknown>[];
  const errors: string[] = [];
  const external: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    if (new URL(route.request().url()).origin === 'http://127.0.0.1:5183') await route.continue();
    else { external.push(route.request().url()); await route.abort(); }
  });
  page.on('response', async response => {
    if (response.request().method() === 'POST' && response.status() === 202) {
      const value = await response.json().catch(() => null);
      if (value?.run_id) runs.push({ run_id: value.run_id, mode: value.mode });
    }
  });
  try {
    await page.goto('/');
    await expect(page.getByText('Real · 模型已配置')).toBeVisible();
    await page.getByLabel('你想学会什么？').fill('理解 Python 列表与元组的区别（真实浏览器验收）');
    await page.getByRole('button', { name: '开始规划' }).click();
    await expect(page.getByRole('heading', { name: '规划你的学习路线' })).toBeVisible();
    report.goal_id = page.url().split('/goals/')[1].split('/')[0];
    checks.push('browser-created-goal');
    await page.getByRole('button', { name: '获取澄清问题' }).click();
    await expect(page.getByText('先明确这几件事')).toBeVisible();
    await page.getByLabel('期望成果').fill('能解释可变性差异，并为简单场景选择列表或元组');
    await page.getByLabel('已有基础').fill('会 Python 变量与基本语法');
    await page.getByLabel('可投入时间').fill('60');
    await page.getByRole('button', { name: '保存目标信息' }).click();
    await expect(page.getByRole('button', { name: '确认已保存目标' })).toBeEnabled();
    await page.getByRole('button', { name: '确认已保存目标' }).click();
    await page.getByLabel('路线节点数').selectOption('3');
    await page.getByRole('button', { name: '生成路线草稿' }).click();
    await expect(page.getByLabel('节点标题')).toBeVisible();
    await expect(page.getByRole('button', { name: '审核完成，发布路线' })).toBeEnabled();
    checks.push('clarification-and-explicit-confirmation');
    const originalTitle = await page.getByLabel('节点标题').inputValue();
    await page.getByLabel('节点标题').fill(`${originalTitle} · 人工审核`);
    await page.getByRole('button', { name: '保存路线修改' }).click();
    await expect(page.getByText('有未保存修改')).not.toBeVisible();
    await page.getByRole('button', { name: '审核完成，发布路线' }).click();
    await page.getByRole('link', { name: '进入学习' }).click();
    await expect(page.getByRole('heading', { name: `${originalTitle} · 人工审核`, exact: true })).toBeVisible();
    checks.push('three-node-graph-review-edit-publish');
    await page.getByLabel('向当前节点提问').fill('请用一个短例子讲解当前节点，并务必调用 create_exercise 工具创建一道单选练习。不要在回复中披露正确答案或解析。');
    await page.getByRole('button', { name: '发送问题' }).click();
    await expect(page.locator('.assistant-message').last()).toContainText('create_exercise');
    await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeEnabled();
    const exerciseCards = page.locator('.practice-panel .exercise');
    await expect(exerciseCards.first()).toBeVisible();
    expect(await exerciseCards.first().getByRole('radio').count()).toBeGreaterThanOrEqual(2);
    await expect(page.locator('.progress-card')).toContainText('未开始');
    checks.push('real-teaching-native-tool-and-public-exercise');
    await exerciseCards.first().getByRole('radio').first().check(); // Public option only, never read private answers.
    await exerciseCards.first().getByRole('button', { name: '提交答案' }).click();
    await expect(page.locator('.feedback')).toBeVisible();
    await expect(page.locator('.progress-card')).toContainText('1 个有效样本');
    await expect(page.locator('.recommendation')).toBeVisible();
    checks.push('answer-feedback-sample-and-rule-recommendation');
    const count = await exerciseCards.count();
    await page.getByRole('button', { name: '生成练习', exact: true }).click();
    await expect(exerciseCards).toHaveCount(count + 1);
    await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeEnabled();
    checks.push('button-generation-entry');
    const posts: string[] = [];
    page.on('request', request => { if (request.method() === 'POST') posts.push(request.url()); });
    await page.reload();
    await expect(exerciseCards).toHaveCount(count + 1);
    await expect(page.locator('.feedback')).toBeVisible();
    await expect(page.locator('.assistant-message').last()).toContainText('create_exercise');
    expect(posts).toEqual([]);
    checks.push('browser-reload-persisted-artifacts-no-post');
    for (const width of [375, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    }
    expect(errors).toEqual([]); expect(external).toEqual([]);
    checks.push('four-widths-no-overflow-or-external-browser-request');
    // Read-only evidence requests, only after the UI has driven the whole journey.
    report.metrics = await page.evaluate(async () => (await fetch('/api/smoke-metrics')).json());
    for (const run of runs) {
      const saved = await page.evaluate(async id => (await fetch(`/api/runs/${id}`)).json(), String(run.run_id));
      Object.assign(run, { status: saved.status, usage: saved.usage,
        tools: Object.values(saved.tool_activity || {}).map((tool: unknown) => {
          const item = tool as { name: string; status: string }; return { name: item.name, status: item.status };
        }) });
      expect(saved.status).toBe('completed');
    }
    report.result = 'passed';
    await page.screenshot({ path: process.env.LEARNGRAPH_REAL_BROWSER_REPORT!.replace(/\.json$/, '-completed.png'), fullPage: true });
  } catch (error) {
    report.result = 'failed'; report.failure = error instanceof Error ? error.message.slice(0, 2000) : 'browser acceptance failed';
    report.metrics = await page.evaluate(async () => (await fetch('/api/smoke-metrics')).json()).catch(() => undefined);
    throw error;
  } finally {
    report.completed_at = new Date().toISOString();
    writeFileSync(process.env.LEARNGRAPH_REAL_BROWSER_REPORT!, `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx' });
  }
});
