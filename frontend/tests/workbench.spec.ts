import type { APIRequestContext, Page } from '@playwright/test';
import { expect, test } from './fixtures';

const intent = '学习 RAG，成果：完成一个本地检索小实践，基础：会 Python，总投入120分钟';
function posts(page: Page) {
  const sent: { path: string; body: Record<string, unknown> }[] = [];
  page.on('request', request => { if (request.method() === 'POST') sent.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() }); });
  return sent;
}
async function graph(request: APIRequestContext, name = '工作台范围测试') {
  const initial = await (await request.post('/api/goals', { data: { title: name } })).json();
  const confirmed = await (await request.post(`/api/goals/${initial.goal_id}/confirm`, { data: { expected_version: initial.version } })).json();
  const draft = await (await request.patch(`/api/goals/${initial.goal_id}/graph`, { data: { expected_version: confirmed.version,
    nodes: [
      { id: 'one', title: '文档分块', explanation: '理解分块粒度与上下文', learning_outcome: '比较两种分块方式', estimated_minutes: 20, priority: 3 },
      { id: 'two', title: '向量检索', explanation: '理解检索与相似度', learning_outcome: '解释检索过程', estimated_minutes: 20, priority: 2 },
    ], edges: [{ source: 'one', target: 'two', kind: 'prerequisite' }] } })).json();
  expect((await request.post(`/api/goals/${initial.goal_id}/graph/publish`, { data: { expected_version: draft.version, expected_revision: draft.graph.revision } })).ok()).toBe(true);
  return initial.goal_id as string;
}
async function startNode(page: Page, title = '文档分块') {
  const previous = new URL(page.url()).searchParams.get('session');
  await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button', { name: title }).click();
  await page.getByRole('button', { name: '开始学习此节点', exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('session')).not.toBe(previous);
  await expect(page.getByLabel('向当前节点提问')).toBeEnabled();
  await expect(page.getByLabel('当前会话记录')).toContainText('学习助手');
  await expect(page.locator('.wb-conversation > .run-status > strong')).toHaveText('已完成');
  return new URL(page.url()).searchParams.get('session')!;
}

test('workbench: explicit goal mode, embedded review, publish and node-started conversation', async ({ page }) => {
  const sent = posts(page);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', { name: '创建目标', exact: true }).click();
  await expect(page.getByRole('region', { name: '创建目标', exact: true })).toBeVisible();
  expect(sent).toHaveLength(0);
  await page.getByLabel('描述学习目标').fill(intent);
  await page.getByRole('button', { name: '发送并创建目标', exact: true }).click();
  await expect(page.getByRole('region', { name: '目标审核', exact: true })).toBeVisible();
  const goal = new URL(page.url()).searchParams.get('goal')!;
  expect(new URL(page.url()).pathname).toBe('/');
  expect(sent.filter(item => item.path === '/api/workbench/goals')).toHaveLength(1);
  await page.getByRole('button', { name: '确认目标并生成图谱', exact: true }).click();
  const review = page.getByRole('region', { name: '路线审核', exact: true });
  await expect(review).toBeVisible();
  const count = sent.length;
  await page.reload();
  await expect(review).toBeVisible();
  expect(sent).toHaveLength(count);
  await review.getByRole('button', { name: '确认并发布路线', exact: true }).click();
  await expect(page.getByRole('complementary', { name: '图谱与节点', exact: true })).toContainText('已发布');
  await expect(page.getByLabel('和 Agent 讨论目标与路线')).toHaveCount(0);
  const beforeView = sent.length;
  await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button').first().click();
  await expect(page.getByRole('region', { name: '所查看节点' })).toBeVisible();
  expect(sent).toHaveLength(beforeView);
  await page.getByRole('button', { name: '开始学习此节点', exact: true }).click();
  await expect(page.getByLabel('向当前节点提问')).toBeEnabled();
  await expect(page.getByLabel('当前对话范围')).toContainText('节点学习');
  const session = new URL(page.url()).searchParams.get('session')!;
  expect(session).not.toBe(`planning:${goal}`);
  await expect(page.getByLabel('当前会话记录')).toContainText('fixture 示例讲解');
  expect(errors).toEqual([]);
});

test('workbench: viewing is separate from focus; independent histories and drafts share node artifacts', async ({ page, request }) => {
  const goal = await graph(request);
  const sent = posts(page);
  await page.goto(`/?goal=${goal}`);
  const first = await startNode(page);
  await page.getByLabel('向当前节点提问').fill('只属于第一次会话的问题');
  await page.getByRole('button', { name: '发送问题', exact: true }).click();
  await expect(page.getByLabel('当前会话记录')).toContainText('只属于第一次会话的问题');
  await expect(page.getByRole('button', { name: '发送问题', exact: true })).toBeDisabled();
  await page.getByLabel('向当前节点提问').fill('第一次会话的未发送草稿');
  await expect(page.getByRole('button', { name: '发送问题', exact: true })).toBeEnabled();
  const beforeBrowse = sent.length;
  await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button', { name: '向量检索' }).click();
  await expect(page.getByRole('region', { name: '所查看节点' })).toContainText('向量检索');
  await expect(page.getByLabel('当前对话范围')).toContainText('节点：文档分块');
  expect(new URL(page.url()).searchParams.get('session')).toBe(first);
  expect(sent).toHaveLength(beforeBrowse);
  await page.getByRole('tab', { name: '学习内容', exact: true }).click();
  await page.getByRole('button', { name: '生成练习', exact: true }).click();
  await expect(page.getByRole('region', { name: '节点已有练习' }).getByRole('radio')).toHaveCount(3);
  await page.getByRole('button', { name: '生成学习包', exact: true }).click();
  await expect(page.getByRole('article', { name: '学习包详情' })).toBeVisible();
  const second = await startNode(page);
  expect(second).not.toBe(first);
  await expect(page.getByLabel('当前会话记录')).not.toContainText('只属于第一次会话的问题');
  await expect(page.getByLabel('向当前节点提问')).toHaveValue('');
  await page.getByRole('tab', { name: '学习内容', exact: true }).click();
  await expect(page.getByRole('region', { name: '节点已有练习' }).getByRole('radio')).toHaveCount(3);
  await expect(page.getByRole('article', { name: '学习包详情' })).toBeVisible();
  const count = sent.length;
  await page.goto(`/?goal=${goal}&session=${first}`);
  await expect(page.getByLabel('向当前节点提问')).toHaveValue('第一次会话的未发送草稿');
  await page.getByRole('tab', { name: '对话', exact: true }).click();
  await expect(page.getByLabel('当前会话记录')).toContainText('只属于第一次会话的问题');
  await page.reload();
  await expect(page.getByLabel('向当前节点提问')).toHaveValue('第一次会话的未发送草稿');
  expect(sent).toHaveLength(count);
  const a = await (await request.get(`/api/sessions/${first}/runs`)).json();
  const b = await (await request.get(`/api/sessions/${second}/runs`)).json();
  expect(a.some((run: { user_text: string }) => run.user_text === '只属于第一次会话的问题')).toBe(true);
  expect(b.some((run: { user_text: string }) => run.user_text === '只属于第一次会话的问题')).toBe(false);
});

test('workbench: metadata response loss preserves identity; refresh and mode changes never generate', async ({ page, request }) => {
  const goal = await graph(request, '创建响应丢失');
  let lost = true;
  await page.route('**/api/conversations', async route => {
    if (route.request().method() !== 'POST' || !lost) { await route.continue(); return; }
    lost = false; await route.fetch(); await route.abort('failed');
  });
  const sent = posts(page);
  await page.goto(`/?goal=${goal}`);
  await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button', { name: '文档分块' }).click();
  await page.getByRole('button', { name: '开始学习此节点', exact: true }).click();
  await expect(page.getByRole('region', { name: '创建恢复' })).toBeVisible();
  const original = sent.find(item => item.path === '/api/conversations')!;
  const count = sent.length;
  await page.reload();
  await expect(page.getByRole('button', { name: '继续本次创建' })).toBeVisible();
  expect(sent).toHaveLength(count);
  await page.getByRole('button', { name: '继续本次创建' }).click();
  await expect(page.getByLabel('向当前节点提问')).toBeEnabled();
  expect(sent.filter(item => item.path === '/api/conversations').map(item => item.body.session_id)).toEqual([original.body.session_id, original.body.session_id]);
  expect(sent.filter(item => item.path.endsWith('/runs'))).toHaveLength(1);
  expect((await (await request.get('/api/conversations')).json()).filter((item: { session_id: string }) => item.session_id === original.body.session_id)).toHaveLength(1);
});

test('workbench: old runner sessions restore read-only and explicitly continue using the original mode', async ({ page, request }) => {
  const goal = await graph(request, '旧学习记录');
  const session = `learn:${goal}:one`;
  const response = await request.post(`/api/sessions/${session}/runs`, { data: { request_id: crypto.randomUUID(), user_text: '来自旧页面的学习问题', goal_id: goal, node_id: 'one', mode: 'runner' } });
  expect(response.ok()).toBe(true);
  const run = await response.json();
  await expect.poll(async () => (await (await request.get(`/api/runs/${run.run_id}`)).json()).status).toBe('completed');
  const sent = posts(page);
  await page.goto(`/?goal=${goal}&session=${session}`);
  await expect(page.getByLabel('当前会话记录')).toContainText('来自旧页面的学习问题');
  expect(sent).toHaveLength(0);
  await page.getByLabel('向当前节点提问').fill('延续旧的只读上下文');
  await page.getByRole('button', { name: '发送问题', exact: true }).click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0].body.mode).toBe('runner');
  await expect(page.locator('.wb-conversation > .run-status > strong')).toHaveText('已完成');
});

test('workbench: inline explanation stays with its source and is isolated across conversations', async ({ page, request }) => {
  const goal = await graph(request, '解释来源与会话');
  await page.goto(`/?goal=${goal}`);
  const first = await startNode(page);
  await page.getByRole('tab', { name: '学习内容', exact: true }).click();
  await page.getByRole('button', { name: '生成学习包', exact: true }).click();
  const chapter = page.getByRole('region', { name: '学习包章节', exact: true });
  await chapter.getByRole('button', { name: '让 Agent 解释', exact: true }).click();
  await expect(chapter.getByRole('article', { name: '组件解释' })).toContainText('fixture');
  await expect(chapter.getByRole('article', { name: '组件解释' })).toContainText('已完成');
  await expect(page.getByRole('region', { name: '学习包解释记录' })).toHaveCount(0);
  const second = await startNode(page);
  expect(second).not.toBe(first);
  await page.getByRole('tab', { name: '学习内容', exact: true }).click();
  await expect(chapter.getByRole('button', { name: '让 Agent 解释', exact: true })).toBeEnabled();
  await expect(chapter).not.toContainText('slot：');
  const sent = posts(page);
  await chapter.getByRole('button', { name: '让 Agent 解释', exact: true }).click();
  await expect(chapter.getByRole('article', { name: '组件解释' })).toContainText('fixture');
  await expect(chapter.getByRole('article', { name: '组件解释' })).toContainText('已完成');
  const count = sent.length;
  await page.reload();
  await expect(chapter.getByRole('article', { name: '组件解释' })).toContainText('fixture');
  expect(sent).toHaveLength(count);
});

test('workbench: narrow screens expose all three regions without horizontal overflow or writes', async ({ page, request }) => {
  const goal = await graph(request, '窄屏工作台');
  const sent = posts(page);
  await page.goto(`/?goal=${goal}`);
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    if (width <= 860) {
      const nav = page.getByRole('navigation', { name: '工作台区域' });
      await nav.getByRole('button', { name: '图谱与节点', exact: true }).click();
      await expect(page.getByRole('complementary', { name: '图谱与节点', exact: true })).toBeVisible();
      await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button', { name: '向量检索' }).click();
      await expect(page.getByRole('region', { name: '所查看节点' })).toContainText('向量检索');
      await nav.getByRole('button', { name: '学习空间', exact: true }).click();
      await expect(page.getByRole('complementary', { name: '学习空间', exact: true })).toBeVisible();
      await nav.getByRole('button', { name: '对话与内容', exact: true }).click();
    }
  }
  expect(sent).toHaveLength(0);
});

test('workbench: goal creation response loss resumes the original goal and authorizes only one initial run', async ({ page, request }) => {
  let lose = true;
  await page.route('**/api/workbench/goals', async route => {
    if (!lose) { await route.continue(); return; }
    lose = false; await route.fetch(); await route.abort('failed');
  });
  const sent = posts(page);
  await page.goto('/?mode=goal');
  await page.getByLabel('描述学习目标').fill(intent);
  await page.getByRole('button', { name: '发送并创建目标' }).click();
  await expect(page.getByRole('region', { name: '创建恢复' })).toBeVisible();
  await expect(page.getByRole('button', { name: '继续本次创建' })).toBeEnabled();
  const id = sent.find(item => item.path === '/api/workbench/goals')!.body.goal_id;
  expect((await request.get(`/api/goals/${id}`)).ok()).toBe(true);
  const count = sent.length;
  await page.reload();
  await expect(page.getByLabel('描述学习目标')).toHaveValue(intent);
  expect(sent).toHaveLength(count);
  await page.goto(`/?goal=${id}&session=planning:${id}`);
  await expect(page.getByRole('button', { name: '继续本次创建' })).toBeVisible();
  await expect(page.getByRole('button', { name: '让 Agent 开始规划' })).toHaveCount(0);
  expect(sent).toHaveLength(count);
  await page.getByRole('button', { name: '继续本次创建' }).click();
  await expect(page.getByRole('region', { name: '目标审核', exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get('goal')).toBe(id);
  expect(sent.filter(item => item.path === '/api/workbench/goals').map(item => item.body.goal_id)).toEqual([id, id]);
  expect(sent.filter(item => item.path.endsWith('/planning-runs'))).toHaveLength(1);
});

test('workbench: lost first teaching response recovers the identical request after read-only reload', async ({ page, request }) => {
  const goal = await graph(request, '首轮响应恢复');
  let lose = true;
  await page.route('**/api/sessions/*/runs', async route => {
    if (route.request().method() !== 'POST' || !lose) { await route.continue(); return; }
    lose = false; await route.fetch(); await route.abort('failed');
  });
  const sent = posts(page);
  await page.goto(`/?goal=${goal}`);
  await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button', { name: '文档分块' }).click();
  await page.getByRole('button', { name: '开始学习此节点', exact: true }).click();
  const pending = page.getByRole('region', { name: '未确认请求恢复' });
  await expect(pending).toBeVisible();
  const command = sent.find(item => item.path.endsWith('/runs'))!;
  const count = sent.length;
  await page.reload();
  await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeEnabled();
  expect(sent).toHaveLength(count);
  await pending.getByRole('button', { name: '重发未确认请求' }).click();
  await expect(pending).toHaveCount(0);
  const commands = sent.filter(item => item.path.endsWith('/runs'));
  expect(commands).toEqual([command, command]);
  expect((await (await request.get(command.path)).json())).toHaveLength(1);
});

test('workbench: repeated 429s preserve the first teaching command until explicit same-ID recovery succeeds', async ({ page, request }) => {
  const goal = await graph(request, '首轮限流恢复');
  let attempts = 0;
  await page.route('**/api/sessions/*/runs', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    attempts += 1;
    if (attempts <= 2) await route.fulfill({ status: 429, json: { detail: { message: 'fixture rate limit' } } });
    else await route.continue();
  });
  const sent = posts(page);
  await page.goto(`/?goal=${goal}`);
  await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button', { name: '文档分块' }).click();
  await page.getByRole('button', { name: '开始学习此节点', exact: true }).click();
  const pending = page.getByRole('region', { name: '未确认请求恢复' });
  const resend = pending.getByRole('button', { name: '重发未确认请求' });
  await expect(resend).toBeEnabled();
  const command = sent.find(item => item.path.endsWith('/runs'))!;
  const session = new URL(page.url()).searchParams.get('session')!;
  const key = `learngraph:command:${session}:pending`;
  const savedCommand = { ...command, path: command.path.replace(/^\/api/, '') };
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), key)).toEqual(savedCommand);
  expect(await (await request.get(command.path)).json()).toHaveLength(0);
  const count = sent.length;
  await page.reload();
  await expect(resend).toBeEnabled();
  expect(sent).toHaveLength(count);
  await resend.click();
  await expect(page.getByRole('alert')).toContainText('请求未确认');
  await expect(resend).toBeEnabled();
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), key)).toEqual(savedCommand);
  expect(await (await request.get(command.path)).json()).toHaveLength(0);
  expect(sent.filter(item => item.path.endsWith('/runs'))).toEqual([command, command]);
  const afterRecovery = sent.length;
  await page.reload();
  await expect(resend).toBeEnabled();
  expect(sent).toHaveLength(afterRecovery);
  await resend.click();
  await expect(pending).toHaveCount(0);
  await expect(page.locator('.wb-conversation > .run-status > strong')).toHaveText('已完成');
  expect(sent.filter(item => item.path.endsWith('/runs'))).toEqual([command, command, command]);
  expect(await (await request.get(command.path)).json()).toHaveLength(1);
  expect(await page.evaluate(key => localStorage.getItem(key), key)).toBeNull();
  const afterSuccess = sent.length;
  await page.reload();
  await expect(page.locator('.wb-conversation > .run-status > strong')).toHaveText('已完成');
  expect(sent).toHaveLength(afterSuccess);
});

test('workbench: a conflicting graph in the URL cannot silently change the saved conversation scope', async ({ page, request }) => {
  const one = await graph(request, '会话原图谱');
  const two = await graph(request, '无关图谱');
  const session = crypto.randomUUID();
  expect((await request.post('/api/conversations', { data: { session_id: session, goal_id: one, node_id: 'one', title: '范围固定' } })).ok()).toBe(true);
  const sent = posts(page);
  await page.goto(`/?goal=${two}&session=${session}`);
  await expect(page.getByRole('alert')).toContainText('图谱与会话范围不一致');
  await expect(page.getByLabel('向当前节点提问')).toHaveCount(0);
  await expect(page.getByLabel('当前对话范围')).toContainText('会话原图谱');
  expect(sent).toHaveLength(0);
});

test('workbench: a rejected initial run retains the full input as the saved conversation draft', async ({ page }) => {
  const input = '这是完整的普通对话输入。'.repeat(18);
  await page.route('**/api/sessions/*/runs', route => route.request().method() === 'POST'
    ? route.fulfill({ status: 422, json: { detail: { message: 'fixture initial rejection' } } }) : route.continue());
  await page.goto('/');
  await page.getByLabel('发送消息', { exact: true }).fill(input);
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.getByLabel('发送消息', { exact: true })).toHaveValue(input);
  await expect(page.getByText(/首次请求被拒绝/)).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('发送消息', { exact: true })).toHaveValue(input);
});

test('workbench: a late creation response never deletes a newer draft', async ({ page }) => {
  let arrived!: () => void;
  let release!: () => void;
  const seen = new Promise<void>(resolve => { arrived = resolve; });
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/conversations', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const response = await route.fetch(); arrived(); await gate; await route.fulfill({ response });
  });
  await page.goto('/');
  await page.getByLabel('发送消息', { exact: true }).fill('原来授权发送的问题');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await seen;
  await page.getByLabel('发送消息', { exact: true }).fill('响应等待期间的新草稿');
  release();
  await expect(page.getByLabel('当前会话记录')).toContainText('原来授权发送的问题');
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  await expect(page.getByLabel('发送消息', { exact: true })).toHaveValue('响应等待期间的新草稿');
});
