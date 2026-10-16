import { openLearning, learningContent, workbenchURL, expect, learningGoal, runDTO, test } from './fixtures';

for (const recovery of ['terminal-get-fails', 'terminal-found-by-query'] as const) {
  test(`P0: ${recovery} reconciles native-tool artifacts without another POST`, async ({ page, request }) => {
    const goal = await learningGoal(request);
    let runId = '';
    if (recovery === 'terminal-get-fails') {
      let failed = false;
      await page.route('**/api/runs/*', async route => {
        if (!failed) { failed = true; await route.abort('failed'); }
        else await route.continue();
      });
    } else {
      await page.route('**/api/runs/*/events', route => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }));
    }
    page.on('response', async response => {
      if (response.request().method() === 'POST' && response.url().includes('/sessions/') && response.status() === 202) runId = (await response.json()).run_id;
    });
    await openLearning(page, request, goal);
    await page.getByLabel('向当前节点提问').fill('请调用工具创建一道练习');
    await page.getByRole('button', { name: '发送问题' }).click();
    await expect.poll(() => runId).not.toBe('');
    await expect.poll(async () => (await (await request.get(`/api/runs/${runId}`)).json()).status).toBe('completed');
    const writes: string[] = [];
    page.on('request', req => { if (req.method() === 'POST') writes.push(req.url()); });
    if (recovery === 'terminal-get-fails') await expect(page.getByRole('alert').first()).toContainText('终态已收到');
    await page.getByRole('button', { name: '查询运行状态', exact: true }).click();
    await expect(page.locator('.assistant-message')).toContainText('后续问题会结合本会话');
    await learningContent(page);
    await expect(page.locator('.wb-exercises .exercise')).toHaveCount(1);
    await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeEnabled();
    expect(writes).toEqual([]);
  });
}

test('P0: Markdown never renders images or sends external image requests', async ({ page, request, externalRequests }) => {
  const goal = await learningGoal(request);
  const markdown = `正常 Markdown **仍然可读**。
![remote](https://untrusted.invalid/pixel?private=input)
![protocol relative](//untrusted.invalid/relative.png)
![reference][tracker]
[tracker]: https://untrusted.invalid/reference.png
<img src="https://untrusted.invalid/raw.png" onerror="alert('xss')">
[普通链接](https://untrusted.invalid/read)
\`<img src="https://untrusted.invalid/code.png">\``;
  await page.route('**/api/sessions/*/runs', route => route.fulfill({ json: [runDTO('safe-markdown', '测试图片', 'completed', markdown)] }));
  await page.route(`**/api/goals/${goal}/nodes/n/exercises`, route => route.fulfill({ json: { exercises: [
    { id: 'image-exercise', prompt: '练习正文 ![exercise](https://untrusted.invalid/exercise.png)', options: [] },
  ], feedback: {} } }));
  await openLearning(page, request, goal);
  await expect(page.locator('.assistant-message')).toContainText('仍然可读');
  await learningContent(page);
  await expect(page.locator('.exercise')).toContainText('练习正文');
  await expect(page.locator('.assistant-message a')).toHaveAttribute('href', 'https://untrusted.invalid/read');
  await expect(page.locator('.assistant-message img, .exercise img')).toHaveCount(0);
  expect(externalRequests).toEqual([]);
});

for (const failure of ['not-delivered', 'response-lost'] as const) {
  test(`P0: ${failure} keeps the latest command across reload and recovers once with the same ID`, async ({ page, request }) => {
    const goal = await learningGoal(request);
    const session = `learn:${goal}:n`;
    const path = `/sessions/${session}/runs`;
    const oldCommand = { path, body: { request_id: crypto.randomUUID(), user_text: '旧的已完成问题', goal_id: goal, node_id: 'n', mode: 'teaching' } };
    const oldResponse = await request.post(`/api${path}`, { data: oldCommand.body });
    expect(oldResponse.ok()).toBe(true);
    const oldRun = await oldResponse.json();
    await expect.poll(async () => (await (await request.get(`/api/runs/${oldRun.run_id}`)).json()).status).toBe('completed');
    await page.addInitScript(({ session, command, runId }) => {
      const key = `learngraph:command:${session}`;
      localStorage.setItem(key, JSON.stringify(command));
      localStorage.setItem(`${key}:${runId}`, JSON.stringify(command));
    }, { session, command: oldCommand, runId: oldRun.run_id });
    const submissions: Record<string, unknown>[] = [];
    const recoveredIds: string[] = [];
    const operations: string[] = [];
    await page.route('**/api/sessions/*/runs', async route => {
      const req = route.request();
      operations.push(req.method());
      if (req.method() !== 'POST') { await route.continue(); return; }
      submissions.push(req.postDataJSON());
      if (submissions.length === 1 && failure === 'not-delivered') { await route.abort('failed'); return; }
      const response = await route.fetch();
      expect(response.ok()).toBe(true);
      recoveredIds.push((await response.json()).run_id);
      if (submissions.length === 1) await route.abort('failed');
      else await route.fulfill({ response });
    });
    await page.goto(workbenchURL(goal, session));
    await expect(page.getByLabel('当前会话记录')).toContainText('旧的已完成问题');
    await page.getByLabel('向当前节点提问').fill('最近未确认的问题，不能被历史命令盖掉');
    await page.getByRole('button', { name: '发送问题' }).click();
    const pending = page.getByRole('region', { name: '未确认请求恢复' });
    await expect(pending).toContainText('最近未确认的问题，不能被历史命令盖掉');
    await expect(page.getByRole('alert')).toContainText('请求未确认');
    await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeEnabled();
    expect(submissions).toHaveLength(1);
    expect(submissions[0].request_id).not.toBe(oldCommand.body.request_id);
    if (failure === 'response-lost') {
      // The lost response still admitted a run. Finish that fixture execution
      // before reloading so its live SSE cannot invalidate the recovery GET.
      await expect.poll(async () => (await (await request.get(`/api/runs/${recoveredIds[0]}`)).json()).status).toBe('completed');
    }
    await page.reload();
    await expect(pending).toContainText('最近未确认的问题，不能被历史命令盖掉');
    await expect(pending).toContainText(String(submissions[0].request_id));
    await pending.getByRole('button', { name: '查询运行状态' }).click();
    await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeEnabled();
    expect(submissions).toHaveLength(1); // Neither refresh nor reload automatically resends.
    await pending.getByRole('button', { name: '重发未确认请求' }).click();
    await expect(pending).not.toBeVisible();
    await expect(page.locator('.assistant-message').last()).toContainText('后续问题会结合本会话的完整回合。');
    expect(submissions).toHaveLength(2);
    expect(submissions[1]).toEqual(submissions[0]);
    expect(operations.slice(operations.indexOf('POST') + 1, operations.lastIndexOf('POST'))).toContain('GET');
    if (failure === 'response-lost') expect(recoveredIds[1]).toBe(recoveredIds[0]);
    const history = await (await request.get(`/api${path}`)).json();
    expect(history).toHaveLength(2); // Old completed run + exactly one new execution.
    expect(history.filter((r: { user_text: string }) => r.user_text === submissions[0].user_text)).toHaveLength(1);
    await expect(page.getByRole('button', { name: '重试', exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.getByLabel('当前会话记录')).toContainText('最近未确认的问题，不能被历史命令盖掉');
    await expect(pending).not.toBeVisible();
    expect(submissions).toHaveLength(2);
  });
}

test('P0: recovery queries before resending, and a failed recovered run retries with a new linked ID', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const session = goal;
  const command = { path: `/sessions/${session}/runs`, body: { request_id: crypto.randomUUID(), user_text: '恢复失败任务的完整输入', goal_id: goal, node_id: 'n', mode: 'teaching' } };
  await page.addInitScript(({ session, command }) => localStorage.setItem(`learngraph:command:${session}:pending`, JSON.stringify(command)), { session, command });
  const submissions: Record<string, unknown>[] = [];
  let allowQuery = false;
  await page.route('**/api/sessions/*/runs', async route => {
    const matched = new URL(route.request().url()).pathname.match(/\/sessions\/([^/]+)\/runs$/);
    if (!matched || decodeURIComponent(matched[1]) !== session) { await route.continue(); return; }
    if (route.request().method() !== 'POST') {
      if (allowQuery) await route.fulfill({ json: [] });
      else await route.abort('failed');
      return;
    }
    const input = route.request().postDataJSON();
    submissions.push(input);
    const run = runDTO(submissions.length === 1 ? 'recovered-failed' : 'recovered-retry', input.user_text,
      submissions.length === 1 ? 'failed' : 'completed', submissions.length === 1 ? '' : '重试后的回答已完成');
    await route.fulfill({ status: 202, json: { ...run, error: submissions.length === 1 ? '模拟执行失败' : null } });
  });
  await openLearning(page, request, goal);
  const pending = page.getByRole('region', { name: '未确认请求恢复' });
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeDisabled();
  expect(submissions).toEqual([]);
  allowQuery = true;
  await pending.getByRole('button', { name: '查询运行状态' }).click();
  await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeEnabled();
  await pending.getByRole('button', { name: '重发未确认请求' }).click();
  await expect(page.locator('.wb-conversation > .run-status')).toContainText('模拟执行失败');
  expect(submissions).toEqual([command.body]);
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect.poll(() => submissions.length).toBe(2);
  await expect(page.locator('.assistant-message').last()).toContainText('重试后的回答已完成');
  expect(submissions[1]).toEqual({ ...command.body, request_id: submissions[1].request_id, retry_of_run_id: 'recovered-failed' });
  expect(submissions[1].request_id).not.toBe(command.body.request_id);
});

test('P0: delayed initial history cannot overwrite a newly acknowledged run', async ({ page, request }) => {
  const goal = await learningGoal(request);
  let release = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  let started = () => {};
  const initialQuery = new Promise<void>(resolve => { started = resolve; });
  await page.route('**/api/sessions/*/runs', async route => {
    if (route.request().method() !== 'POST') {
      started(); await gate;
      await route.fulfill({ json: [] });
    } else await route.fulfill({ status: 202, json: runDTO('new-run', route.request().postDataJSON().user_text) });
  });
  await openLearning(page, request, goal);
  await initialQuery;
  await page.getByLabel('向当前节点提问').fill('新运行不能被旧列表抹掉');
  await page.getByRole('button', { name: '发送问题' }).click();
  await expect(page.getByLabel('当前会话记录')).toContainText('新运行不能被旧列表抹掉');
  const response = page.waitForResponse(r => r.url().includes('/sessions/') && r.request().method() === 'GET');
  release(); await response;
  await page.evaluate(() => new Promise(requestAnimationFrame));
  await expect(page.getByLabel('当前会话记录')).toContainText('新运行不能被旧列表抹掉');
  await expect(page.locator('.assistant-message')).toContainText('模拟回答已完成');
});

for (const status of [422, 409]) {
  test(`P0: explicit HTTP ${status} rejection preserves input without locking new submissions`, async ({ page, request }) => {
    const goal = await learningGoal(request);
    const submissions: Record<string, unknown>[] = [];
    await page.route('**/api/sessions/*/runs', async route => {
      if (route.request().method() !== 'POST') { await route.fulfill({ json: [] }); return; }
      const input = route.request().postDataJSON();
      submissions.push(input);
      if (submissions.length === 1) await route.fulfill({ status, json: { error: { message: '明确业务拒绝' } } });
      else await route.fulfill({ status: 202, json: runDTO('after-rejection', input.user_text) });
    });
    await openLearning(page, request, goal);
    await page.getByLabel('向当前节点提问').fill('业务拒绝后保留我的问题');
    await page.getByRole('button', { name: '发送问题' }).click();
    await expect(page.getByRole('alert')).toContainText('请求被拒绝');
    await expect(page.getByLabel('向当前节点提问')).toHaveValue('业务拒绝后保留我的问题');
    await expect(page.getByRole('region', { name: '未确认请求恢复' })).not.toBeVisible();
    await expect(page.getByRole('button', { name: '发送问题' })).toBeEnabled();
    await learningContent(page);
    await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeEnabled();
    expect(submissions).toHaveLength(1);
    await page.getByRole('button', { name: '发送问题' }).click();
    await expect(page.locator('.assistant-message')).toContainText('模拟回答已完成');
    expect(submissions).toHaveLength(2);
    expect(submissions[1].user_text).toBe(submissions[0].user_text);
    expect(submissions[1].request_id).not.toBe(submissions[0].request_id);
  });
}

test('P0: long node scopes use a persisted bounded session for chat, exercises and reload', async ({ page, request }) => {
  const node = 'n'.repeat(128);
  const goal = await learningGoal(request, node);
  const sessionIds: string[] = [];
  const submittedSessionIds: string[] = [];
  page.on('request', req => {
    const match = new URL(req.url()).pathname.match(/^\/api\/sessions\/([^/]+)\/runs$/);
    if (match) sessionIds.push(decodeURIComponent(match[1]));
    if (match && req.method() === 'POST' && req.postDataJSON().mode === 'teaching') submittedSessionIds.push(decodeURIComponent(match[1]));
    if (req.method() === 'POST' && req.url().endsWith('/exercises')) { sessionIds.push(req.postDataJSON().session_id); submittedSessionIds.push(req.postDataJSON().session_id); }
  });
  const session = await openLearning(page, request, goal, node);
  await expect(page.getByLabel('当前对话范围')).toContainText('错误与恢复');
  await page.getByLabel('向当前节点提问').fill('合法最长节点 ID 仍能学习');
  await page.getByRole('button', { name: '发送问题' }).click();
  await expect(page.locator('.assistant-message')).toContainText('后续问题会结合本会话的完整回合。');
  await learningContent(page);
  await page.getByRole('button', { name: '生成练习', exact: true }).click();
  await expect(page.getByRole('radio')).toHaveCount(3);
  await page.reload();
  await expect(page.getByLabel('当前会话记录')).toContainText('合法最长节点 ID 仍能学习');
  await expect(page.getByRole('radio')).toHaveCount(3);
  const teachingSession = new URL(page.url()).searchParams.get('session');
  expect(teachingSession).toBe(session);
  expect((await (await request.get(`/api/conversations/${session}`)).json()).node_id).toBe(node);
  expect(sessionIds.filter(id => id === teachingSession).length).toBeGreaterThanOrEqual(4);
  expect(new Set(submittedSessionIds).size).toBe(1);
  expect(submittedSessionIds[0]).toHaveLength(36);
  expect(teachingSession).toBe(submittedSessionIds[0]);
  expect(sessionIds.every(id => id.length <= 128)).toBe(true); // P1 has separate lesson/explanation/proposal sessions.
  await expect(page.getByRole('alert')).toHaveCount(0);
});

for (const dirty of ['goal', 'graph'] as const) {
  test(`P0: completion and manual refresh protect dirty ${dirty} edits without unlocking conflicting writes`, async ({ page, request }) => {
    const goal = await learningGoal(request, 'n', false);
    await page.goto(workbenchURL(goal, `planning:${goal}`, 'graph'));
    await page.getByText('图谱与节点编辑', { exact: true }).click();
    await expect(page.getByLabel('节点标题')).toHaveValue('错误与恢复');
    let release = () => {};
    const gate = new Promise<void>(resolve => { release = resolve; });
    let started = () => {};
    const refreshStarted = new Promise<void>(resolve => { started = resolve; });
    let queryCount = 0;
    let completedQueries = 0;
    await page.route(`**/api/goals/${goal}`, async route => {
      if (route.request().method() !== 'GET') { await route.continue(); return; }
      const response = await route.fetch();
      if (++queryCount === 1) { started(); await gate; }
      await route.fulfill({ response }); completedQueries++;
    });
    await page.route(`**/api/goals/${goal}/graph-drafts`, route => route.fulfill({ status: 202,
      json: { ...runDTO('graph-complete', '', 'completed'), mode: 'graph' } }));
    await page.getByRole('button', { name: '重新生成图谱', exact: true }).click();
    await refreshStarted;
    const field = dirty === 'goal' ? page.getByRole('textbox', { name: '期望成果', exact: true }) : page.getByLabel('节点标题');
    const input = dirty === 'goal' ? '本地未保存的目标成果' : '本地未保存的节点标题';
    try { await field.fill(input); } finally { release(); }
    await expect.poll(() => completedQueries).toBe(1);
    await expect(field).toHaveValue(input);
    await page.getByRole('button', { name: '刷新目标与图谱', exact: true }).click();
    await expect.poll(() => completedQueries).toBe(2);
    await expect(field).toHaveValue(input);
    await expect(page.getByText('有未确认或未保存修改，请先保存。')).toBeVisible();
    await expect(page.getByRole('button', { name: '审核完成，发布图谱', exact: true })).toBeDisabled();
    if (dirty === 'goal') {
      await expect(page.getByLabel('节点标题')).toBeDisabled();
      await page.getByRole('button', { name: '确认目标摘要', exact: true }).click();
      const saved = await (await request.get(`/api/goals/${goal}`)).json();
      expect(saved.goal.desired_outcome).toBe(input);
      expect(saved.goal.confirmed).toBe(true);
      expect(saved.graph).toBeNull(); // Reconfirmation still atomically invalidates the old draft.
      await expect(page.getByRole('button', { name: '生成图谱草稿', exact: true })).toBeEnabled();
    } else {
      await expect(page.getByRole('button', { name: '确认目标摘要', exact: true })).toBeDisabled();
      await page.getByRole('button', { name: '保存图谱修改', exact: true }).click();
      await expect(page.getByText('有未确认或未保存修改，请先保存。')).not.toBeVisible();
      await expect(page.getByRole('button', { name: '审核完成，发布图谱', exact: true })).toBeEnabled();
      const saved = await (await request.get(`/api/goals/${goal}`)).json();
      expect(saved.graph.status).toBe('draft');
      expect(saved.graph.nodes[0].title).toBe(input);
    }
  });
}
