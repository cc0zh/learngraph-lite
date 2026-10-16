import { test, expect } from '@playwright/test';
import { writeFileSync } from 'node:fs';
import type { Conversation, Exercise, Plan, Run } from '../src/types';
import productInputs from './user-inputs.json' with { type: 'json' };

test('real P0: UI intent → Agent goal review → confirm → route review → teach/tool → answer → recommendation → reload', async ({ page }) => {
  const report: Record<string, unknown> = { mode: 'real', scope: 'browser P0', started_at: new Date().toISOString(),
    checks: [], runs: [], input_style: 'natural-user-intent', limitations: ['one small sample, not 20-case model quality evaluation', 'no real failure/cancel/retry coverage', 'no semantic guarantee about answer leakage or prerequisite necessity'] };
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
  // Read-only observations verify outcomes; they never prepare or advance the UI journey.
  async function read<T>(path: string): Promise<T> {
    return page.evaluate(async path => {
      const response = await fetch(path);
      if (!response.ok) throw new Error(`Evidence GET failed: ${response.status}`);
      return response.json();
    }, path);
  }
  async function completed(runId: string) {
    await expect.poll(async () => ['completed', 'failed', 'cancelled', 'interrupted', 'budget_exceeded'].includes((await read<Run>(`/api/runs/${runId}`)).status)).toBe(true);
    const saved = await read<Run>(`/api/runs/${runId}`);
    expect(saved.status).toBe('completed');
    return saved;
  }
  function toolCompleted(run: Run, name: string) {
    expect(Object.values(run.tool_activity).some(tool => tool.name === name && tool.status === 'completed')).toBe(true);
  }
  try {
    await page.goto('/?mode=goal');
    await expect(page.getByText('Real · 模型已配置')).toBeVisible();
    await page.getByLabel('描述学习目标').fill(productInputs.goalIntent);
    const goalResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.status() === 202 && new URL(response.url()).pathname.endsWith('/planning-runs'));
    await page.getByRole('button', { name: '发送并创建目标' }).click();
    const goalRun = await completed((await (await goalResponse).json()).run_id);
    toolCompleted(goalRun, 'propose_goal_draft');
    await expect(page.getByRole('region', { name: '目标审核', exact: true })).toBeVisible();
    report.goal_id = new URL(page.url()).searchParams.get('goal');
    const goalId = String(report.goal_id);
    const unconfirmed = await read<Plan>(`/api/goals/${goalId}`);
    expect(unconfirmed.goal.confirmed).toBe(false);
    expect(unconfirmed.graph).toBeNull();
    expect(unconfirmed.goal.time_budget_minutes).toBe(60);
    expect(new URL(page.url()).pathname).toBe('/');
    checks.push('browser-created-goal');
    await expect(page.getByRole('heading', { name: '希望学到什么程度？', exact: true })).toHaveCount(0);
    const routeResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.status() === 202 && new URL(response.url()).pathname.endsWith('/planning-runs'));
    await page.getByRole('button', { name: '确认目标并生成图谱', exact: true }).click();
    const routeRun = await completed((await (await routeResponse).json()).run_id);
    toolCompleted(routeRun, 'generate_route_draft');
    const route = page.getByRole('region', { name: '路线审核', exact: true });
    await expect(route).toBeVisible();
    const stages = route.getByRole('list', { name: '图谱知识节点', exact: true }).getByRole('listitem');
    expect(await stages.count()).toBeGreaterThanOrEqual(1);
    expect(await stages.count()).toBeLessThanOrEqual(30);
    const unpublished = await read<Plan>(`/api/goals/${goalId}`);
    expect(unpublished.goal.confirmed).toBe(true);
    expect(unpublished.graph?.status).toBe('draft');
    checks.push('native-planning-tools-goal-review-and-explicit-confirmation');
    const originalTitle = await stages.first().getByRole('heading', { level: 3 }).innerText();
    await route.getByRole('button', { name: '确认并发布路线', exact: true }).click();
    await expect(page.getByRole('complementary', { name: '图谱与节点', exact: true })).toContainText('已发布');
    await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button', { name: originalTitle, exact: true }).click();
    await page.getByRole('button', { name: '开始学习此节点', exact: true }).click();
    await expect(page.locator('.wb-conversation > .run-status > strong')).toHaveText('已完成');
    await expect(page.getByLabel('当前对话范围')).toContainText(originalTitle);
    checks.push('persisted-graph-explicit-review-publish');
    const session = new URL(page.url()).searchParams.get('session')!;
    const scope = await read<Conversation>(`/api/conversations/${encodeURIComponent(session)}`);
    expect(scope.goal_id).toBe(goalId);
    expect(scope.node_id).toBeTruthy();
    const exercisesPath = `/api/goals/${goalId}/nodes/${encodeURIComponent(scope.node_id!)}/exercises`;
    const before = await read<{ exercises: Exercise[] }>(exercisesPath);
    const previousIds = new Set(before.exercises.map(exercise => exercise.id));
    await page.getByLabel('向当前节点提问').fill(productInputs.practiceRequest);
    const teachingResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.status() === 202 && new URL(response.url()).pathname === `/api/sessions/${session}/runs`);
    await page.getByRole('button', { name: '发送问题' }).click();
    const teachingRun = await completed((await (await teachingResponse).json()).run_id);
    toolCompleted(teachingRun, 'create_exercise');
    const saved = await read<{ exercises: Exercise[] }>(exercisesPath);
    const added = saved.exercises.filter(exercise => !previousIds.has(exercise.id));
    expect(added).toHaveLength(1);
    expect((teachingRun.output?.exercises as Exercise[] | undefined)?.map(exercise => exercise.id)).toEqual(added.map(exercise => exercise.id));
    for (const exercise of added) {
      expect(exercise).not.toHaveProperty('correct_option_id');
      expect(exercise).not.toHaveProperty('explanation');
    }
    await expect(page.locator('.wb-conversation > .run-status > strong')).toHaveText('已完成');
    const teachingReply = await page.locator('.assistant-message').last().innerText();
    await page.getByRole('tab', { name: '学习内容', exact: true }).click();
    await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeEnabled();
    const exerciseCards = page.locator('.wb-exercises .exercise');
    await expect(exerciseCards).toHaveCount(before.exercises.length + 1);
    const newCard = exerciseCards.filter({ has: page.locator(`input[name^="quiz-${added[0].id}-"]`) });
    await expect(newCard).toBeVisible();
    expect(await newCard.getByRole('radio').count()).toBeGreaterThanOrEqual(2);
    await expect(page.locator('.progress-card')).toContainText('未开始');
    checks.push('natural-practice-request-completed-tool-and-new-persisted-public-exercise');
    await newCard.getByRole('radio').first().check(); // Public option only, never read private answers.
    await newCard.getByRole('button', { name: '提交答案' }).click();
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
    await expect(page.locator('.assistant-message').last()).toHaveText(teachingReply, { useInnerText: true });
    expect(posts).toEqual([]);
    checks.push('browser-reload-persisted-artifacts-no-post');
    for (const width of [375, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    }
    expect(errors).toEqual([]); expect(external).toEqual([]);
    checks.push('four-widths-no-overflow-or-external-browser-request');
    // Final read-only evidence; all business writes were driven through the UI.
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
