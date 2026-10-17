import type { APIRequestContext, Page } from '@playwright/test';
import type { Conversation, Plan, Run } from '../src/types';
import { expect, learningContent, test, workbenchURL } from './fixtures';

const intent = '学习 RAG，成果：完成一个本地检索小实践，基础：会 Python，总投入120分钟';

function writes(page: Page) {
  const sent: { method: string; path: string; body: unknown }[] = [];
  page.on('request', request => {
    if (!['GET', 'HEAD'].includes(request.method())) sent.push({ method: request.method(),
      path: new URL(request.url()).pathname, body: request.postData() ? request.postDataJSON() : null });
  });
  return sent;
}
async function plan(request: APIRequestContext, published = true) {
  const created = await request.post('/api/goals', { data: { title: `生命周期-${crypto.randomUUID()}` } });
  expect(created.ok()).toBe(true);
  let value: Plan = await created.json();
  if (published) {
    const confirmed = await request.post(`/api/goals/${value.goal_id}/confirm`, { data: { expected_version: value.version } });
    expect(confirmed.ok()).toBe(true); value = await confirmed.json();
    const edited = await request.patch(`/api/goals/${value.goal_id}/graph`, { data: { expected_version: value.version,
      nodes: [{ id: 'n', title: '错误与恢复', explanation: '核对结果，不自动重发', learning_outcome: '安全恢复', estimated_minutes: 20, priority: 3 }], edges: [] } });
    expect(edited.ok()).toBe(true); value = await edited.json();
    const result = await request.post(`/api/goals/${value.goal_id}/graph/publish`, { data: { expected_version: value.version, expected_revision: value.graph!.revision } });
    expect(result.ok()).toBe(true); value = await result.json();
  }
  return value;
}
async function conversation(request: APIRequestContext, goal?: string) {
  const session = crypto.randomUUID();
  const title = `独立会话-${crypto.randomUUID()}`;
  const response = await request.post('/api/conversations', { data: { session_id: session, title, goal_id: goal ?? null, node_id: goal ? 'n' : null } });
  expect(response.ok(), await response.text()).toBe(true);
  return { session, title, path: `/api/conversations/${encodeURIComponent(session)}` };
}
async function expandGoal(page: Page, title: string) {
  const details = page.locator('.wb-spaces details').filter({ has: page.locator('summary').filter({ hasText: title }) });
  await expect(details).toHaveCount(1);
  if (!await details.evaluate(element => (element as HTMLDetailsElement).open)) await details.locator(':scope > summary').click();
  return details;
}
async function confirmDelete(page: Page, label: string, accept = true) {
  const dialog = page.waitForEvent('dialog');
  const click = page.getByRole('button', { name: label, exact: true }).click();
  const prompt = await dialog;
  expect(prompt.type()).toBe('confirm');
  expect(prompt.message()).toMatch(/删除|放弃/);
  expect(prompt.message()).toMatch(/会话|图谱|目标/);
  if (accept) await prompt.accept(); else await prompt.dismiss();
  await click;
  return prompt.message();
}
async function storage(page: Page) {
  return page.evaluate(() => Object.fromEntries(Object.entries(localStorage)));
}
async function savedCommand(page: Page, session: string) {
  const key = `learngraph:command:${session}:saved-run`;
  const value = JSON.stringify({ path: `/sessions/${encodeURIComponent(session)}/runs`, body: { request_id: crypto.randomUUID(), user_text: '已保存的重试命令', mode: 'teaching' } });
  await page.evaluate(({ key, value }) => localStorage.setItem(key, value), { key, value });
  return { key, value };
}
async function completed(request: APIRequestContext, response: Awaited<ReturnType<APIRequestContext['post']>>) {
  expect(response.ok()).toBe(true); const run: Run = await response.json();
  await expect.poll(async () => (await (await request.get(`/api/runs/${run.run_id}`)).json()).status).toBe('completed');
}

test('lifecycle: root intent → review → publish → overview → node teaching needs no uploaded materials', async ({ page, request }) => {
  const sent = writes(page);
  await page.goto('/');
  const creation = page.getByRole('region', { name: '创建目标', exact: true });
  await expect(creation).toBeVisible();
  await creation.getByRole('textbox', { name: '描述学习目标', exact: true }).fill(intent);
  await creation.getByRole('button', { name: '发送并创建目标', exact: true }).click();
  await page.getByRole('region', { name: '目标审核', exact: true }).getByRole('button', { name: '确认目标并生成图谱', exact: true }).click();
  await page.getByRole('region', { name: '路线审核', exact: true }).getByRole('button', { name: '确认并发布路线', exact: true }).click();
  const goal = new URL(page.url()).searchParams.get('goal')!;
  const beforeNavigation = sent.length;
  await page.getByRole('button', { name: '选择节点开始学习', exact: true }).click();
  await expect(page.getByRole('region', { name: '知识图谱全景', exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.has('session')).toBe(false);
  expect(new URL(page.url()).searchParams.get('goal')).toBe(goal);
  expect(sent).toHaveLength(beforeNavigation);
  const entry = page.getByRole('region', { name: '进入节点学习', exact: true });
  await expect(entry.getByRole('combobox', { name: '学习节点', exact: true })).toBeEnabled();
  const node = await entry.getByRole('combobox', { name: '学习节点', exact: true }).inputValue();
  await entry.getByRole('button', { name: '开始节点学习', exact: true }).click();
  await expect(page.getByLabel('向当前节点提问', { exact: true })).toBeEnabled();
  await expect(page.getByLabel('当前会话记录')).toContainText('fixture 示例讲解');
  const session = new URL(page.url()).searchParams.get('session')!;
  expect(session).not.toBe(`planning:${goal}`);
  const started = sent.slice(beforeNavigation);
  expect(started.filter(item => item.path === '/api/conversations')).toHaveLength(1);
  expect(started.filter(item => item.path.endsWith('/runs'))).toEqual([{ method: 'POST', path: `/api/sessions/${encodeURIComponent(session)}/runs`,
    body: expect.objectContaining({ mode: 'teaching', goal_id: goal, node_id: node }) }]);
  expect(sent.some(item => item.path.includes('document'))).toBe(false);
  expect((await (await request.get(`/api/goals/${goal}/document-bindings`)).json()).document_ids).toEqual([]);
  expect((await (await request.get(`/api/goals/${goal}/document-bindings?node_id=${encodeURIComponent(node)}`)).json()).document_ids).toEqual([]);
  const count = sent.length; await page.reload();
  await expect(page.getByLabel('向当前节点提问')).toBeEnabled();
  expect(sent).toHaveLength(count);
});

test('lifecycle: goal alias and secondary ordinary-question/new-conversation navigation stay read-only', async ({ page }) => {
  const sent = writes(page);
  await page.goto('/?mode=goal');
  await expect(page.getByRole('region', { name: '创建目标', exact: true })).toBeVisible();
  await page.getByLabel('描述学习目标', { exact: true }).fill('目标草稿不能被普通提问清除');
  await page.getByRole('button', { name: '普通提问', exact: true }).click();
  await expect(page).toHaveURL(/[?]mode=chat$/);
  await page.getByRole('textbox', { name: '发送消息', exact: true }).fill('独立普通草稿');
  await page.getByRole('button', { name: '创建目标', exact: true }).click();
  await expect(page.getByLabel('描述学习目标', { exact: true })).toHaveValue('目标草稿不能被普通提问清除');
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  await expect(page).toHaveURL(/[?]mode=chat$/);
  await expect(page.getByRole('textbox', { name: '发送消息', exact: true })).toHaveValue('独立普通草稿');
  expect(sent).toEqual([]);
});

test('lifecycle: overview continues a saved node conversation without a model; new node conversation is explicit', async ({ page, request }) => {
  const goal = await plan(request); const existing = await conversation(request, goal.goal_id);
  await page.goto(workbenchURL(goal.goal_id, existing.session));
  await page.getByLabel('向当前节点提问').fill('继续对话应恢复的草稿');
  const sent = writes(page);
  await page.goto(workbenchURL(goal.goal_id));
  const entry = page.getByRole('region', { name: '进入节点学习', exact: true });
  await entry.getByRole('combobox', { name: '学习节点', exact: true }).selectOption('n');
  await expect(entry.getByRole('button', { name: '开始节点学习', exact: true })).toHaveCount(0);
  await entry.getByRole('button', { name: '继续节点对话', exact: true }).click();
  await expect(page.getByLabel('向当前节点提问')).toHaveValue('继续对话应恢复的草稿');
  expect(new URL(page.url()).searchParams.get('session')).toBe(existing.session);
  expect(sent).toEqual([]);
  await page.goto(workbenchURL(goal.goal_id));
  await entry.getByRole('button', { name: '新建节点对话', exact: true }).click();
  await expect(page.getByLabel('当前会话记录')).toContainText('fixture 示例讲解');
  expect(new URL(page.url()).searchParams.get('session')).not.toBe(existing.session);
  expect(sent.filter(item => item.path === '/api/conversations')).toHaveLength(1);
  expect(sent.filter(item => item.path.endsWith('/runs'))).toHaveLength(1);
  expect((await (await request.get('/api/conversations')).json() as Conversation[]).filter(item => item.goal_id === goal.goal_id && item.kind === 'learning')).toHaveLength(2);
});

test('lifecycle: cancelling native confirmation never DELETEs a conversation or graph; planning has no individual delete', async ({ page, request }) => {
  const goal = await plan(request); const item = await conversation(request, goal.goal_id);
  const sent = writes(page); await page.goto(workbenchURL(goal.goal_id, item.session));
  await expandGoal(page, goal.goal.title);
  const directory: Conversation[] = await (await request.get('/api/conversations')).json();
  const planning = directory.find(record => record.goal_id === goal.goal_id && record.kind === 'planning');
  expect(planning).toBeTruthy();
  await expect(page.getByRole('button', { name: `删除会话：${planning!.title}`, exact: true })).toHaveCount(0);
  await confirmDelete(page, `删除会话：${item.title}`, false);
  await confirmDelete(page, `删除图谱：${goal.goal.title}`, false);
  expect(sent).toEqual([]);
  expect((await request.get(item.path)).ok()).toBe(true);
  expect((await request.get(`/api/goals/${goal.goal_id}`)).ok()).toBe(true);
  expect(new URL(page.url()).searchParams.get('session')).toBe(item.session);
});

test('lifecycle: deleting the current learning conversation clears only its drafts/commands, preserving shared lessons, exercises and grades', async ({ page, request }) => {
  const goal = await plan(request); const first = await conversation(request, goal.goal_id); const second = await conversation(request, goal.goal_id);
  await completed(request, await request.post(`/api/goals/${goal.goal_id}/nodes/n/exercises`, { data: { session_id: first.session, request_id: crypto.randomUUID(), count: 1, purpose: 'practice' } }));
  const exercises = await (await request.get(`/api/goals/${goal.goal_id}/nodes/n/exercises`)).json();
  expect((await request.post(`/api/goals/${goal.goal_id}/exercises/${exercises.exercises[0].id}/attempts`, { data: { submission_id: crypto.randomUUID(), selected_option_id: 'b' } })).ok()).toBe(true);
  await page.goto(workbenchURL(goal.goal_id, first.session));
  await learningContent(page);
  const generated = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/nodes/n/lessons'));
  await page.getByRole('button', { name: '生成学习包', exact: true }).click();
  expect((await generated).postDataJSON()).toMatchObject({ parent_session_id: first.session });
  await expect(page.getByRole('article', { name: '学习包详情' })).toBeVisible();
  const chapter = page.getByRole('region', { name: '学习包章节', exact: true });
  const explained = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/runs') && request.postDataJSON().mode === 'explanation');
  await chapter.getByRole('button', { name: '让 Agent 解释', exact: true }).click();
  expect((await explained).postDataJSON()).toMatchObject({ parent_session_id: first.session });
  await expect(chapter.getByRole('article', { name: '组件解释' })).toContainText('已完成');
  const lessons = await (await request.get(`/api/goals/${goal.goal_id}/nodes/n/lessons`)).json();
  const graded = await (await request.get(`/api/goals/${goal.goal_id}/nodes/n/exercises`)).json();
  const context = await (await request.get(`/api/goals/${goal.goal_id}/nodes/n/context`)).json();
  await page.getByLabel('向当前节点提问').fill('只清理此会话的未发送草稿');
  const firstCommand = await savedCommand(page, first.session);
  await page.goto(workbenchURL(goal.goal_id, second.session));
  await page.getByLabel('向当前节点提问').fill('其他会话的草稿必须保留');
  const secondCommand = await savedCommand(page, second.session);
  await page.goto(workbenchURL(goal.goal_id, first.session));
  const before = await storage(page);
  const ownDraftKeys = Object.keys(before).filter(key => before[key].includes('只清理此会话的未发送草稿'));
  expect(ownDraftKeys.length).toBeGreaterThan(0);
  const otherDraftKeys = Object.keys(before).filter(key => before[key].includes('其他会话的草稿必须保留'));
  expect(otherDraftKeys.length).toBeGreaterThan(0);
  const sent = writes(page);
  await confirmDelete(page, `删除会话：${first.title}`);
  await expect(page.getByRole('region', { name: '知识图谱全景', exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get('goal')).toBe(goal.goal_id);
  expect(new URL(page.url()).searchParams.has('session')).toBe(false);
  expect(sent).toHaveLength(1); expect(sent[0]).toMatchObject({ method: 'DELETE', path: first.path });
  expect([null, '{}']).toContain(sent[0].body === null ? null : JSON.stringify(sent[0].body));
  expect((await request.get(first.path)).status()).toBe(404);
  expect((await request.get(second.path)).ok()).toBe(true);
  const after = await storage(page);
  for (const key of [...ownDraftKeys, firstCommand.key]) expect(after[key]).toBeUndefined();
  for (const key of [...otherDraftKeys, secondCommand.key]) expect(after[key]).toBe(before[key]);
  expect(await (await request.get(`/api/goals/${goal.goal_id}/nodes/n/lessons`)).json()).toEqual(lessons);
  expect(await (await request.get(`/api/goals/${goal.goal_id}/nodes/n/exercises`)).json()).toEqual(graded);
  expect(await (await request.get(`/api/goals/${goal.goal_id}/nodes/n/context`)).json()).toEqual(context);
  await page.goto(workbenchURL(goal.goal_id, second.session));
  await expect(page.getByLabel('向当前节点提问')).toHaveValue('其他会话的草稿必须保留');
});

test('lifecycle: deleting current ordinary chat returns to the default creation home', async ({ page, request }) => {
  const item = await conversation(request); const sent = writes(page);
  await page.goto(workbenchURL(undefined, item.session));
  await expect(page.getByRole('textbox', { name: '发送消息', exact: true })).toBeEnabled();
  await confirmDelete(page, `删除会话：${item.title}`);
  await expect(page.getByRole('region', { name: '创建目标', exact: true })).toBeVisible();
  expect(new URL(page.url()).search).toBe('');
  expect((await request.get(item.path)).status()).toBe(404);
  expect(sent.map(item => item.method)).toEqual(['DELETE']);
});

test('lifecycle: abandoning an unfinished current goal sends its expected version and removes the planning session', async ({ page, request }) => {
  const goal = await plan(request, false); const sent = writes(page);
  await page.goto(workbenchURL(goal.goal_id, `planning:${goal.goal_id}`));
  await expandGoal(page, goal.goal.title);
  const message = await confirmDelete(page, `放弃目标：${goal.goal.title}`);
  expect(message).toMatch(/规划|会话/);
  await expect(page.getByRole('region', { name: '创建目标', exact: true })).toBeVisible();
  expect(new URL(page.url()).search).toBe('');
  expect(sent).toEqual([{ method: 'DELETE', path: `/api/goals/${goal.goal_id}`, body: { expected_version: goal.version } }]);
  expect((await request.get(`/api/goals/${goal.goal_id}`)).status()).toBe(404);
  expect((await (await request.get('/api/conversations')).json() as Conversation[]).filter(item => item.goal_id === goal.goal_id)).toEqual([]);
});

test('lifecycle: deleting another graph never steals current conversation navigation or deletes an uploaded document', async ({ page, request }) => {
  const removed = await plan(request); const kept = await plan(request);
  const old = await conversation(request, removed.goal_id); const active = await conversation(request, kept.goal_id);
  const upload = await request.post('/api/documents', { multipart: { file: { name: `独立资料-${crypto.randomUUID()}.md`, mimeType: 'text/markdown', buffer: Buffer.from('# 保留原文：删除图谱不删除上传资料。') } } });
  expect(upload.ok()).toBe(true); const document = await upload.json();
  await expect.poll(async () => (await (await request.get(`/api/documents/${document.document_id}`)).json()).status).toBe('ready');
  for (const goal of [removed, kept]) {
    expect((await request.post(`/api/goals/${goal.goal_id}/document-bindings`, { data: { document_id: document.document_id } })).ok()).toBe(true);
  }
  const originalDocument = await (await request.get(`/api/documents/${document.document_id}`)).json();
  const originalBindings = await (await request.get(`/api/goals/${kept.goal_id}/document-bindings`)).json();
  const originalPlan = await (await request.get(`/api/goals/${kept.goal_id}`)).json();
  await page.goto(workbenchURL(kept.goal_id, active.session));
  await page.getByLabel('向当前节点提问').fill('当前另一图谱的草稿');
  const destination = page.url(); const sent = writes(page);
  await expandGoal(page, removed.goal.title);
  await confirmDelete(page, `删除图谱：${removed.goal.title}`);
  await expect(page.getByRole('button', { name: `删除图谱：${removed.goal.title}`, exact: true })).toHaveCount(0);
  expect(page.url()).toBe(destination);
  await expect(page.getByLabel('向当前节点提问')).toHaveValue('当前另一图谱的草稿');
  expect((await request.get(old.path)).status()).toBe(404);
  expect((await request.get(active.path)).ok()).toBe(true);
  expect(await (await request.get(`/api/goals/${kept.goal_id}`)).json()).toEqual(originalPlan);
  expect(await (await request.get(`/api/documents/${document.document_id}`)).json()).toEqual(originalDocument);
  expect(await (await request.get(`/api/goals/${kept.goal_id}/document-bindings`)).json()).toEqual(originalBindings);
  expect(sent).toEqual([{ method: 'DELETE', path: `/api/goals/${removed.goal_id}`, body: { expected_version: removed.version } }]);
});

for (const target of ['conversation', 'goal'] as const) {
  test(`lifecycle: committed ${target} DELETE with a lost response persists a receipt; reload never rewrites; GET 404 confirms cleanup`, async ({ page, request }) => {
    const goal = await plan(request); const item = await conversation(request, goal.goal_id);
    await page.goto(workbenchURL(goal.goal_id, item.session));
    await page.getByLabel('向当前节点提问').fill('查询确认前保留的草稿');
    const command = await savedCommand(page, item.session); const before = await storage(page);
    const path = target === 'goal' ? `/api/goals/${goal.goal_id}` : item.path;
    const label = target === 'goal' ? `删除图谱：${goal.goal.title}` : `删除会话：${item.title}`;
    await page.route(`**${path}`, async route => {
      if (route.request().method() !== 'DELETE') return route.continue();
      const response = await route.fetch(); expect(response.status()).toBe(200); await route.abort('failed');
    });
    const sent = writes(page); await confirmDelete(page, label);
    const status = page.getByRole('region', { name: '删除状态', exact: true });
    await expect(status).toBeVisible();
    const uncertain = await storage(page);
    expect(uncertain[command.key]).toBe(command.value);
    const receipt = uncertain['learngraph:workbench:deletion'];
    expect(receipt).toBeTruthy();
    expect(receipt).toContain(target === 'goal' ? goal.goal_id : item.session);
    await page.reload(); await expect(status).toBeVisible();
    expect(sent.map(item => item.method)).toEqual(['DELETE']);
    const reads: string[] = []; page.on('request', request => { if (request.method() === 'GET') reads.push(new URL(request.url()).pathname); });
    await status.getByRole('button', { name: '查询删除结果', exact: true }).click();
    await expect.poll(() => new URL(page.url()).searchParams.has('session')).toBe(false);
    if (target === 'goal') {
      await expect(page.getByRole('region', { name: '创建目标', exact: true })).toBeVisible();
      expect(new URL(page.url()).search).toBe('');
    } else {
      await expect(page.getByRole('region', { name: '知识图谱全景', exact: true })).toBeVisible();
      expect(new URL(page.url()).searchParams.get('goal')).toBe(goal.goal_id);
    }
    expect(reads).toContain(path); expect(sent.map(item => item.method)).toEqual(['DELETE']);
    const after = await storage(page);
    expect(after[command.key]).toBeUndefined(); expect(after['learngraph:workbench:deletion']).toBeUndefined();
    const draftKeys = Object.entries(before).filter(([, value]) => value.includes('查询确认前保留的草稿')).map(([key]) => key);
    expect(draftKeys.length).toBeGreaterThan(0);
    for (const key of draftKeys) expect(after[key]).toBeUndefined();
    expect((await request.get(path)).status()).toBe(404);
  });
}

test('lifecycle: an undelivered DELETE and failed queries never retry writes; an existing result requires a fresh native confirmation', async ({ page, request }) => {
  const goal = await plan(request); const item = await conversation(request, goal.goal_id);
  await page.goto(workbenchURL(goal.goal_id, item.session));
  await page.getByLabel('向当前节点提问').fill('未送达时不能丢失的草稿');
  const command = await savedCommand(page, item.session); const before = await storage(page);
  let attempts = 0; let failQuery = false;
  await page.route(`**${item.path}`, async route => {
    if (route.request().method() === 'DELETE') {
      attempts++; if (attempts === 1) await route.abort('internetdisconnected'); else await route.continue();
    } else if (failQuery) await route.fulfill({ status: 503, json: { detail: '暂时无法查询' } });
    else await route.continue();
  });
  const sent = writes(page); await confirmDelete(page, `删除会话：${item.title}`);
  const status = page.getByRole('region', { name: '删除状态', exact: true });
  await expect(status).toBeVisible();
  await expect(status.getByRole('button', { name: '重新确认删除', exact: true })).not.toBeEnabled();
  await page.reload(); await expect(status).toBeVisible();
  expect(attempts).toBe(1); failQuery = true;
  for (let index = 0; index < 2; index++) {
    const queried = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === item.path);
    await status.getByRole('button', { name: '查询删除结果', exact: true }).click();
    expect((await queried).status()).toBe(503);
    await expect(status).toContainText(/503|查询失败|无法查询/);
    await expect(status.getByRole('button', { name: '重新确认删除', exact: true })).not.toBeEnabled();
  }
  expect(attempts).toBe(1); expect((await storage(page))[command.key]).toBe(command.value);
  failQuery = false; await status.getByRole('button', { name: '查询删除结果', exact: true }).click();
  await expect(status.getByRole('button', { name: '重新确认删除', exact: true })).toBeEnabled();
  expect(attempts).toBe(1); expect((await request.get(item.path)).ok()).toBe(true);
  const pending = await storage(page);
  for (const [key, value] of Object.entries(before).filter(([, value]) => value.includes('未送达时不能丢失的草稿'))) expect(pending[key]).toBe(value);
  await confirmDelete(page, '重新确认删除', false); expect(attempts).toBe(1);
  await confirmDelete(page, '重新确认删除');
  await expect(page.getByRole('region', { name: '知识图谱全景', exact: true })).toBeVisible();
  expect(attempts).toBe(2); expect(sent.map(item => item.method)).toEqual(['DELETE', 'DELETE']);
  expect((await request.get(item.path)).status()).toBe(404);
  expect((await storage(page))[command.key]).toBeUndefined();
});

test('lifecycle: a late completed teaching POST cannot resurrect a deleted conversation or its cleared commands', async ({ page, request }) => {
  const goal = await plan(request); const item = await conversation(request, goal.goal_id);
  let release!: () => void; let committed!: (run: Run) => void; let delivered!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const accepted = new Promise<Run>(resolve => { committed = resolve; });
  const lateResponse = new Promise<void>(resolve => { delivered = resolve; });
  await page.route('**/api/sessions/*/runs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch(); expect(response.ok()).toBe(true);
    committed(await response.json()); await gate;
    await route.fulfill({ response }); delivered();
  });
  await page.goto(workbenchURL(goal.goal_id, item.session));
  await page.getByLabel('向当前节点提问').fill('响应迟到也不能恢复已删会话');
  await page.getByRole('button', { name: '发送问题', exact: true }).click();
  const run = await accepted;
  await expect.poll(async () => (await (await request.get(`/api/runs/${run.run_id}`)).json()).status).toBe('completed');
  const sent = writes(page);
  try {
    await confirmDelete(page, `删除会话：${item.title}`);
    await expect(page.getByRole('region', { name: '知识图谱全景', exact: true })).toBeVisible();
    expect((await request.get(item.path)).status()).toBe(404);
    const cleared = await storage(page);
    expect(Object.keys(cleared).filter(key => key.startsWith(`learngraph:command:${item.session}:`))).toEqual([]);
    expect(Object.values(cleared).some(value => value.includes('响应迟到也不能恢复已删会话'))).toBe(false);
    const destination = page.url(); release(); await lateResponse;
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    expect(page.url()).toBe(destination);
    await expect(page.getByRole('region', { name: '知识图谱全景', exact: true })).toBeVisible();
    const after = await storage(page);
    expect(Object.keys(after).filter(key => key.startsWith(`learngraph:command:${item.session}:`)), 'Late run ACK must not recreate a command after confirmed deletion').toEqual([]);
    expect(Object.values(after).some(value => value.includes('响应迟到也不能恢复已删会话'))).toBe(false);
    expect(sent.map(item => item.method)).toEqual(['DELETE']);
  } finally { release(); }
});

for (const target of ['conversation', 'goal'] as const) {
  test(`lifecycle: ${target} DELETE 409 keeps visible data, draft, commands and the current route`, async ({ page, request }) => {
    const goal = await plan(request); const item = await conversation(request, goal.goal_id);
    await page.goto(workbenchURL(goal.goal_id, item.session));
    await page.getByLabel('向当前节点提问').fill('冲突时不可清理的草稿');
    const command = await savedCommand(page, item.session); const destination = page.url();
    const path = target === 'goal' ? `/api/goals/${goal.goal_id}` : item.path;
    const label = target === 'goal' ? `删除图谱：${goal.goal.title}` : `删除会话：${item.title}`;
    await page.route(`**${path}`, route => route.request().method() === 'DELETE'
      ? route.fulfill({ status: 409, json: { detail: { message: target === 'goal' ? '版本已过期，请刷新后重试' : '仍有活跃任务，请等待完成' } } }) : route.continue());
    const sent = writes(page); await confirmDelete(page, label);
    await expect(page.getByRole('alert')).toContainText(/等待|刷新/);
    await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
    await expect(page.getByLabel('向当前节点提问')).toHaveValue('冲突时不可清理的草稿');
    expect(page.url()).toBe(destination); expect((await storage(page))[command.key]).toBe(command.value);
    expect((await request.get(path)).ok()).toBe(true);
    expect(sent.map(item => item.method)).toEqual(['DELETE']);
  });
}
