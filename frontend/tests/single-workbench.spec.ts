import type { APIRequestContext, Page } from '@playwright/test';
import { expect, learningGoal, test } from './fixtures';

async function conversation(request: APIRequestContext, goal: string) {
  const session = crypto.randomUUID();
  expect((await request.post('/api/conversations', { data: { session_id: session, goal_id: goal, node_id: 'n', title: '保留原会话' } })).ok()).toBe(true);
  return session;
}
function writes(page: Page) {
  const result: string[] = [];
  page.on('request', request => { if (!['GET', 'HEAD'].includes(request.method())) result.push(request.method() + ' ' + new URL(request.url()).pathname); });
  return result;
}

test('single workbench: old bookmarks resolve read-only without creating replacement goals or sessions', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const sent = writes(page);
  for (const [path, tool] of [[`/goals/${goal}/plan`, ''], [`/goals/${goal}/plan?mode=manual`, 'graph'], [`/goals/${goal}/learn`, ''], ['/library', ''], ['/documents', 'documents']] as const) {
    await page.goto(path);
    await expect(page.locator('.workbench')).toBeVisible();
    await expect.poll(() => new URL(page.url()).pathname).toBe('/');
    expect(new URL(page.url()).searchParams.get('tool') || '').toBe(tool);
  }
  expect(sent).toEqual([]);
});

test('single workbench: a legacy learning bookmark restores its saved history without a new teaching run', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const session = `learn:${goal}:n`;
  const run = await (await request.post(`/api/sessions/${session}/runs`, { data: { request_id: crypto.randomUUID(), goal_id: goal, node_id: 'n', mode: 'runner', user_text: '原页面保存的历史问题' } })).json();
  await expect.poll(async () => (await (await request.get(`/api/runs/${run.run_id}`)).json()).status).toBe('completed');
  await page.goto('/');
  await page.evaluate(goal => localStorage.setItem(`learngraph:node:${goal}`, 'n'), goal);
  const sent = writes(page);
  await page.goto(`/goals/${goal}/learn`);
  await expect(page.getByLabel('当前会话记录')).toContainText('原页面保存的历史问题');
  expect(new URL(page.url()).searchParams.get('session')).toBe(session);
  expect(sent).toEqual([]);
});

test('single workbench: document source scope, browser history and return preserve the original conversation', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const other = await learningGoal(request);
  const session = await conversation(request, goal);
  const name = `工作台资料-${crypto.randomUUID()}.md`;
  const document = await (await request.post('/api/documents', { multipart: { file: { name, mimeType: 'text/markdown', buffer: Buffer.from('# 工作台原文\n资料范围不是聊天范围。') } } })).json();
  await expect.poll(async () => (await (await request.get(`/api/documents/${document.document_id}`)).json()).status).toBe('ready');
  const sent = writes(page);
  await page.goto(`/?goal=${goal}&session=${session}`);
  await expect(page.getByLabel('向当前节点提问')).toBeEnabled();
  await page.getByRole('link', { name: '我的资料', exact: true }).click();
  await page.getByRole('link', { name, exact: true }).click();
  await expect(page.getByRole('region', { name: '资料原文' })).toContainText('资料范围不是聊天范围');
  await page.getByLabel('绑定目标').selectOption(other);
  await expect.poll(() => new URL(page.url()).searchParams.get('source_goal')).toBe(other);
  expect(new URL(page.url()).searchParams.get('goal')).toBe(goal);
  expect(new URL(page.url()).searchParams.get('session')).toBe(session);
  await page.goBack();
  await expect(page.getByRole('region', { name: '资料原文' })).toBeVisible();
  await page.goForward();
  await expect(page.getByLabel('绑定目标')).toHaveValue(other);
  await page.reload();
  await expect(page.getByLabel('绑定目标')).toHaveValue(other);
  await page.getByLabel('绑定目标', { exact: true }).selectOption('');
  await page.getByRole('link', { name: '返回资料列表', exact: true }).click();
  await expect(page.getByRole('region', { name: '资料管理', exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get('source_goal')).toBe('');
  await expect(page.getByRole('region', { name: '目标资料绑定', exact: true })).toHaveCount(0);
  await expect(page.getByRole('region', { name: '节点资料绑定', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '返回对话与学习', exact: true }).click();
  await expect(page.getByLabel('向当前节点提问')).toBeEnabled();
  expect(new URL(page.url()).searchParams.get('session')).toBe(session);
  expect(sent).toEqual([]);
});

test('single workbench: deterministic recommendation browses without creating a conversation or calling a model', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const session = await conversation(request, goal);
  const sent = writes(page);
  await page.goto(`/?goal=${goal}&session=${session}`);
  await page.getByRole('tab', { name: '学习内容', exact: true }).click();
  const recommendation = page.getByRole('region', { name: '下一步建议' });
  await expect(recommendation).toContainText('错误与恢复');
  await recommendation.getByRole('button', { name: '查看推荐节点' }).click();
  await expect(page.getByRole('region', { name: '所查看节点' })).toContainText('错误与恢复');
  expect(new URL(page.url()).searchParams.get('session')).toBe(session);
  expect(sent).toEqual([]);
});

test('single workbench: proficient practice uses readable wording and an all-complete next step', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const session = await conversation(request, goal);
  const run = await (await request.post(`/api/goals/${goal}/nodes/n/exercises`, { data: { session_id: session, request_id: crypto.randomUUID(), count: 3, purpose: 'practice' } })).json();
  await expect.poll(async () => (await (await request.get(`/api/runs/${run.run_id}`)).json()).status).toBe('completed');
  const questions = await (await request.get(`/api/goals/${goal}/nodes/n/exercises`)).json();
  for (const question of questions.exercises) expect((await request.post(`/api/goals/${goal}/exercises/${question.id}/attempts`, { data: { submission_id: crypto.randomUUID(), selected_option_id: 'b' } })).ok()).toBe(true);
  await page.goto(`/?goal=${goal}&session=${session}`);
  const sent = writes(page);
  await page.getByRole('tab', { name: '学习内容', exact: true }).click();
  await expect(page.locator('.progress-card')).toContainText('已达练习熟练标准');
  await expect(page.getByRole('region', { name: '下一步建议' })).toContainText('综合实践或结束');
  await page.reload();
  await expect(page.locator('.progress-card')).toContainText('已达练习熟练标准');
  expect(sent).toEqual([]);
});

test('single workbench: unsaved advanced edits guard tool navigation and keep draft when leaving is cancelled', async ({ page, request }) => {
  const goal = await learningGoal(request, 'n', false);
  await page.goto(`/?goal=${goal}`);
  await page.getByRole('button', { name: '图谱管理', exact: true }).click();
  await page.getByText('图谱与节点编辑', { exact: true }).click();
  await page.getByLabel('节点标题', { exact: true }).fill('尚未保存的新标题');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('link', { name: '我的资料', exact: true }).click();
  expect(new URL(page.url()).searchParams.get('tool')).toBe('graph');
  await expect(page.getByLabel('节点标题', { exact: true })).toHaveValue('尚未保存的新标题');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('link', { name: '我的资料', exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('tool')).toBe('documents');
  await page.goBack();
  await page.getByText('图谱与节点编辑', { exact: true }).click();
  await page.getByLabel('节点标题', { exact: true }).fill('第二次未保存');
  page.once('dialog', dialog => dialog.dismiss());
  await page.goBack();
  await expect.poll(() => new URL(page.url()).searchParams.get('tool')).toBe('graph');
  await expect(page.getByLabel('节点标题', { exact: true })).toHaveValue('第二次未保存');
  page.once('dialog', dialog => dialog.accept());
  await page.goBack();
  await expect.poll(() => new URL(page.url()).searchParams.get('tool')).toBeNull();
  await page.goForward();
  await expect.poll(() => new URL(page.url()).searchParams.get('tool')).toBe('graph');
  await page.goBack();
  await expect.poll(() => new URL(page.url()).searchParams.get('tool')).toBeNull();
});

test('single workbench: uploading and target binding refresh sibling node scope without manual refresh', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const session = await conversation(request, goal);
  await page.goto(`/?goal=${goal}&session=${session}`);
  await page.getByRole('button', { name: '当前节点资料', exact: true }).click();
  const name = `联动资料-${crypto.randomUUID()}.md`;
  await page.getByLabel('选择资料文件').setInputFiles({ name, mimeType: 'text/markdown', buffer: Buffer.from('# 联动\n先目标，再显式节点。') });
  await page.getByRole('button', { name: '上传资料', exact: true }).click();
  const parent = page.getByRole('region', { name: '目标资料绑定', exact: true });
  const node = page.getByRole('region', { name: '节点资料绑定', exact: true });
  await expect(parent.getByRole('option', { name, exact: true })).toBeEnabled();
  await parent.getByLabel('选择要绑定的资料', { exact: true }).selectOption({ label: name });
  await parent.getByRole('button', { name: '绑定所选资料', exact: true }).click();
  await expect(node.getByRole('option', { name, exact: true })).toBeEnabled();
  await node.getByLabel('选择要绑定的资料', { exact: true }).selectOption({ label: name });
  await node.getByRole('button', { name: '绑定所选资料', exact: true }).click();
  await expect(node.getByRole('link', { name, exact: true })).toBeVisible();
  const target = await parent.getByRole('link', { name, exact: true }).getAttribute('href');
  const id = new URL(target!, page.url()).searchParams.get('document')!;
  await page.goto(`/?goal=${goal}&session=${session}&tool=document&document=${id}`);
  await page.locator('.doc-associations li').filter({ hasText: '节点：错误与恢复' }).getByRole('link').click();
  await expect(page.getByRole('region', { name: '所查看节点' })).toContainText('错误与恢复');
  expect(new URL(page.url()).searchParams.get('session')).toBe(session);
  await page.reload();
  await expect(page.getByRole('region', { name: '所查看节点' })).toContainText('错误与恢复');
});

test('single workbench: late document deletion never takes over a later conversation navigation', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const name = `待删除-${crypto.randomUUID()}.md`;
  const document = await (await request.post('/api/documents', { multipart: { file: { name, mimeType: 'text/markdown', buffer: Buffer.from('# 删除\n迟到响应。') } } })).json();
  await expect.poll(async () => (await (await request.get(`/api/documents/${document.document_id}`)).json()).status).toBe('ready');
  let release!: () => void, deleted!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const committed = new Promise<void>(resolve => { deleted = resolve; });
  await page.route(`**/api/documents/${document.document_id}`, async route => {
    if (route.request().method() !== 'DELETE') return route.continue();
    const response = await route.fetch(); deleted(); await gate; await route.fulfill({ response });
  });
  await page.goto(`/?goal=${goal}&tool=document&document=${document.document_id}`);
  await expect(page.getByRole('region', { name: '资料原文' })).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  const response = page.waitForResponse(r => r.request().method() === 'DELETE');
  await page.getByRole('button', { name: '删除资料', exact: true }).click();
  await committed;
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  const destination = page.url(); release(); await response;
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  expect(page.url()).toBe(destination);
  await expect(page.getByRole('heading', { name: '想探索什么知识？', exact: true })).toBeVisible();
});

test('single workbench: tools remain inside responsive workspace without reload writes', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const sent = writes(page);
  for (const tool of ['documents', 'graph']) {
    await page.goto(`/?goal=${goal}&tool=${tool}`);
    for (const width of [375, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(page.locator('.wb-main')).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    }
    await page.reload();
    await expect(page.locator('.workbench')).toBeVisible();
  }
  expect(sent).toEqual([]);
});
