import { expect, test } from './fixtures';

test('P0: plan, publish, stream, answer, recover and stop/retry', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByText('Fixture · 示例模式')).toBeVisible();
  await page.getByLabel('你想学会什么？').fill(`P0 浏览器验收 ${Date.now()}`);
  await page.getByRole('button', { name: '开始规划' }).click();
  await expect(page.getByRole('heading', { name: '学习目标', level: 2 })).toBeVisible();
  await expect(page.getByRole('heading', { name: '希望学到什么程度？', level: 3 })).toBeVisible();
  await page.getByLabel('期望成果（也可以自己写）', { exact: true }).fill('能解释核心概念并完成一个最小例子');
  await page.getByRole('button', { name: '下一步', exact: true }).click();
  await page.getByLabel('已有基础（用户自述，未验证）', { exact: true }).fill('了解 Python');
  await page.getByRole('button', { name: '下一步', exact: true }).click();
  await page.getByLabel('可投入时间（总分钟）', { exact: true }).fill('120');
  await page.getByRole('button', { name: '下一步', exact: true }).click();
  await expect(page.getByRole('heading', { name: '目标摘要', level: 3 })).toBeVisible();
  await page.getByRole('button', { name: '确认目标摘要', exact: true }).click();
  await page.getByRole('button', { name: '生成路线草稿' }).click();
  await expect(page.getByRole('list', { name: '学习阶段', exact: true })).toBeVisible();
  await expect(page.getByLabel('节点标题')).not.toBeVisible();
  await page.getByText('高级：图谱与节点编辑', { exact: true }).click();
  await expect(page.getByLabel('节点标题')).toHaveValue('目标与边界');
  await page.getByLabel('节点标题').fill('边界与验收');
  await page.getByRole('button', { name: '保存路线修改' }).click();
  await expect(page.getByText('有未保存修改')).not.toBeVisible();
  await page.getByRole('button', { name: '审核完成，发布路线' }).click();
  await page.getByRole('link', { name: '进入学习' }).click();
  await expect(page.getByRole('heading', { name: '边界与验收' })).toBeVisible();
  await page.getByLabel('向当前节点提问').fill('用例子解释当前节点，并调用工具给我一道练习');
  await page.getByRole('button', { name: '发送问题' }).click();
  await expect(page.locator('.assistant-message')).toContainText('get_learning_context');
  await expect(page.locator('.assistant-message')).toContainText('create_exercise');
  await expect(page.locator('.assistant-message')).toContainText('这是 fixture');
  await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeEnabled();
  await expect(page.locator('.assistant-message')).toContainText('后续问题会结合本会话的完整回合。');
  await expect(page.getByRole('radio')).toHaveCount(3);
  await expect(page.locator('.progress-card')).toContainText('未开始');
  await page.getByRole('radio', { name: '解释原理并完成一个例子' }).check();
  await page.getByRole('button', { name: '提交答案' }).click();
  await expect(page.getByText('回答正确', { exact: true })).toBeVisible();
  await expect(page.locator('.progress-card')).toContainText('1 个有效样本');
  const posts: string[] = [];
  page.on('request', request => { if (request.method() === 'POST') posts.push(request.url()); });
  await page.reload();
  await expect(page.getByText('回答正确', { exact: true })).toBeVisible();
  await expect(page.locator('.assistant-message')).toContainText('后续问题会结合本会话的完整回合。');
  await expect(page.locator('.progress-card')).toContainText('1 个有效样本');
  expect(posts).toEqual([]);
  // The button remains a separate entry to the same generation use case.
  await page.getByRole('button', { name: '生成练习', exact: true }).click();
  await expect(page.getByRole('radio')).toHaveCount(6);
  await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeEnabled();
  await page.getByLabel('向当前节点提问').fill('再次解释，我将停止这次回答');
  await page.getByRole('button', { name: '发送问题' }).click();
  await expect(page.locator('.assistant-message').last()).toContainText('这是 fixture');
  await page.getByRole('button', { name: '停止', exact: true }).click();
  await expect(page.getByText('已停止', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.locator('.assistant-message').last()).toContainText('后续问题会结合本会话的完整回合。');
  await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeEnabled();
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    if (width === 375) {
      await page.getByRole('tab', { name: '练习与进度' }).click();
      await expect(page.getByText('回答正确', { exact: true })).toBeVisible();
      await page.getByRole('tab', { name: '节点对话' }).click();
    }
  }
  await page.screenshot({ path: 'test-results/p0-workspace.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('P0: model failure is visible and explicit retry preserves the teaching input', async ({ page, request }) => {
  // Real fixture business setup; only the failed/completed model run DTOs are mocked.
  const created = await request.post('/api/goals', { data: { title: '模型错误可见' } });
  const plan = await created.json();
  const goal = plan.goal_id;
  const confirmed = await (await request.post(`/api/goals/${goal}/confirm`, { data: { expected_version: plan.version } })).json();
  const drafted = await (await request.patch(`/api/goals/${goal}/graph`, { data: { expected_version: confirmed.version,
    nodes: [{ id: 'n', title: '错误与恢复', explanation: '识别失败', learning_outcome: '显式重试', estimated_minutes: 20, priority: 3 }], edges: [] } })).json();
  const published = await request.post(`/api/goals/${goal}/graph/publish`, { data: { expected_version: drafted.version, expected_revision: drafted.graph.revision } });
  expect(published.ok()).toBe(true);
  await page.goto(`/goals/${goal}/learn`);
  await expect(page.getByRole('heading', { name: '错误与恢复' })).toBeVisible();
  const submissions: Record<string, unknown>[] = [];
  await page.route('**/api/sessions/*/runs', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const input = route.request().postDataJSON();
    submissions.push(input);
    const failed = submissions.length === 1;
    await route.fulfill({ status: 202, json: { run_id: failed ? 'mock-failed' : 'mock-retry', mode: 'teaching',
      user_text: input.user_text, status: failed ? 'failed' : 'completed', created_at: new Date().toISOString(),
      partial_text: '', final_text: failed ? '' : '重试已完成（模拟模型结果）', tool_activity: {},
      error: failed ? '模拟模型连接失败' : null } });
  });
  await page.getByLabel('向当前节点提问').fill('解释失败恢复');
  await page.getByRole('button', { name: '发送问题' }).click();
  await expect(page.locator('.assistant-message')).toContainText('模拟模型连接失败');
  await expect(page.getByRole('button', { name: '重试', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.locator('.assistant-message').last()).toContainText('重试已完成');
  expect(submissions).toHaveLength(2);
  expect(submissions[0]).toMatchObject({ mode: 'teaching', goal_id: goal, node_id: 'n', user_text: '解释失败恢复' });
  expect(submissions[1]).toMatchObject({ ...submissions[0], request_id: submissions[1].request_id, retry_of_run_id: 'mock-failed' });
  expect(submissions[1].request_id).not.toBe(submissions[0].request_id);
});
