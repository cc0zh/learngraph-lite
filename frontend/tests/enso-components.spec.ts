import type { Locator, Page, Request } from '@playwright/test';
import type { Run } from '../src/types';
import { expect, learningGoal, openLearning, runDTO, test, workbenchURL } from './fixtures';

function posts(page: Page) {
  const sent: Request[] = [];
  page.on('request', request => { if (request.method() === 'POST') sent.push(request); });
  return sent;
}
function runPosts(sent: Request[]) {
  return sent.filter(request => /\/api\/sessions\/[^/]+\/runs$/.test(new URL(request.url()).pathname));
}
async function flushUI(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}
function runStatus(page: Page) {
  return page.locator('.wb-conversation > .run-status');
}
function steps(page: Page) {
  return runStatus(page).locator('details').filter({ has: page.locator('summary').filter({ hasText: '处理步骤' }) });
}
function failedRun(id = 'enso-failed'): Run {
  return { ...runDTO(id, '请检索资料并解释', 'failed', ''), error: '资料读取失败，请显式重试', tool_activity: {
    context: { call_id: 'context', name: 'get_learning_context', status: 'completed' },
    search: { call_id: 'search', name: 'search_documents', status: 'failed' },
    chunk: { call_id: 'chunk', name: 'read_document_chunk', status: 'failed' },
    future: { call_id: 'future', name: 'future_operation', status: 'completed' },
  } };
}
// Only run reads/SSE are mocked. Unexpected POSTs continue to the fixture and are observed.
async function restoreRun(page: Page, run: Run) {
  await page.route('**/api/sessions/*/runs', route => route.request().method() === 'GET'
    ? route.fulfill({ json: [run] }) : route.continue());
  await page.route(`**/api/runs/${run.run_id}`, route => route.request().method() === 'GET'
    ? route.fulfill({ json: run }) : route.continue());
  await page.route(`**/api/runs/${run.run_id}/events`, route => route.fulfill({ contentType: 'text/event-stream',
    body: `event: run.snapshot\ndata: ${JSON.stringify({ payload: run })}\n\n`,
  }));
}
async function expectUnifiedComposer(page: Page, label: string, submitLabel: string) {
  const input = page.getByRole('textbox', { name: label, exact: true });
  await expect(input).toBeVisible();
  const composer = page.locator('.message-composer').filter({ has: input });
  await expect(composer, `${label}: input and submit share one .message-composer`).toHaveCount(1);
  await expect(composer.getByRole('button', { name: submitLabel, exact: true })).toHaveAttribute('aria-label', submitLabel);
}
async function expectTouchTarget(control: Locator) {
  const box = await control.boundingBox();
  expect(box, 'The scrolled control must have a rendered hit target').not.toBeNull();
  expect(box!.width, 'Touch target width').toBeGreaterThanOrEqual(44);
  expect(box!.height, 'Touch target height').toBeGreaterThanOrEqual(44);
}

test('enso: failed steps collapse natively, expose the failure count and keep error/retry outside', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const run = failedRun();
  // A restored failure has a real saved command, as in the existing recovery tests.
  const command = { path: `/sessions/${goal}/runs`, body: { request_id: crypto.randomUUID(), goal_id: goal,
    node_id: 'n', mode: 'teaching', user_text: run.user_text } };
  await page.addInitScript(({ session, runId, command }) => {
    localStorage.setItem(`learngraph:command:${session}:${runId}`, JSON.stringify(command));
  }, { session: goal, runId: run.run_id, command });
  await restoreRun(page, run);
  const sent = posts(page);
  await openLearning(page, request, goal);
  const details = steps(page), summary = details.locator(':scope > summary');
  await expect(details).toHaveCount(1);
  await expect(details).toHaveJSProperty('open', false);
  await expect(summary).toBeVisible();
  await expect(summary).toContainText('处理步骤');
  // Two failures out of four: a total count alone must not satisfy this assertion.
  await expect(summary).toContainText(/失败\s*[:：]?\s*2|2\s*(?:个|项|步)?\s*失败/);
  await expect(details.locator('.tool')).toHaveCount(4);
  await expect(details.locator('.tool').first()).toBeHidden();
  const error = runStatus(page).getByText(run.error!, { exact: false });
  const retry = runStatus(page).getByRole('button', { name: '重试', exact: true });
  await expect(error).toBeVisible();
  await expect(retry).toBeVisible();
  await expect(details.getByText(run.error!, { exact: false })).toHaveCount(0);
  await expect(details.getByRole('button', { name: '重试', exact: true })).toHaveCount(0);
  await summary.focus();
  await summary.press('Enter');
  await expect(details).toHaveJSProperty('open', true);
  const labels = { get_learning_context: '读取当前学习状态', search_documents: '检索学习资料',
    read_document_chunk: '读取资料原文', future_operation: '处理学习操作' };
  for (const [name, label] of Object.entries(labels)) {
    const tool = details.locator(`.tool[data-tool-name="${name}"]`);
    await expect(tool).toBeVisible();
    await expect(tool).toContainText(label);
    await expect(tool).not.toContainText(name);
  }
  await summary.press('Space');
  await expect(details).toHaveJSProperty('open', false);
  await expect(error).toBeVisible();
  await expect(retry).toBeVisible();
  await page.reload();
  await expect(summary).toBeVisible();
  await expect(details).toHaveJSProperty('open', false);
  await expect(summary).toContainText(/失败\s*[:：]?\s*2|2\s*(?:个|项|步)?\s*失败/);
  await expect(error).toBeVisible();
  await expect(retry).toBeVisible();
  await flushUI(page);
  expect(sent, 'Expanding, collapsing and reloading are read-only').toEqual([]);
});

test('enso: queued and running snapshots both restore keyboard-expandable steps without POST', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const sent = posts(page);
  for (const state of ['queued', 'running'] as const) {
    const run: Run = { ...runDTO(`enso-${state}`, `读取${state}运行`, state, ''), tool_activity: {
      context: { call_id: 'context', name: 'get_learning_context', status: state === 'running' ? 'completed' : 'queued' },
      search: { call_id: 'search', name: 'search_documents', status: state },
    } };
    await restoreRun(page, run);
    await openLearning(page, request, goal);
    const details = steps(page), summary = details.locator(':scope > summary');
    await expect(summary, `${state}: a native summary is visible`).toBeVisible();
    await expect(details).toHaveJSProperty('open', false);
    await expect(details.locator('.tool')).toHaveCount(2);
    await expect(details.locator('.tool').first()).toBeHidden();
    await summary.focus();
    await summary.press('Space');
    await expect(details).toHaveJSProperty('open', true);
    await expect(details.locator('.tool[data-tool-name="get_learning_context"]')).toContainText('读取当前学习状态');
    await expect(details.locator('.tool[data-tool-name="search_documents"]')).toContainText('检索学习资料');
    await summary.press('Enter');
    await expect(details).toHaveJSProperty('open', false);
    await page.reload();
    await expect(summary).toBeVisible();
    await expect(details).toHaveJSProperty('open', false);
    await flushUI(page);
    expect(sent, `${state}: restoring and toggling steps must not start/retry a run`).toEqual([]);
  }
});

test('enso: node tabs implement roving focus, arrow wrap, Home/End and linked panels without changing the draft', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const sent = posts(page);
  await openLearning(page, request, goal);
  const input = page.getByLabel('向当前节点提问', { exact: true });
  const draft = '切换紧凑 tabs 也不能改写的未发送草稿';
  await input.fill(draft);
  const tablist = page.getByRole('tablist').filter({ has: page.getByRole('tab', { name: '学习内容', exact: true }) });
  await expect(tablist).toHaveCount(1);
  await expect(tablist.getByRole('tab')).toHaveCount(2);
  async function selected(name: string) {
    for (const tabName of ['对话', '学习内容']) {
      const tab = tablist.getByRole('tab', { name: tabName, exact: true });
      await expect(tab).toHaveAttribute('aria-selected', String(tabName === name));
      await expect(tab).toHaveAttribute('tabindex', tabName === name ? '0' : '-1');
      const controls = await tab.getAttribute('aria-controls');
      expect(controls, `${tabName} must identify its tabpanel`).toBeTruthy();
      const target = page.locator(`[id=${JSON.stringify(controls)}]`);
      // Inactive panels may be hidden or unmounted; every selected tab must resolve.
      if (tabName === name) {
        await expect(tab).toBeFocused();
        await expect(target).toHaveAttribute('role', 'tabpanel');
        await expect(target).toBeVisible();
        const tabId = await tab.getAttribute('id');
        expect(tabId, 'The panel must be labelled by its tab').toBeTruthy();
        await expect(target).toHaveAttribute('aria-labelledby', tabId!);
      } else await expect(target).toBeHidden();
    }
  }
  await tablist.getByRole('tab', { name: '对话', exact: true }).focus();
  await selected('对话');
  await tablist.getByRole('tab', { name: '对话', exact: true }).press('Tab');
  await expect(page.getByRole('tabpanel', { name: '对话', exact: true })).toBeFocused();
  await tablist.getByRole('tab', { name: '对话', exact: true }).focus();
  for (const [key, name] of [
    ['ArrowRight', '学习内容'], ['ArrowRight', '对话'], ['ArrowLeft', '学习内容'],
    ['Home', '对话'], ['End', '学习内容'], ['ArrowLeft', '对话'],
  ]) {
    await page.keyboard.press(key);
    await selected(name);
    expect(sent, `${key}: selecting a tab is read-only`).toEqual([]);
  }
  await expect(input).toHaveValue(draft);
  await flushUI(page);
  expect(sent).toEqual([]);
});

test('enso: directory disclosure keeps native Space/Enter behavior beside the graph and never POSTs', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const sent = posts(page);
  await openLearning(page, request, goal);
  const input = page.getByLabel('向当前节点提问', { exact: true });
  await input.fill('目录收起后仍保留的草稿');
  const details = page.locator('.wb-spaces details').filter({ has: page.locator('.wb-session[aria-current=page]') });
  const summary = details.locator(':scope > summary');
  await expect(details).toHaveJSProperty('open', true);
  await summary.press('Space');
  await expect(details).toHaveJSProperty('open', false);
  await expect(details.locator('.wb-session[aria-current=page]')).toBeHidden();
  await summary.press('Enter');
  await expect(details).toHaveJSProperty('open', true);
  await expect(details.locator('.wb-session[aria-current=page]')).toBeVisible();
  await expect(input).toHaveValue('目录收起后仍保留的草稿');
  expect(sent).toEqual([]);
});

test('enso: unified learning, goal-creation and planning composers retain labels and explicit submit names', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const created = await request.post('/api/goals', { data: { title: `Enso 规划输入契约-${crypto.randomUUID()}` } });
  expect(created.ok()).toBe(true);
  const planningGoal = (await created.json()).goal_id as string;
  const sent = posts(page);
  await openLearning(page, request, goal);
  await expectUnifiedComposer(page, '向当前节点提问', '发送问题');
  await page.goto('/?mode=goal');
  await expectUnifiedComposer(page, '描述学习目标', '发送并创建目标');
  await page.goto(workbenchURL(planningGoal, `planning:${planningGoal}`));
  await expectUnifiedComposer(page, '和 Agent 讨论目标与路线', '发送消息');
  await flushUI(page);
  expect(sent, 'Mounting each composer must not create a goal or start a model').toEqual([]);
});

test('enso: ordinary chat sends only with Ctrl/Meta+Enter, never bare Enter or a composing shortcut', async ({ page, request }) => {
  const sent = posts(page);
  await page.goto('/');
  const input = page.getByRole('textbox', { name: '发送消息', exact: true });
  const submit = page.locator('.message-composer button[type=submit]');
  await input.fill('普通 Enter 只换行');
  await input.press('End');
  await input.press('Enter');
  await expect(input).toHaveValue('普通 Enter 只换行\n');
  await flushUI(page);
  expect(sent, 'Bare Enter must not even create a conversation').toEqual([]);
  await input.fill('输入法候选仍未确认');
  await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', ctrlKey: true, isComposing: true, bubbles: true, cancelable: true });
  await expect(input).toHaveValue('输入法候选仍未确认');
  await flushUI(page);
  expect(sent, 'Ctrl+Enter while isComposing=true must not send').toEqual([]);
  const questions: string[] = [];
  for (const modifier of ['Control', 'Meta']) {
    const question = `${modifier} 显式发送的普通问题`;
    questions.push(question);
    await input.fill(question);
    await expect(submit).toBeEnabled();
    await input.press(`${modifier}+Enter`);
    await expect.poll(() => runPosts(sent).length, { message: `${modifier}+Enter must submit exactly one real fixture run` }).toBe(questions.length);
    expect(runPosts(sent).at(-1)!.postDataJSON()).toMatchObject({ user_text: question });
    await expect(input).toHaveValue('');
    await expect(page.getByLabel('当前会话记录')).toContainText(question);
  }
  const session = new URL(page.url()).searchParams.get('session');
  expect(session).toBeTruthy();
  await expect.poll(async () => {
    const response = await request.get(`/api/sessions/${encodeURIComponent(session!)}/runs`);
    expect(response.ok()).toBe(true);
    return ((await response.json()) as Run[]).map(run => run.user_text);
  }).toEqual(questions);
  expect(runPosts(sent)).toHaveLength(2);
  expect(sent.filter(request => new URL(request.url()).pathname === '/api/conversations')).toHaveLength(1);
});

test('enso: a disabled submit leaves its unified composer editable and blocks new shortcut POSTs', async ({ page, request }) => {
  const session = crypto.randomUUID();
  expect((await request.post('/api/conversations', { data: { session_id: session, title: '普通会话的发送门禁', goal_id: null, node_id: null } })).ok()).toBe(true);
  let release!: () => void, arrived!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const seen = new Promise<void>(resolve => { arrived = resolve; });
  await page.route('**/api/sessions/*/runs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch(); // Use the real fixture; delay only delivery to the UI.
    arrived();
    await gate;
    await route.fulfill({ response });
  });
  const sent = posts(page);
  await page.goto(workbenchURL(undefined, session));
  const input = page.getByRole('textbox', { name: '发送消息', exact: true });
  const submit = page.getByRole('button', { name: '发送问题', exact: true });
  await input.fill('先显式发送一个普通问题');
  try {
    await submit.click();
    await seen;
    await expect(submit).toBeDisabled();
    await expect(input).toBeEditable();
    await input.fill('等待响应期间继续编辑的新草稿');
    await expectUnifiedComposer(page, '发送消息', '发送问题');
    const count = sent.length;
    for (const key of ['Control+Enter', 'Meta+Enter']) await input.press(key);
    await flushUI(page);
    await expect(input).toHaveValue('等待响应期间继续编辑的新草稿');
    expect(sent, 'Disabled submit cannot be bypassed by either shortcut').toHaveLength(count);
    expect(runPosts(sent)).toHaveLength(1);
  } finally { release(); }
  await expect(submit).toBeEnabled();
  await expect(input).toHaveValue('等待响应期间继续编辑的新草稿');
});

for (const viewport of [{ width: 390, height: 844 }, { width: 568, height: 320 }]) {
  test(`enso: ${viewport.width}x${viewport.height} scrolled composer targets stay clickable and >=44px below collapsed steps`, async ({ page, request }) => {
    await page.setViewportSize(viewport);
    const goal = await learningGoal(request);
    const run = failedRun(`enso-small-${viewport.width}`);
    run.tool_activity = Object.fromEntries(Array.from({ length: 24 }, (_, index) => [
      `step-${index}`, { call_id: `step-${index}`, name: 'search_documents', status: 'failed' },
    ]));
    await restoreRun(page, run);
    const sent = posts(page);
    await openLearning(page, request, goal);
    const navigation = page.getByRole('navigation', { name: '工作台区域', exact: true });
    if (await navigation.isVisible()) await navigation.getByRole('button', { name: '对话与内容', exact: true }).click();
    const details = steps(page);
    await expect(details).toHaveJSProperty('open', false);
    await expect(details.locator('.tool')).toHaveCount(24);
    await expect(details.locator('.tool').first()).toBeHidden();
    const input = page.getByLabel('向当前节点提问', { exact: true });
    await input.scrollIntoViewIfNeeded();
    await expectTouchTarget(input);
    await input.click(); // Real actionability/hit testing, not just a bounding-box assertion.
    await expect(input).toBeFocused();
    const question = `在 ${viewport.width}x${viewport.height} 可实际发送的问题`;
    await input.fill(question);
    const submit = page.getByRole('button', { name: '发送问题', exact: true });
    await submit.scrollIntoViewIfNeeded();
    await expectTouchTarget(submit);
    expect(sent, 'Scrolling past collapsed steps must not submit').toEqual([]);
    const [response] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'POST' && /\/api\/sessions\/[^/]+\/runs$/.test(new URL(response.url()).pathname)),
      submit.click(),
    ]);
    expect(response.status()).toBe(202);
    expect(runPosts(sent)).toHaveLength(1);
    expect(runPosts(sent)[0].postDataJSON()).toMatchObject({ user_text: question, goal_id: goal, node_id: 'n' });
  });
}
