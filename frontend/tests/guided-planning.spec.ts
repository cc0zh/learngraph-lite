import type { APIRequestContext, Page } from '@playwright/test';
import type { GraphNode, Plan } from '../src/types';
import { expect, runDTO, test } from './fixtures';

const outcomeLabel = '期望成果（也可以自己写）';
const foundationLabel = '已有基础（用户自述，未验证）';
const budgetLabel = '可投入时间（总分钟）';
const feedbackLabel = '希望怎样调整路线？';
const advancedSummary = '高级：图谱与节点编辑';
const questions = ['希望学到什么程度？', '从哪里开始更合适？', '这次愿意投入多少时间？'];
const outcomes = ['理解核心概念', '能独立完成一个小成果', '深入原理与复杂应用'];
const foundations = ['第一次接触', '了解一些概念，还没实践', '做过相关练习或项目'];
const budgets = [
  { label: '1 小时 · 快速了解', minutes: 60 },
  { label: '4 小时 · 入门实践', minutes: 240 },
  { label: '12 小时 · 系统学习', minutes: 720 },
];

async function newGoal(request: APIRequestContext): Promise<Plan> {
  const response = await request.post('/api/goals', { data: { title: '引导式学习目标' } });
  expect(response.status()).toBe(201);
  return response.json();
}

function goalWrites(page: Page, goal: string) {
  const writes: { method: string; path: string; body: Record<string, unknown> }[] = [];
  page.on('request', req => {
    const path = new URL(req.url()).pathname;
    if (path.startsWith(`/api/goals/${goal}`) && !['GET', 'HEAD'].includes(req.method())) {
      writes.push({ method: req.method(), path, body: req.postDataJSON() });
    }
  });
  return writes;
}

function summaryField(page: Page, name: RegExp) {
  return page.locator('dl dt').filter({ hasText: name }).locator('xpath=following-sibling::dd[1]');
}

async function next(page: Page) {
  await page.getByRole('button', { name: '下一步', exact: true }).click();
}

async function editableSummary(page: Page) {
  await page.getByRole('button', { name: '先看目标摘要', exact: true }).click();
  await expect(page.getByRole('heading', { name: '目标摘要', level: 3 })).toBeVisible();
  await page.getByRole('button', { name: '修改摘要', exact: true }).click();
}

// Deliberately reverse storage order and give the last stage the highest priority:
// rendering must use prerequisite topology, not DTO order or recommendation priority.
const topologyNodes: GraphNode[] = [
  { id: 'finish', title: '验证小成果', explanation: '检查成果是否满足目标', learning_outcome: '给出可复现的验收结果', estimated_minutes: 90, priority: 5, citation_ids: [] },
  { id: 'start', title: '建立核心概念', explanation: '先辨认概念与边界', learning_outcome: '解释两个核心概念', estimated_minutes: 40, priority: 1, citation_ids: [] },
  { id: 'practice', title: '完成一次实践', explanation: '将概念用于最小例子', learning_outcome: '独立运行最小例子', estimated_minutes: 80, priority: 3, citation_ids: [] },
];
const topologyEdges = [{ source: 'practice', target: 'finish' }, { source: 'start', target: 'practice' }];

async function draftGoal(request: APIRequestContext, budget = 240): Promise<Plan> {
  const created = await request.post('/api/goals', { data: { title: '按依赖顺序学习',
    desired_outcome: '完成一个小成果', current_level: '只了解术语', time_budget_minutes: budget } });
  expect(created.ok()).toBe(true);
  const initial: Plan = await created.json();
  const confirmation = await request.post(`/api/goals/${initial.goal_id}/confirm`, { data: { expected_version: initial.version } });
  expect(confirmation.ok()).toBe(true);
  const confirmed: Plan = await confirmation.json();
  const saved = await request.patch(`/api/goals/${initial.goal_id}/graph`, { data: {
    expected_version: confirmed.version, nodes: topologyNodes, edges: topologyEdges,
  } });
  expect(saved.ok()).toBe(true);
  return saved.json();
}

for (let index = 0; index < outcomes.length; index++) {
  test(`guided: option set ${index + 1} populates all three answers and reviews without writes`, async ({ page, request }) => {
    const initial = await newGoal(request);
    const writes = goalWrites(page, initial.goal_id);
    await page.goto(`/goals/${initial.goal_id}/plan`);
    await expect(page.getByRole('heading', { name: '学习目标', level: 2 })).toBeVisible();
    await expect(page.getByRole('heading', { name: questions[0], level: 3 })).toBeVisible();
    await expect(page.getByRole('textbox', { name: outcomeLabel, exact: true })).toHaveValue('');
    await expect(page.getByRole('textbox', { name: outcomeLabel, exact: true })).toHaveJSProperty('tagName', 'TEXTAREA');
    for (const option of outcomes) await expect(page.getByRole('button', { name: option, exact: true })).toBeVisible();
    await page.getByRole('button', { name: outcomes[index], exact: true }).click();
    await expect(page.getByRole('textbox', { name: outcomeLabel, exact: true })).toHaveValue([/核心概念/, /小成果/, /原理/][index]);
    const outcome = await page.getByRole('textbox', { name: outcomeLabel, exact: true }).inputValue();
    await next(page);
    await expect(page.getByRole('heading', { name: questions[1], level: 3 })).toBeVisible();
    await expect(page.getByRole('textbox', { name: foundationLabel, exact: true })).toHaveJSProperty('tagName', 'TEXTAREA');
    for (const option of foundations) await expect(page.getByRole('button', { name: option, exact: true })).toBeVisible();
    await page.getByRole('button', { name: foundations[index], exact: true }).click();
    await expect(page.getByRole('textbox', { name: foundationLabel, exact: true })).toHaveValue([/接触|基础/, /概念/, /练习|项目/][index]);
    const foundation = await page.getByRole('textbox', { name: foundationLabel, exact: true }).inputValue();
    await next(page);
    await expect(page.getByRole('heading', { name: questions[2], level: 3 })).toBeVisible();
    await expect(page.getByLabel(budgetLabel, { exact: true })).toHaveAttribute('type', 'number');
    for (const option of budgets) await expect(page.getByRole('button', { name: option.label, exact: true })).toBeVisible();
    await page.getByRole('button', { name: budgets[index].label, exact: true }).click();
    await expect(page.getByLabel(budgetLabel, { exact: true })).toHaveValue(String(budgets[index].minutes));
    await next(page);
    await expect(page.getByRole('heading', { name: '目标摘要', level: 3 })).toBeVisible();
    await expect(summaryField(page, /成果与深度/)).toContainText(outcome);
    await expect(summaryField(page, /起点/)).toContainText(foundation);
    await expect(summaryField(page, /总投入/)).toContainText(String(budgets[index].minutes));
    await expect(page.getByRole('button', { name: '确认目标摘要', exact: true })).toBeEnabled();
    expect(writes).toEqual([]);
    expect((await (await request.get(`/api/goals/${initial.goal_id}`)).json()).goal.confirmed).toBe(false);
  });
}

test('guided: custom answers survive backtracking and remain editable in the summary', async ({ page, request }) => {
  const initial = await newGoal(request);
  const writes = goalWrites(page, initial.goal_id);
  await page.goto(`/goals/${initial.goal_id}/plan`);
  await page.getByRole('textbox', { name: outcomeLabel, exact: true }).fill('能给同事演示自己的索引器');
  await next(page);
  await page.getByRole('textbox', { name: foundationLabel, exact: true }).fill('会 TypeScript，但没有实现过索引');
  await next(page);
  await page.getByLabel(budgetLabel, { exact: true }).fill('275');
  await page.getByRole('button', { name: '上一步', exact: true }).click();
  await expect(page.getByRole('textbox', { name: foundationLabel, exact: true })).toHaveValue('会 TypeScript，但没有实现过索引');
  await page.getByRole('button', { name: '上一步', exact: true }).click();
  await expect(page.getByRole('textbox', { name: outcomeLabel, exact: true })).toHaveValue('能给同事演示自己的索引器');
  await next(page); await next(page);
  await expect(page.getByLabel(budgetLabel, { exact: true })).toHaveValue('275');
  await next(page);
  await page.getByRole('button', { name: '修改摘要', exact: true }).click();
  await expect(page.getByLabel('目标', { exact: true })).toHaveValue(initial.goal.title);
  await expect(page.getByRole('textbox', { name: '期望成果', exact: true })).toHaveValue('能给同事演示自己的索引器');
  await expect(page.getByRole('textbox', { name: foundationLabel, exact: true })).toHaveValue('会 TypeScript，但没有实现过索引');
  await expect(page.getByLabel(budgetLabel, { exact: true })).toHaveValue('275');
  await expect(page.getByRole('textbox', { name: '其他约束与重点', exact: true })).toBeVisible();
  expect(writes).toEqual([]);
});

test('guided: skipping all fields exposes defaults as assumptions, never as demonstrated ability', async ({ page, request }) => {
  const initial = await newGoal(request);
  const writes = goalWrites(page, initial.goal_id);
  await page.goto(`/goals/${initial.goal_id}/plan`);
  for (const question of questions) {
    await expect(page.getByRole('heading', { name: question, level: 3 })).toBeVisible();
    await page.getByRole('button', { name: '跳过这一项', exact: true }).click();
  }
  await expect(page.getByRole('heading', { name: '目标摘要', level: 3 })).toBeVisible();
  const outcome = summaryField(page, /成果与深度/);
  const foundation = summaryField(page, /起点/);
  const budget = summaryField(page, /总投入/);
  await expect(outcome).toContainText('理解核心概念、完成适合主题的练习并解释结果');
  await expect(outcome).toContainText('跳过');
  await expect(foundation).toContainText('未知');
  await expect(foundation).toContainText(/不假设.*(?:掌握|能力)/);
  await expect(foundation).toContainText('跳过');
  await expect(budget).toContainText('240');
  await expect(budget).toContainText('规划参考');
  await expect(budget).toContainText('跳过');
  expect(writes).toEqual([]);
  await page.getByRole('button', { name: '修改摘要', exact: true }).click();
  // Defaults are planning assumptions, not fabricated user answers persisted in inputs.
  await expect(page.getByRole('textbox', { name: '期望成果', exact: true })).toHaveValue('');
  await expect(page.getByRole('textbox', { name: foundationLabel, exact: true })).toHaveValue('');
  await expect(page.getByLabel(budgetLabel, { exact: true })).toHaveValue('');
  await page.getByRole('button', { name: '确认目标摘要', exact: true }).click();
  await expect(page.getByRole('button', { name: '生成路线草稿', exact: true })).toBeEnabled();
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({ method: 'POST', path: `/api/goals/${initial.goal_id}/confirm`, body: {
    expected_version: initial.version, desired_outcome: '', current_level: '', time_budget_minutes: null,
    skipped_fields: expect.arrayContaining(['desired_outcome', 'current_level', 'time_budget_minutes']),
  } });
  expect(writes[0].body.skipped_fields).toHaveLength(3);
  const saved: Plan = await (await request.get(`/api/goals/${initial.goal_id}`)).json();
  expect(saved.goal).toMatchObject({ confirmed: true, desired_outcome: '', current_level: '', time_budget_minutes: null,
    skipped_fields: expect.arrayContaining(['desired_outcome', 'current_level', 'time_budget_minutes']) });
});

test('guided: early summary is available at every question without confirmation or generation', async ({ page, request }) => {
  for (let step = 1; step <= 3; step++) {
    const initial = await newGoal(request);
    const writes = goalWrites(page, initial.goal_id);
    await page.goto(`/goals/${initial.goal_id}/plan`);
    for (let prior = 1; prior < step; prior++) await page.getByRole('button', { name: '跳过这一项', exact: true }).click();
    await expect(page.getByRole('heading', { name: questions[step - 1], level: 3 })).toBeVisible();
    await page.getByRole('button', { name: '先看目标摘要', exact: true }).click();
    await expect(page.getByRole('heading', { name: '目标摘要', level: 3 })).toBeVisible();
    await expect(page.getByRole('button', { name: '确认目标摘要', exact: true })).toBeEnabled();
    expect(writes).toEqual([]);
  }
});

test('guided: one explicit confirmation atomically submits every edited field and blocks duplicate clicks', async ({ page, request }) => {
  const initial = await newGoal(request);
  const writes = goalWrites(page, initial.goal_id);
  let release = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**/api/goals/${initial.goal_id}/confirm`, async route => {
    await gate;
    await route.fulfill({ response: await route.fetch() });
  });
  await page.goto(`/goals/${initial.goal_id}/plan`);
  await editableSummary(page);
  await page.getByLabel('目标', { exact: true }).fill('实现可解释的索引器');
  await page.getByRole('textbox', { name: '期望成果', exact: true }).fill('展示检索结果与来源');
  await page.getByRole('textbox', { name: foundationLabel, exact: true }).fill('写过 TypeScript 测试');
  await page.getByLabel(budgetLabel, { exact: true }).fill('135');
  await page.getByRole('textbox', { name: '其他约束与重点', exact: true }).fill('仅使用本地资料，重点解释取舍');
  const confirmation = page.getByRole('button', { name: '确认目标摘要', exact: true });
  try {
    await confirmation.click();
    await expect(confirmation).toBeDisabled();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes).toEqual([{ method: 'POST', path: `/api/goals/${initial.goal_id}/confirm`, body: {
      expected_version: initial.version, title: '实现可解释的索引器', desired_outcome: '展示检索结果与来源',
      current_level: '写过 TypeScript 测试', time_budget_minutes: 135, constraints: '仅使用本地资料，重点解释取舍', skipped_fields: [],
    } }]);
  } finally { release(); }
  await expect(page.getByRole('button', { name: '生成路线草稿', exact: true })).toBeEnabled();
  const confirmed: Plan = await (await request.get(`/api/goals/${initial.goal_id}`)).json();
  expect(confirmed.goal).toMatchObject({ title: '实现可解释的索引器', desired_outcome: '展示检索结果与来源',
    current_level: '写过 TypeScript 测试', time_budget_minutes: 135, constraints: '仅使用本地资料，重点解释取舍', confirmed: true });
  expect(confirmed.graph).toBeNull();
  expect(writes).toHaveLength(1); // No preceding PATCH and no automatic graph generation/publishing.
  await expect(page.getByRole('button', { name: '保存目标信息', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '确认已保存目标', exact: true })).toHaveCount(0);
});

test('guided: a lost confirmation response reconciles matching server inputs by a read, never another POST', async ({ page, request }) => {
  const initial = await newGoal(request);
  const writes = goalWrites(page, initial.goal_id);
  await page.route(`**/api/goals/${initial.goal_id}/confirm`, async route => {
    const response = await route.fetch();
    expect(response.ok()).toBe(true); // The server committed; only the response is lost.
    await route.abort('failed');
  });
  await page.goto(`/goals/${initial.goal_id}/plan`);
  await editableSummary(page);
  await page.getByLabel('目标', { exact: true }).fill('确认响应丢失也能恢复的目标');
  await page.getByRole('textbox', { name: '期望成果', exact: true }).fill('演示一个完整例子');
  await page.getByRole('textbox', { name: foundationLabel, exact: true }).fill('了解核心术语但没有实践');
  await page.getByLabel(budgetLabel, { exact: true }).fill('90');
  await page.getByRole('button', { name: '确认目标摘要', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('textbox', { name: '期望成果', exact: true })).toHaveValue('演示一个完整例子');
  const committed: Plan = await (await request.get(`/api/goals/${initial.goal_id}`)).json();
  expect(committed.goal).toMatchObject({ title: '确认响应丢失也能恢复的目标', desired_outcome: '演示一个完整例子', confirmed: true });
  expect(committed.version).toBe(initial.version + 1);
  expect(writes).toHaveLength(1);
  await page.getByRole('button', { name: '刷新目标与路线', exact: true }).click();
  await expect(page.getByRole('button', { name: '生成路线草稿', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: '修改目标', exact: true })).toBeVisible();
  await expect(summaryField(page, /成果与深度/)).toContainText('演示一个完整例子');
  await page.reload();
  await expect(page.getByRole('button', { name: '生成路线草稿', exact: true })).toBeEnabled();
  expect(writes.map(write => `${write.method} ${write.path}`)).toEqual([`POST /api/goals/${initial.goal_id}/confirm`]);
  expect((await (await request.get(`/api/goals/${initial.goal_id}`)).json()).version).toBe(initial.version + 1);
});

test('guided: refresh and reload restore the confirmed summary and draft using reads only', async ({ page, request }) => {
  const plan = await draftGoal(request);
  const writes = goalWrites(page, plan.goal_id);
  await page.goto(`/goals/${plan.goal_id}/plan`);
  await expect(summaryField(page, /成果与深度/)).toContainText(plan.goal.desired_outcome);
  await expect(page.getByRole('list', { name: '学习阶段', exact: true }).getByRole('listitem')).toHaveCount(3);
  await page.getByRole('button', { name: '刷新目标与路线', exact: true }).click();
  await expect(summaryField(page, /起点/)).toContainText(plan.goal.current_level);
  await page.reload();
  await expect(summaryField(page, /成果与深度/)).toContainText(plan.goal.desired_outcome);
  await expect(page.getByRole('list', { name: '学习阶段', exact: true }).getByRole('listitem')).toHaveCount(3);
  await expect(page.getByRole('button', { name: '修改目标', exact: true })).toBeVisible();
  await expect(page.getByLabel('节点标题')).not.toBeVisible();
  expect(writes).toEqual([]);
});

test('guided: editing a confirmed goal opens the summary directly and reconfirmation clears the old server route', async ({ page, request }) => {
  const plan = await draftGoal(request);
  const writes = goalWrites(page, plan.goal_id);
  await page.goto(`/goals/${plan.goal_id}/plan`);
  await page.getByRole('button', { name: '修改目标', exact: true }).click();
  await expect(page.getByRole('heading', { name: '目标摘要', level: 3 })).toBeVisible();
  for (const question of questions) await expect(page.getByRole('heading', { name: question, level: 3 })).not.toBeVisible();
  await expect(page.getByLabel('目标', { exact: true })).toHaveValue(plan.goal.title);
  await page.getByLabel('目标', { exact: true }).fill('改为实现一个新的学习目标');
  await page.getByRole('textbox', { name: '期望成果', exact: true }).fill('输出新的可验收成果');
  await page.getByRole('button', { name: '确认目标摘要', exact: true }).click();
  await expect(page.getByRole('button', { name: '生成路线草稿', exact: true })).toBeEnabled();
  const changed: Plan = await (await request.get(`/api/goals/${plan.goal_id}`)).json();
  expect(changed.goal).toMatchObject({ title: '改为实现一个新的学习目标', desired_outcome: '输出新的可验收成果', confirmed: true });
  expect(changed.graph).toBeNull();
  expect(writes.map(write => `${write.method} ${write.path}`)).toEqual([`POST /api/goals/${plan.goal_id}/confirm`]);
  await expect(page.getByRole('list', { name: '学习阶段', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '进入学习' })).toHaveCount(0);
});

test('guided: stages expose full content in prerequisite order and compare total minutes against the budget', async ({ page, request }) => {
  for (const budget of [150, 240]) {
    const plan = await draftGoal(request, budget);
    await page.goto(`/goals/${plan.goal_id}/plan`);
    const stages = page.getByRole('list', { name: '学习阶段', exact: true });
    await expect(stages.getByRole('heading', { level: 3 })).toHaveText(['建立核心概念', '完成一次实践', '验证小成果']);
    const ordered = [topologyNodes[1], topologyNodes[2], topologyNodes[0]];
    for (let index = 0; index < ordered.length; index++) {
      const stage = stages.getByRole('listitem').nth(index);
      await stage.getByText('为什么学 · 实践与验证', { exact: true }).click();
      await expect(stage).toContainText(ordered[index].explanation);
      await expect(stage).toContainText(ordered[index].learning_outcome);
      await expect(stage).toContainText(new RegExp(`${ordered[index].estimated_minutes}\\s*分钟`));
    }
    await expect(page.getByText(/阶段.*预计.*210\s*分钟/)).toBeVisible();
    await expect(page.getByText(new RegExp(`(?:总投入|预算).*${budget}\\s*分钟`)).first()).toBeVisible();
    if (budget < 210) await expect(page.getByText(/超出.*60\s*分钟/)).toBeVisible();
    else await expect(page.getByText(/超出.*分钟/)).not.toBeVisible();
    const advanced = page.locator('details').filter({ has: page.locator('summary').filter({ hasText: advancedSummary }) });
    await expect(advanced).not.toHaveAttribute('open', '');
    await expect(page.getByLabel('节点标题')).not.toBeVisible();
    await expect(page.getByRole('button', { name: '保存路线修改', exact: true })).not.toBeVisible();
    await page.getByText(advancedSummary, { exact: true }).click();
    await expect(page.getByLabel('节点标题')).toBeVisible();
    await expect(page.getByRole('button', { name: '保存路线修改', exact: true })).toBeVisible();
  }
});

test('guided: stage review can publish explicitly without opening advanced editing', async ({ page, request }) => {
  const plan = await draftGoal(request);
  const writes = goalWrites(page, plan.goal_id);
  await page.goto(`/goals/${plan.goal_id}/plan`);
  await expect(page.getByRole('list', { name: '学习阶段', exact: true }).getByRole('listitem')).toHaveCount(3);
  await expect(page.getByRole('button', { name: '重新生成', exact: true })).toBeEnabled();
  await expect(page.getByLabel('路线节点数')).not.toBeVisible();
  await page.getByText('路线长度（可选）', { exact: true }).click();
  await expect(page.getByLabel('路线节点数')).toHaveJSProperty('tagName', 'SELECT');
  await page.getByLabel('路线节点数').selectOption('3');
  await expect(page.getByLabel('节点标题')).not.toBeVisible();
  expect(writes).toEqual([]);
  expect((await (await request.get(`/api/goals/${plan.goal_id}`)).json()).graph.status).toBe('draft');
  await expect(page.getByRole('link', { name: '进入学习' })).toHaveCount(0);
  await page.getByRole('button', { name: '审核完成，发布路线', exact: true }).click();
  await expect(page.getByRole('link', { name: '进入学习' })).toBeVisible();
  expect(writes).toEqual([{ method: 'POST', path: `/api/goals/${plan.goal_id}/graph/publish`,
    body: { expected_version: plan.version, expected_revision: plan.graph!.revision } }]);
  expect((await (await request.get(`/api/goals/${plan.goal_id}`)).json()).graph.status).toBe('published');
  await expect(page.getByLabel('节点标题')).not.toBeVisible();
});

test('guided: feedback shortcuts populate distinct editable text without making requests', async ({ page, request }) => {
  const plan = await draftGoal(request);
  const writes = goalWrites(page, plan.goal_id);
  await page.goto(`/goals/${plan.goal_id}/plan`);
  const feedback = page.getByRole('textbox', { name: feedbackLabel, exact: true });
  await expect(feedback).toHaveJSProperty('tagName', 'TEXTAREA');
  await expect(feedback).toHaveValue('');
  await expect(page.getByRole('button', { name: '根据反馈调整路线', exact: true })).toBeDisabled();
  const presets: string[] = [];
  for (const shortcut of ['太难了', '范围太宽', '我已有基础', '调整学习重点']) {
    await page.getByRole('button', { name: shortcut, exact: true }).click();
    await expect(feedback).not.toHaveValue('');
    presets.push(await feedback.inputValue());
    await expect(page.getByRole('button', { name: '根据反馈调整路线', exact: true })).toBeEnabled();
  }
  expect(new Set(presets).size).toBe(4);
  await feedback.fill('只保留一个例子，优先讲清设计取舍');
  await expect(feedback).toHaveValue('只保留一个例子，优先讲清设计取舍');
  expect(writes).toEqual([]);
});

test('guided: feedback generation preserves the old stages until completion and never publishes the replacement', async ({ page, request }) => {
  const plan = await draftGoal(request);
  const writes = goalWrites(page, plan.goal_id);
  const runId = 'guided-feedback-running';
  let result: Record<string, unknown> = { ...runDTO(runId, '', 'running', ''), mode: 'graph' };
  const submissions: Record<string, unknown>[] = [];
  await page.route(`**/api/goals/${plan.goal_id}/graph-drafts`, async route => {
    submissions.push(route.request().postDataJSON());
    await route.fulfill({ status: 202, json: result });
  });
  // An empty stream forces explicit read-only recovery rather than fabricating SSE frames.
  await page.route(`**/api/runs/${runId}/events`, route => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }));
  await page.route(`**/api/runs/${runId}`, route => route.fulfill({ json: result }));
  await page.route('**/api/sessions/*/runs', async route => {
    expect(route.request().method()).toBe('GET');
    await route.fulfill({ json: submissions.length ? [result] : [] });
  });
  await page.goto(`/goals/${plan.goal_id}/plan`);
  await page.getByText('路线长度（可选）', { exact: true }).click();
  await page.getByLabel('路线节点数').selectOption('3');
  await page.getByRole('textbox', { name: feedbackLabel, exact: true }).fill('降低难度，只围绕一个最小成果');
  await page.getByRole('button', { name: '根据反馈调整路线', exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0]).toEqual({ expected_version: plan.version, request_id: expect.any(String),
    node_count: 3, feedback: '降低难度，只围绕一个最小成果' });
  expect(String(submissions[0].request_id).length).toBeGreaterThan(0);
  await expect(page.getByRole('list', { name: '学习阶段', exact: true }).getByRole('heading', { level: 3 })).toHaveText(['建立核心概念', '完成一次实践', '验证小成果']);
  expect((await (await request.get(`/api/goals/${plan.goal_id}`)).json()).graph).toEqual(plan.graph);
  for (const name of ['根据反馈调整路线', '重新生成', '审核完成，发布路线']) {
    await expect(page.getByRole('button', { name, exact: true })).toBeDisabled();
  }
  const changedNodes = topologyNodes.map(node => ({ ...node, title: `${node.title} · 简化版`, estimated_minutes: 20 }));
  const replaced = await request.patch(`/api/goals/${plan.goal_id}/graph`, { data: {
    expected_version: plan.version, nodes: changedNodes, edges: topologyEdges,
  } });
  expect(replaced.ok()).toBe(true);
  const changed: Plan = await replaced.json();
  result = { ...runDTO(runId, '', 'completed', '反馈调整已完成'), mode: 'graph', output: { planning: changed } };
  await page.getByRole('button', { name: '查询运行状态', exact: true }).click();
  await expect(page.getByRole('list', { name: '学习阶段', exact: true }).getByRole('heading', { level: 3 })).toHaveText([
    '建立核心概念 · 简化版', '完成一次实践 · 简化版', '验证小成果 · 简化版',
  ]);
  await expect(page.getByRole('button', { name: '审核完成，发布路线', exact: true })).toBeEnabled();
  expect((await (await request.get(`/api/goals/${plan.goal_id}`)).json()).graph.status).toBe('draft');
  expect(writes.map(write => write.path)).toEqual([`/api/goals/${plan.goal_id}/graph-drafts`]);
  await expect(page.getByRole('link', { name: '进入学习' })).toHaveCount(0);
});

for (const dirty of ['goal', 'graph'] as const) {
  test(`guided: dirty ${dirty} edits gate feedback generation and publication`, async ({ page, request }) => {
    const plan = await draftGoal(request);
    const writes = goalWrites(page, plan.goal_id);
    await page.goto(`/goals/${plan.goal_id}/plan`);
    await page.getByRole('textbox', { name: feedbackLabel, exact: true }).fill('将范围收窄到一个练习');
    await expect(page.getByRole('button', { name: '根据反馈调整路线', exact: true })).toBeEnabled();
    if (dirty === 'goal') {
      await page.getByRole('button', { name: '修改目标', exact: true }).click();
      await page.getByRole('textbox', { name: '期望成果', exact: true }).fill('还未确认的新成果');
    } else {
      await page.getByText(advancedSummary, { exact: true }).click();
      await page.getByLabel('节点标题').fill('还未保存的新标题');
    }
    for (const name of ['根据反馈调整路线', '重新生成', '审核完成，发布路线']) {
      await expect(page.getByRole('button', { name, exact: true })).toBeDisabled();
    }
    expect(writes).toEqual([]);
    expect((await (await request.get(`/api/goals/${plan.goal_id}`)).json()).graph).toEqual(plan.graph);
  });
}

for (const failure of ['not-delivered', 'response-lost'] as const) {
  test(`guided: feedback ${failure} survives reload and only explicitly replays the same full command`, async ({ page, request }) => {
    const plan = await draftGoal(request);
    const submissions: Record<string, unknown>[] = [];
    const runIds: string[] = [];
    await page.route(`**/api/goals/${plan.goal_id}/graph-drafts`, async route => {
      submissions.push(route.request().postDataJSON());
      if (submissions.length === 1 && failure === 'not-delivered') { await route.abort('failed'); return; }
      const response = await route.fetch();
      expect(response.status()).toBe(202);
      runIds.push((await response.json()).run_id);
      if (submissions.length === 1) await route.abort('failed');
      else await route.fulfill({ response });
    });
    await page.goto(`/goals/${plan.goal_id}/plan`);
    await page.getByText('路线长度（可选）', { exact: true }).click();
    await page.getByLabel('路线节点数').selectOption('3');
    await page.getByRole('textbox', { name: feedbackLabel, exact: true }).fill('保留基础阶段，重点练习核心概念');
    await page.getByRole('button', { name: '根据反馈调整路线', exact: true }).click();
    const pending = page.getByRole('region', { name: '未确认请求恢复', exact: true });
    await expect(pending).toBeVisible();
    expect(submissions).toHaveLength(1);
    expect(submissions[0]).toEqual({ expected_version: plan.version, request_id: expect.any(String),
      node_count: 3, feedback: '保留基础阶段，重点练习核心概念' });
    if (failure === 'response-lost') {
      await expect.poll(async () => (await (await request.get(`/api/runs/${runIds[0]}`)).json()).status).toBe('completed');
    }
    await page.reload();
    await expect(pending).toContainText(String(submissions[0].request_id));
    expect(submissions).toHaveLength(1);
    for (const name of ['根据反馈调整路线', '重新生成', '审核完成，发布路线']) {
      await expect(page.getByRole('button', { name, exact: true })).toBeDisabled();
    }
    await pending.getByRole('button', { name: '查询运行状态', exact: true }).click();
    await expect(pending.getByRole('button', { name: '重发未确认请求', exact: true })).toBeEnabled();
    expect(submissions).toHaveLength(1);
    await pending.getByRole('button', { name: '重发未确认请求', exact: true }).click();
    await expect(pending).not.toBeVisible();
    await expect(page.getByRole('button', { name: '审核完成，发布路线', exact: true })).toBeEnabled();
    await expect(page.getByRole('button', { name: '重新生成', exact: true })).toBeEnabled();
    await page.getByRole('textbox', { name: feedbackLabel, exact: true }).fill('恢复后仍然可以提出新的调整');
    await expect(page.getByRole('button', { name: '根据反馈调整路线', exact: true })).toBeEnabled();
    expect(submissions).toHaveLength(2);
    expect(submissions[1]).toEqual(submissions[0]);
    if (failure === 'response-lost') expect(runIds[1]).toBe(runIds[0]);
    const restored: Plan = await (await request.get(`/api/goals/${plan.goal_id}`)).json();
    expect(restored.graph?.status).toBe('draft');
    expect(restored.graph?.nodes).toHaveLength(3);
    await page.reload();
    await expect(pending).not.toBeVisible();
    await expect(page.getByRole('list', { name: '学习阶段', exact: true }).getByRole('listitem')).toHaveCount(3);
    expect(submissions).toHaveLength(2);
  });
}
