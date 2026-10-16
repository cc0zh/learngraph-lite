import { test, expect } from '@playwright/test';
import { writeFileSync } from 'node:fs';

test('real P0: UI intent → Agent goal review → confirm → route review → teach/tool → answer → recommendation → reload', async ({ page }) => {
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
    await page.goto('/?mode=goal');
    await expect(page.getByText('Real · 模型已配置')).toBeVisible();
    await page.getByLabel('描述学习目标').fill('我会 Python 变量与基本语法，希望总共投入 60 分钟理解列表与元组的区别，能解释可变性差异并为简单场景选择列表或元组。不涉及部署，偏好短例子和练习，路线尽量精简为三个阶段。请根据这些已提供信息提出目标草稿供我确认，不要替我确认或发布。（真实浏览器验收）');
    await page.getByRole('button', { name: '发送并创建目标' }).click();
    await expect(page.getByRole('region', { name: '目标审核', exact: true })).toBeVisible();
    report.goal_id = new URL(page.url()).searchParams.get('goal');
    expect(new URL(page.url()).pathname).toBe('/');
    checks.push('browser-created-goal');
    await expect(page.getByRole('heading', { name: '希望学到什么程度？', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '确认目标并生成图谱', exact: true }).click();
    const route = page.getByRole('region', { name: '路线审核', exact: true });
    await expect(route).toBeVisible();
    const stages = route.getByRole('list', { name: '图谱知识节点', exact: true }).getByRole('listitem');
    expect(await stages.count()).toBeGreaterThanOrEqual(1);
    expect(await stages.count()).toBeLessThanOrEqual(30);
    checks.push('native-planning-tools-goal-review-and-explicit-confirmation');
    const originalTitle = await stages.first().getByRole('heading', { level: 3 }).innerText();
    await route.getByRole('button', { name: '确认并发布路线', exact: true }).click();
    await expect(page.getByRole('complementary', { name: '图谱与节点', exact: true })).toContainText('已发布');
    await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button', { name: originalTitle, exact: true }).click();
    await page.getByRole('button', { name: '开始学习此节点', exact: true }).click();
    await expect(page.locator('.wb-conversation > .run-status > strong')).toHaveText('已完成');
    await expect(page.getByLabel('当前对话范围')).toContainText(originalTitle);
    checks.push('agent-selected-small-graph-explicit-review-publish');
    await page.getByLabel('向当前节点提问').fill('请用一个短例子讲解当前节点，并务必调用 create_exercise 工具创建一道单选练习。不要在回复中披露正确答案或解析。');
    await page.getByRole('button', { name: '发送问题' }).click();
    await expect(page.locator('.wb-conversation > .run-status')).toContainText('create_exercise');
    await expect(page.locator('.wb-conversation > .run-status > strong')).toHaveText('已完成');
    const teachingReply = await page.locator('.assistant-message').last().innerText();
    await page.getByRole('tab', { name: '学习内容', exact: true }).click();
    await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeEnabled();
    const exerciseCards = page.locator('.wb-exercises .exercise');
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
    await page.getByRole('tab', { name: '对话', exact: true }).click();
    await expect(page.locator('.assistant-message').last()).toHaveText(teachingReply);
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
