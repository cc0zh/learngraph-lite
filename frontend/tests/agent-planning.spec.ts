import type { APIRequestContext, Page } from '@playwright/test';
import type { Plan, PlanningCard, Run } from '../src/types';
import { workbenchURL, expect, learningGoal, runDTO, test } from './fixtures';

const clearIntent = '学习 RAG，成果：完成一个本地检索小实践，基础：会 Python，总投入120分钟';
const composer = '和 Agent 讨论目标与路线';

async function createGoal(request: APIRequestContext, title = clearIntent): Promise<Plan> {
  const response = await request.post('/api/goals', { data: { title } });
  expect(response.ok()).toBe(true); return response.json();
}
function planningRun(plan: Plan, id: string, card: PlanningCard | null, response_to_run_id?: string): Run {
  return { ...runDTO(id, '持久化的规划输入'), mode: 'planning', output: { planning_agent: { planning: plan, card, changes: null, response_to_run_id } } };
}
function writes(page: Page) {
  const values: { path: string; body: Record<string, unknown> }[] = [];
  page.on('request', request => { if (request.method() === 'POST') values.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() }); });
  return values;
}
async function start(page: Page, intent = clearIntent) {
  await page.goto('/?mode=goal');
  await page.getByLabel('描述学习目标').fill(intent);
  await page.getByRole('button', { name: '发送并创建目标' }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('goal')).toBeTruthy();
  await expect(page).toHaveURL(/session=planning/);
}

test('agent: vague intent → dynamic questions → edited goal → route → explanation → diff → explicit publish', async ({ page, request }) => {
  const sent = writes(page);
  await start(page, 'RAG');
  const questions = page.getByRole('region', { name: '澄清问题', exact: true });
  await expect(questions).toBeVisible();
  await questions.getByRole('button', { name: '完成一个小实践', exact: true }).click();
  await questions.getByLabel('你对这个主题有什么基础？（自定义回答）').fill('会 Python，没做过检索');
  await questions.getByRole('button', { name: '跳过：本次大约能投入多少时间？', exact: true }).click();
  await expect(questions).toContainText('为什么问：');
  await questions.getByRole('button', { name: '发送这些回答' }).click();
  const goalCard = page.getByRole('region', { name: '目标审核', exact: true }).last();
  await expect(goalCard).toBeVisible();
  const answerWrite = sent.filter(value => value.path.endsWith('/planning-runs')).at(-1)!;
  expect(answerWrite.body.response_to_run_id).toEqual(expect.any(String));
  expect(answerWrite.body.answers).toEqual([
    { question_id: 'desired_outcome', value: '完成一个小实践', skipped: false },
    { question_id: 'current_level', value: '会 Python，没做过检索', skipped: false },
    { question_id: 'time_budget_minutes', value: '', skipped: true },
  ]);
  await expect(questions.getByRole('button', { name: '发送这些回答' })).toBeDisabled();
  await goalCard.getByRole('button', { name: '修改摘要', exact: true }).click();
  const editor = page.getByRole('form', { name: '本地目标编辑' });
  await editor.getByLabel('可投入时间（总分钟）').fill('120');
  await expect(page.getByRole('complementary', { name: '当前方案' })).toContainText('当前方案');
  expect((await (await request.get(`/api/goals/${new URL(page.url()).searchParams.get('goal')}`)).json()).goal.time_budget_minutes).not.toBe(120); // Local editor is not a saved fact.
  await editor.getByRole('button', { name: '确认目标并生成图谱', exact: true }).click();
  const route = page.getByRole('region', { name: '路线审核', exact: true }).last();
  const publish = route.getByRole('button', { name: '确认并发布路线', exact: true });
  await expect(publish).toBeEnabled();
  await expect(route.getByRole('list', { name: '图谱知识节点', exact: true }).getByRole('listitem')).toHaveCount(4);
  expect(sent.filter(value => value.path.endsWith('/confirm'))).toHaveLength(1);
  expect(sent.filter(value => value.path.endsWith('/graph/publish'))).toHaveLength(0);
  expect(sent.filter(value => value.path.endsWith('/planning-runs')).every(value => !('node_count' in value.body))).toBe(true);
  const goalId = new URL(page.url()).searchParams.get('goal')!;
  const before = await (await request.get(`/api/goals/${goalId}`)).json();
  await page.getByLabel(composer).fill('为什么这样安排？请解释，不要修改路线');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.locator('.assistant-message').last()).toContainText('这一回合只解释，没有修改');
  await expect(publish).toBeEnabled();
  expect(await (await request.get(`/api/goals/${goalId}`)).json()).toEqual(before);
  await page.getByLabel(composer).fill('范围太宽，请缩小路线');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.getByRole('region', { name: '路线审核', exact: true })).toHaveCount(2);
  const cards = page.getByRole('region', { name: '路线审核', exact: true });
  await expect(cards.first().getByRole('button', { name: '确认并发布路线', exact: true })).toBeDisabled();
  await expect(cards.last().getByRole('button', { name: '确认并发布路线', exact: true })).toBeEnabled();
  await expect(page.getByRole('region', { name: '路线变更', exact: true }).last()).toContainText('移除：');
  await expect(cards.last().getByRole('list', { name: '图谱知识节点', exact: true }).getByRole('listitem')).toHaveCount(3);
  const modelCount = sent.filter(value => value.path.endsWith('/planning-runs')).length;
  await cards.last().getByRole('button', { name: '确认并发布路线', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '图谱与节点', exact: true })).toContainText('已发布');
  expect(sent.filter(value => value.path.endsWith('/planning-runs'))).toHaveLength(modelCount);
  expect(sent.filter(value => value.path.endsWith('/graph/publish'))).toHaveLength(1);
  const publishedWrites = sent.length;
  await page.reload();
  await expect(page.getByLabel(composer)).toHaveCount(0);
  expect(sent).toHaveLength(publishedWrites);
  await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button').first().click();
  await page.getByRole('button', { name: '开始学习此节点', exact: true }).click();
  await expect(page.getByLabel('向当前节点提问')).toBeVisible();
});

test('agent: clear input skips the fixed questionnaire; reload is read-only at every viewport', async ({ page }) => {
  const sent = writes(page);
  await start(page);
  const card = page.getByRole('region', { name: '目标审核', exact: true });
  await expect(card.getByRole('button', { name: '确认目标并生成图谱' })).toBeEnabled();
  await expect(page.getByRole('region', { name: '澄清问题' })).toHaveCount(0);
  for (const label of ['希望学到什么程度？', '从哪里开始更合适？', '这次愿意投入多少时间？']) await expect(page.getByRole('heading', { name: label })).toHaveCount(0);
  expect(sent.filter(value => value.path.endsWith('/planning-runs'))).toHaveLength(1);
  const count = sent.length;
  await page.reload();
  await expect(card.getByRole('button', { name: '确认目标并生成图谱' })).toBeEnabled();
  expect(sent).toHaveLength(count);
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    if (width <= 860) {
      await page.getByRole('navigation', { name: '工作台区域' }).getByRole('button', { name: '图谱与节点', exact: true }).click();
      await expect(page.getByRole('complementary', { name: '当前方案' })).toBeVisible();
      await page.getByRole('navigation', { name: '工作台区域' }).getByRole('button', { name: '对话与内容', exact: true }).click();
    }
  }
  expect(sent).toHaveLength(count);
});

test('agent: long history keeps the newest turn in an internal scroll area without new requests', async ({ page, request }) => {
  const plan = await createGoal(request);
  const records = Array.from({ length: 12 }, (_, index) => ({
    ...planningRun(plan, `history-${index}`, null),
    final_text: index === 11 ? '最新方案在这里，可以继续讨论。' : '历史规划说明，仍可向上回顾。'.repeat(35),
  }));
  await page.route('**/api/sessions/*/runs', route => route.fulfill({ json: records }));
  const sent = writes(page);
  await page.goto(workbenchURL(plan.goal_id, `planning:${plan.goal_id}`));
  await expect(page.locator('.planning-history .turn')).toHaveCount(12);
  await expect.poll(() => page.locator('.planning-history').evaluate(element => {
    const container = element.getBoundingClientRect();
    const latest = element.lastElementChild!.getBoundingClientRect();
    return element.scrollTop > 0 && latest.top >= container.top - 1 && latest.bottom <= container.bottom + 1;
  })).toBe(true);
  expect(sent).toEqual([]);
});

test('agent: an existing goal never starts a model on mount, but allows free questions', async ({ page, request }) => {
  const plan = await createGoal(request, 'RAG'); const sent = writes(page);
  await page.goto(workbenchURL(plan.goal_id, `planning:${plan.goal_id}`));
  await expect(page.getByRole('button', { name: '让 Agent 开始规划' })).toBeEnabled();
  await page.reload();
  await expect(page.getByRole('button', { name: '让 Agent 开始规划' })).toBeEnabled();
  expect(sent).toEqual([]);
  await page.getByLabel(composer).fill('为什么需要规划？');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.locator('.assistant-message')).toContainText('这一回合只解释');
  await expect(page.getByRole('region', { name: '澄清问题' })).toHaveCount(0);
  expect(sent).toHaveLength(1);
});

for (const failure of ['not-delivered', 'response-lost'] as const) {
  test(`agent: workbench creation ${failure} persists before sending and recovers explicitly with the same ID`, async ({ page, request }) => {
    const sent = writes(page);
    let attempts = 0; let sawSaved = false;
    await page.route('**/api/goals/*/planning-runs', async route => {
      attempts++; const goalId = new URL(route.request().url()).pathname.split('/')[3];
      sawSaved = await page.evaluate(id => !!localStorage.getItem(`learngraph:command:planning:${id}:pending`), goalId);
      if (attempts === 1) {
        if (failure === 'response-lost') await route.fetch();
        await route.abort('failed');
      } else await route.continue();
    });
    await start(page);
    const pending = page.getByRole('region', { name: '未确认请求恢复' });
    await expect(pending).toBeVisible(); expect(sawSaved).toBe(true);
    await page.reload();
    await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeEnabled();
    expect(attempts).toBe(1);
    await pending.getByRole('button', { name: '重发未确认请求' }).click();
    await expect(pending).toHaveCount(0);
    await expect(page.getByRole('region', { name: '目标审核' }).getByRole('button', { name: '确认目标并生成图谱' })).toBeEnabled();
    const commands = sent.filter(value => value.path.endsWith('/planning-runs'));
    expect(commands).toHaveLength(2); expect(commands[1].body).toEqual(commands[0].body);
    const goalId = new URL(page.url()).searchParams.get('goal')!;
    expect(await (await request.get(`/api/sessions/planning:${goalId}/runs`)).json()).toHaveLength(1);
  });
}

test('agent: lost confirmation is acknowledged by a read, never automatically confirmed or continued', async ({ page, request }) => {
  const sent = writes(page); await start(page);
  await page.route('**/api/goals/*/confirm', async route => { await route.fetch(); await route.abort('failed'); });
  const goalCard = page.getByRole('region', { name: '目标审核' });
  await expect(goalCard.getByRole('button', { name: '修改摘要' })).toBeEnabled();
  await goalCard.getByRole('button', { name: '修改摘要' }).click();
  const editor = page.getByRole('form', { name: '本地目标编辑' });
  await editor.getByRole('textbox', { name: '期望成果', exact: true }).fill('确认响应丢失也保留的成果');
  await editor.getByRole('button', { name: '确认目标并生成图谱' }).click();
  await expect(page.getByRole('alert')).toContainText('确认结果尚不确定');
  await expect(editor.getByRole('textbox', { name: '期望成果', exact: true })).toHaveValue('确认响应丢失也保留的成果');
  const before = sent.length;
  await page.getByRole('button', { name: '刷新目标与路线', exact: true }).click();
  await expect(page.getByRole('button', { name: '继续生成图谱', exact: true })).toBeEnabled();
  await page.reload();
  await expect(page.getByRole('button', { name: '继续生成图谱', exact: true })).toBeEnabled();
  expect(sent).toHaveLength(before);
  expect(sent.filter(value => value.path.endsWith('/confirm'))).toHaveLength(1);
  expect(sent.filter(value => value.path.endsWith('/planning-runs'))).toHaveLength(1);
  const goalId = new URL(page.url()).searchParams.get('goal')!;
  expect((await (await request.get(`/api/goals/${goalId}`)).json()).goal).toMatchObject({ confirmed: true, desired_outcome: '确认响应丢失也保留的成果' });
  await page.getByRole('button', { name: '继续生成图谱', exact: true }).click();
  await expect(page.getByRole('region', { name: '路线审核' }).getByRole('button', { name: '确认并发布路线' })).toBeEnabled();
  expect(sent.filter(value => value.path.endsWith('/confirm'))).toHaveLength(1);
});

test('agent: a rejected continuation retains the confirmed goal and requires an explicit new authorization', async ({ page }) => {
  const sent = writes(page); await start(page);
  let rejected = false;
  await page.route('**/api/goals/*/planning-runs', async route => {
    if (!rejected) { rejected = true; await route.fulfill({ status: 422, json: { error: { message: '模拟生成请求被拒绝' } } }); }
    else await route.continue();
  });
  await page.getByRole('region', { name: '目标审核' }).getByRole('button', { name: '确认目标并生成图谱' }).click();
  await expect(page.getByRole('button', { name: '继续生成图谱', exact: true })).toBeEnabled();
  await expect(page.getByRole('alert')).toContainText('目标已确认');
  const count = sent.length; await page.reload();
  await expect(page.getByRole('button', { name: '继续生成图谱', exact: true })).toBeEnabled();
  expect(sent).toHaveLength(count);
  await page.getByRole('button', { name: '继续生成图谱', exact: true }).click();
  await expect(page.getByRole('region', { name: '路线审核' }).getByRole('button', { name: '确认并发布路线' })).toBeEnabled();
  expect(sent.filter(value => value.path.endsWith('/confirm'))).toHaveLength(1);
});

test('agent: consumed question cards remain readable but disabled even if an explanation keeps the same version', async ({ page, request }) => {
  const plan = await createGoal(request);
  const card: PlanningCard = { kind: 'questions', title: '真正动态的问题', questions: [{ id: 'specific-choice', prompt: '更关心哪类实际成果？', reason: '只询问当前缺失的取舍', options: [{ id: 'option', label: '可复现例子', value: 'example' }], allow_skip: true }] };
  const source = planningRun(plan, 'question-card', card);
  const response = planningRun(plan, 'answered-with-explanation', null, source.run_id);
  await page.route('**/api/sessions/*/runs', route => route.fulfill({ json: [source, response] }));
  const sent = writes(page); await page.goto(workbenchURL(plan.goal_id, `planning:${plan.goal_id}`));
  const questions = page.getByRole('region', { name: '澄清问题' });
  await expect(questions).toContainText('只询问当前缺失的取舍');
  await expect(questions.getByRole('button', { name: '可复现例子' })).toBeDisabled();
  await expect(questions.getByRole('button', { name: '发送这些回答' })).toBeDisabled();
  await expect(page.getByLabel(composer)).toBeEnabled();
  expect(sent).toEqual([]);
});

test('agent: a failed answer consumes its source card across reload, with explicit linked retry only', async ({ page, request }) => {
  const plan = await createGoal(request);
  const source = planningRun(plan, 'failed-source', { kind: 'questions', title: '尚可读取的问题', questions: [
    { id: 'outcome', prompt: '希望做出什么？', reason: '明确验收成果', options: [{ id: 'practice', label: '一个实践', value: 'practice' }], allow_skip: true },
  ] });
  source.final_text = '';
  const failed: Run = { ...planningRun(plan, 'failed-answer', null), status: 'failed', output: {}, response_to_run_id: source.run_id, error: '模拟回答处理失败' };
  const command = { path: `/goals/${plan.goal_id}/planning-runs`, body: { request_id: 'failed-command-id', expected_version: plan.version, user_text: '回答：一个实践', response_to_run_id: source.run_id, answers: [{ question_id: 'outcome', value: 'practice', skipped: false }] } };
  await page.addInitScript(({ goalId, runId, command }) => localStorage.setItem(`learngraph:command:planning:${goalId}:${runId}`, JSON.stringify(command)), { goalId: plan.goal_id, runId: failed.run_id, command });
  await page.route('**/api/sessions/*/runs', route => route.fulfill({ json: [source, failed] }));
  const sent = writes(page);
  await page.route(`**/api/goals/${plan.goal_id}/planning-runs`, route => route.fulfill({ status: 202, json: { ...planningRun(plan, 'retry-answer', null), response_to_run_id: source.run_id } }));
  await page.goto(workbenchURL(plan.goal_id, `planning:${plan.goal_id}`));
  const questions = page.getByRole('region', { name: '澄清问题' });
  await expect(questions.getByRole('button', { name: '一个实践' })).toBeDisabled();
  await expect(page.locator('.assistant-message').first()).toContainText('请查看下方问题卡。');
  await expect(page.getByRole('button', { name: '重试', exact: true })).toBeEnabled();
  await page.reload();
  await expect(questions.getByRole('button', { name: '一个实践' })).toBeDisabled();
  expect(sent).toEqual([]);
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0].body).toMatchObject({ ...command.body, request_id: expect.any(String), retry_of_run_id: failed.run_id });
  expect(sent[0].body.request_id).not.toBe(command.body.request_id);
  await expect(questions.getByRole('button', { name: '一个实践' })).toBeDisabled();
});

test('agent: refresh protects local goal edits and keeps them distinct from saved facts', async ({ page, request }) => {
  const plan = await createGoal(request); const sent = writes(page);
  await page.goto(workbenchURL(plan.goal_id, `planning:${plan.goal_id}`));
  await page.getByRole('button', { name: '编辑当前目标' }).click();
  const editor = page.getByRole('form', { name: '本地目标编辑' });
  await editor.getByRole('textbox', { name: '期望成果', exact: true }).fill('不能被晚到 GET 覆盖的本地成果');
  await page.getByLabel(composer).fill('编辑期间也不丢失对话输入');
  await page.getByRole('button', { name: '刷新目标与路线', exact: true }).click();
  await expect(editor.getByRole('textbox', { name: '期望成果', exact: true })).toHaveValue('不能被晚到 GET 覆盖的本地成果');
  await expect(page.getByRole('button', { name: '发送消息', exact: true })).toBeDisabled();
  await page.reload();
  await expect(editor.getByRole('textbox', { name: '期望成果', exact: true })).toHaveValue('不能被晚到 GET 覆盖的本地成果');
  await expect(page.getByLabel(composer)).toHaveValue('编辑期间也不丢失对话输入');
  await editor.getByRole('button', { name: '放弃本地编辑' }).click();
  await expect(page.getByRole('button', { name: '发送消息', exact: true })).toBeEnabled();
  expect(sent).toEqual([]);
});

test('agent: old route cards cannot unlock while the terminal artifact read is delayed', async ({ page, request }) => {
  const goalId = await learningGoal(request, 'n', false);
  const plan: Plan = await (await request.get(`/api/goals/${goalId}`)).json();
  const old = planningRun(plan, 'old-route', { kind: 'route_review' });
  let latest = old; let delayReads = false; let release = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/sessions/*/runs', route => route.fulfill({ json: latest === old ? [old] : [old, latest] }));
  await page.route(`**/api/goals/${goalId}`, async route => { if (delayReads) await gate; await route.fulfill({ json: plan }); });
  await page.route(`**/api/goals/${goalId}/planning-runs`, async route => {
    latest = planningRun({ ...plan, version: plan.version + 1 }, 'new-route', { kind: 'route_review' });
    await route.fulfill({ status: 202, json: latest });
  });
  await page.goto(workbenchURL(goalId, `planning:${goalId}`));
  const routes = page.getByRole('region', { name: '路线审核' });
  await expect(routes.first().getByRole('button', { name: '确认并发布路线' })).toBeEnabled();
  await page.getByLabel(composer).fill('调整路线');
  delayReads = true;
  await page.getByRole('button', { name: '发送消息' }).click();
  try {
    await expect(routes).toHaveCount(2);
    await expect(routes.first().getByRole('button', { name: '确认并发布路线' })).toBeDisabled();
    await expect(routes.last().getByRole('button', { name: '确认并发布路线' })).toBeDisabled();
  } finally { release(); }
  // GET still has the old version: neither history card is safe to publish.
  await page.getByLabel(composer).fill('解释当前路线，不提交新任务');
  await expect(page.getByRole('button', { name: '发送消息' })).toBeEnabled();
  await expect(routes.first().getByRole('button', { name: '确认并发布路线' })).toBeDisabled();
  await expect(routes.last().getByRole('button', { name: '确认并发布路线' })).toBeDisabled();
});

test('agent: a saved route without a completed review card is explicitly publishable without a model', async ({ page, request }) => {
  const goalId = await learningGoal(request, 'n', false);
  const plan: Plan = await (await request.get(`/api/goals/${goalId}`)).json();
  const failed: Run = { ...planningRun(plan, 'saved-before-failure', null), status: 'failed', error: '路线已保存后运行中断' };
  await page.route('**/api/sessions/*/runs', route => route.fulfill({ json: [failed] }));
  const sent = writes(page);
  await page.goto(workbenchURL(goalId, `planning:${goalId}`));
  const sidebar = page.getByRole('complementary', { name: '当前方案' });
  await expect(sidebar.getByText(/审核已保存路线草稿/)).toBeVisible();
  await page.reload();
  await expect(sidebar.getByText(/审核已保存路线草稿/)).toBeVisible();
  expect(sent).toEqual([]);
  await sidebar.getByText(/审核已保存路线草稿/).click();
  await expect(sidebar.getByRole('list', { name: '图谱知识节点' })).toBeVisible();
  await sidebar.getByRole('button', { name: '确认并发布路线' }).click();
  await expect(page.getByRole('complementary', { name: '图谱与节点', exact: true })).toContainText('已发布');
  expect(sent).toEqual([{ path: `/api/goals/${goalId}/graph/publish`, body: { expected_version: plan.version, expected_revision: plan.graph!.revision } }]);
});

test('agent: persisted user/assistant Markdown and partial SSE are safe; tools use business labels', async ({ page, request, externalRequests }) => {
  const plan = await createGoal(request);
  const run = { ...planningRun(plan, 'streaming-planning', null), status: 'running', user_text: '**用户想法** ![tracker](https://untrusted.invalid/user)', final_text: '', partial_text: '' };
  await page.route('**/api/sessions/*/runs', route => route.fulfill({ json: [run] }));
  await page.route('**/api/runs/*/events', route => route.fulfill({ contentType: 'text/event-stream', body:
    `event: run.snapshot\ndata: ${JSON.stringify({ payload: run })}\n\n` +
    `event: message.delta\ndata: ${JSON.stringify({ payload: { text: '**公开回复** ![tracker](https://untrusted.invalid/assistant)<img src="https://untrusted.invalid/raw">' } })}\n\n` +
    `event: tool.started\ndata: ${JSON.stringify({ payload: { call_id: 'read', name: 'read_planning_context' } })}\n\n` }));
  await page.goto(workbenchURL(plan.goal_id, `planning:${plan.goal_id}`));
  await expect(page.locator('.assistant-message strong').last()).toHaveText('公开回复');
  await expect(page.locator('.user-message strong').last()).toHaveText('用户想法');
  await expect(page.locator('.run-status')).toContainText('读取当前目标与路线');
  await expect(page.locator('.run-status')).not.toContainText('read_planning_context');
  await expect(page.locator('.planning-history img')).toHaveCount(0);
  expect(externalRequests).toEqual([]);
});
