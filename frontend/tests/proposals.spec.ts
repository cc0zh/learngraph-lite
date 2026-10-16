import { openLearning, learningContent, expect, learningGoal, test } from './fixtures';

test('P1: proposal generation failure uses explicit linked retry (mock model DTOs)', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const bodies: Record<string, unknown>[] = [];
  await page.route(`**/api/goals/${goal}/graph-proposals/generate`, async route => {
    const body = route.request().postDataJSON(); bodies.push(body);
    await route.fulfill({ status: 202, json: { run_id: bodies.length === 1 ? 'mock-proposal-failed' : 'mock-proposal-retried',
      status: bodies.length === 1 ? 'failed' : 'completed', mode: 'proposal', user_text: '', partial_text: '',
      final_text: bodies.length === 1 ? '' : '模拟模型重试已完成', error: bodies.length === 1 ? '模拟提案模型失败' : null,
      created_at: new Date().toISOString(), tool_activity: {} } });
  });
  await openLearning(page, request, goal);
  await page.getByRole('button', { name: '图谱管理', exact: true }).click();
  const panel = page.getByRole('region', { name: '路线调整提案' });
  await panel.getByRole('button', { name: '让 Agent 生成调整提案' }).click();
  await expect(panel).toContainText('模拟提案模型失败');
  await panel.getByRole('button', { name: '重试', exact: true }).click();
  await expect(panel).toContainText('模拟模型重试已完成');
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toEqual({ ...bodies[0], request_id: bodies[1].request_id, retry_of_run_id: 'mock-proposal-failed' });
  expect(bodies[1].request_id).not.toBe(bodies[0].request_id);
});

test('P1: lost accept response reconciles the published graph and status without a second decision', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const plan = await (await request.get(`/api/goals/${goal}`)).json();
  const made = await request.post(`/api/goals/${goal}/graph-proposals`, { data: { request_id: crypto.randomUUID(),
    base_revision: plan.graph.revision, rationale: '验证审核响应丢失恢复',
    operations: [{ kind: 'update_node', node_id: 'n', title: '响应丢失后的新路线' }] } });
  expect(made.status()).toBe(201);
  const proposal = await made.json();
  let decisions = 0;
  await page.route(`**/api/goals/${goal}/graph-proposals/${proposal.id}/decision`, async route => {
    decisions++; expect((await route.fetch()).status()).toBe(200); await route.abort('failed');
  });
  await openLearning(page, request, goal);
  await page.getByRole('button', { name: '图谱管理', exact: true }).click();
  const panel = page.getByRole('region', { name: '路线调整提案' });
  page.once('dialog', dialog => dialog.accept());
  await panel.getByRole('button', { name: '接受提案并发布' }).click();
  await expect(panel.getByRole('heading', { name: '已接受', exact: true })).toBeVisible();
  await expect(page.getByRole('list', { name: '图谱知识节点', exact: true })).toContainText('响应丢失后的新路线');
  await panel.getByRole('button', { name: '刷新提案与状态' }).click();
  await expect(page.getByRole('list', { name: '图谱知识节点', exact: true })).toContainText('响应丢失后的新路线');
  expect(decisions).toBe(1);
});

test('P1: generated proposal stays pending, accepts atomically, preserves read-only history and reloads without writes', async ({ page, request }) => {
  const goal = await learningGoal(request);
  await openLearning(page, request, goal);
  await learningContent(page);
  await page.getByRole('button', { name: '生成练习', exact: true }).click();
  await expect(page.getByRole('radio')).toHaveCount(3);
  await page.getByRole('radio', { name: '解释原理并完成一个例子' }).check();
  await page.getByRole('button', { name: '提交答案' }).click();
  await expect(page.locator('.progress-card')).toContainText('1 个有效样本');
  await page.getByText('选择已有题目加入学习包', { exact: false }).click();
  await page.getByLabel('加入题目 1').check();
  await page.getByRole('button', { name: '生成学习包', exact: true }).click();
  await expect(page.getByRole('article', { name: '学习包详情' })).toBeVisible();
  const before = await (await request.get(`/api/goals/${goal}`)).json();
  await page.getByRole('button', { name: '图谱管理', exact: true }).click();
  const panel = page.getByRole('region', { name: '路线调整提案' });
  await panel.getByRole('button', { name: '让 Agent 生成调整提案' }).click();
  await expect(panel.getByRole('heading', { name: '待审核', exact: true })).toBeVisible();
  const pending = await (await request.get(`/api/goals/${goal}/graph-proposals`)).json();
  expect(pending.proposals).toHaveLength(1);
  expect((await (await request.get(`/api/goals/${goal}`)).json()).graph).toEqual(before.graph);
  expect((await (await request.get(`/api/goals/${goal}/nodes/n/context`)).json()).node.sample_count).toBe(1);
  page.once('dialog', dialog => dialog.accept());
  await panel.getByRole('button', { name: '接受提案并发布' }).click();
  await expect(panel.getByRole('heading', { name: '已接受', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '返回工作台浏览节点', exact: true }).click();
  await learningContent(page);
  await expect(page.locator('.progress-card')).toContainText('0 个有效样本');
  await expect(page.getByRole('article', { name: '学习包详情' })).toContainText('内容版本已过期');
  await expect(page.getByRole('article', { name: '学习包详情' }).getByRole('button', { name: '提交答案' })).toBeDisabled();
  const after = await (await request.get(`/api/goals/${goal}`)).json();
  expect(after.graph.revision).toBe(before.graph.revision + 1);
  expect(after.graph.content_revision).toBe(before.graph.content_revision + 1);
  const writes: string[] = [];
  page.on('request', r => { if (!['GET', 'HEAD'].includes(r.method())) writes.push(r.method()); });
  await page.reload();
  await expect(page.getByRole('article', { name: '学习包详情' })).toContainText('内容版本已过期');
  await page.getByRole('button', { name: '图谱管理', exact: true }).click();
  await expect(panel.getByRole('heading', { name: '已接受', exact: true })).toBeVisible();
  expect(writes).toEqual([]);
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
});

test('P1: teaching tool creates reviewable proposal; rejection does not change graph or scores', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const before = await (await request.get(`/api/goals/${goal}`)).json();
  await openLearning(page, request, goal);
  await page.getByLabel('向当前节点提问').fill('这部分有点难，能帮我调整路线吗？');
  await page.getByRole('button', { name: '发送问题' }).click();
  await expect(page.locator('.wb-conversation > .run-status')).toContainText('提出图谱调整建议');
  await page.getByRole('button', { name: '图谱管理', exact: true }).click();
  const panel = page.getByRole('region', { name: '路线调整提案' });
  await expect(panel.getByRole('heading', { name: '待审核', exact: true })).toBeVisible();
  await panel.getByRole('button', { name: '拒绝提案' }).click();
  await expect(panel.getByRole('heading', { name: '已拒绝', exact: true })).toBeVisible();
  expect((await (await request.get(`/api/goals/${goal}`)).json()).graph).toEqual(before.graph);
  expect((await (await request.get(`/api/goals/${goal}/nodes/n/context`)).json()).node.sample_count).toBe(0);
  expect((await (await request.get(`/api/goals/${goal}/graph-proposals`)).json()).proposals[0].status).toBe('rejected');
});

test('P1: stale pending proposal persists conflicted rather than overwriting a newer published graph', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const plan = await (await request.get(`/api/goals/${goal}`)).json();
  const proposals: string[] = [];
  for (const priority of [4, 5]) {
    const result = await request.post(`/api/goals/${goal}/graph-proposals`, { data: {
      request_id: `priority-${priority}`, base_revision: plan.graph.revision,
      rationale: `计划优先级调整 ${priority}`, operations: [{ kind: 'update_node', node_id: 'n', priority }],
    } });
    expect(result.status()).toBe(201); proposals.push((await result.json()).id);
  }
  await openLearning(page, request, goal);
  await page.getByRole('button', { name: '图谱管理', exact: true }).click();
  const first = page.getByRole('article', { name: `提案 ${proposals[0]}`, exact: true });
  page.once('dialog', dialog => dialog.accept());
  await first.getByRole('button', { name: '接受提案并发布' }).click();
  await expect(first).toContainText('已接受');
  const second = page.getByRole('article', { name: `提案 ${proposals[1]}`, exact: true });
  await expect(second).toContainText('基础版本已过期');
  page.once('dialog', dialog => dialog.accept());
  await second.getByRole('button', { name: '接受提案并发布' }).click();
  await expect(second).toContainText('版本冲突');
  const latest = await (await request.get(`/api/goals/${goal}`)).json();
  expect(latest.graph.nodes[0].priority).toBe(4);
  expect(latest.graph.revision).toBe(plan.graph.revision + 1);
  expect(latest.graph.content_revision).toBe(plan.graph.content_revision);
  await page.reload();
  await expect(second).toContainText('版本冲突');
});
