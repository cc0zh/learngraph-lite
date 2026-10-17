import type { Locator, Page } from '@playwright/test';
import type { Conversation, Plan } from '../src/types';
import { expect, learningGoal, openLearning, test, workbenchURL } from './fixtures';

const previewName = '知识图谱交互示例';
const useTheme = '用此主题起草目标';
const pythonPrompt = '我想学习 Python 基础，重点理解数据类型、控制流、函数与可复用的小程序。';
const viewports = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1440, height: 1000 },
];

function writes(page: Page) {
  const sent: string[] = [];
  page.on('request', request => {
    if (!['GET', 'HEAD'].includes(request.method())) sent.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });
  return sent;
}

async function reveal(page: Page, area: '学习空间' | '对话与内容' | '图谱与节点') {
  const nav = page.getByRole('navigation', { name: '工作台区域', exact: true });
  if (await nav.isVisible()) await nav.getByRole('button', { name: area, exact: true }).click();
  const panel = area === '对话与内容' ? page.getByRole('region', { name: '对话与学习内容', exact: true })
    : page.getByRole('complementary', { name: area, exact: true });
  await expect(panel).toBeVisible();
  return panel;
}

async function choose(page: Page, title: string) {
  await reveal(page, '对话与内容');
  const button = page.getByRole('group', { name: '探索知识示例', exact: true }).getByRole('button', { name: title, exact: true });
  await button.click();
  // On narrow screens choosing a topic immediately hides main and reveals graph.
  await expect(page.getByRole('group', { name: '探索知识示例', exact: true, includeHidden: true })
    .getByRole('button', { name: title, exact: true, includeHidden: true })).toHaveAttribute('aria-pressed', 'true');
}

async function preview(page: Page) {
  await reveal(page, '图谱与节点');
  const sample = page.getByRole('region', { name: previewName, exact: true });
  await expect(sample).toBeVisible();
  return sample;
}

async function noRootOverflow(page: Page) {
  for (const selector of ['html', '.workbench']) {
    const bounds = await page.locator(selector).evaluate(element => {
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, viewport: innerWidth, scroll: element.scrollWidth, client: element.clientWidth };
    });
    expect(bounds.left, `${selector}: left edge`).toBeGreaterThanOrEqual(-1);
    expect(bounds.right, `${selector}: right edge`).toBeLessThanOrEqual(bounds.viewport + 1);
    expect(bounds.scroll, `${selector}: no horizontal scroll`).toBeLessThanOrEqual(bounds.client + 1);
  }
}

async function noHiddenAncestors(content: Locator) {
  await expect(content).toBeVisible();
  const hidden = await content.evaluate(element => {
    const found: string[] = [];
    for (let current: Element | null = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (Number(style.opacity) <= 0.01 || style.visibility === 'hidden' || style.display === 'none') found.push(current.tagName);
    }
    return found;
  });
  expect(hidden, 'Reduced motion must not strand real content behind an entrance animation').toEqual([]);
}

test('taste studio: sample nodes are clearly illustrative and browsing never persists business data', async ({ page, request }) => {
  const goals = await (await request.get('/api/goals')).json();
  const conversations = await (await request.get('/api/conversations')).json();
  const sent = writes(page);
  await page.goto('/');
  const sample = await preview(page);
  await expect(sample).toContainText('交互示例');
  await expect(sample).toContainText('不是 AI 生成结果');
  await expect(sample).toContainText('发送后才创建');
  const node = sample.getByRole('button', { name: '文档分块', exact: true });
  await node.click();
  await expect(node).toHaveAttribute('aria-pressed', 'true');
  await expect(sample.getByRole('heading', { name: '文档分块', exact: true })).toBeVisible();
  await expect(sample).toContainText('粒度和上下文之间的取舍');
  await expect(sample.getByRole('button', { name: '开始学习此节点', exact: true })).toHaveCount(0);
  expect(new URL(page.url()).search).toBe('');
  await page.reload();
  await expect(page.getByRole('textbox', { name: '描述学习目标', exact: true })).toHaveValue('');
  expect(await (await request.get('/api/goals')).json()).toEqual(goals);
  expect(await (await request.get('/api/conversations')).json()).toEqual(conversations);
  expect(sent).toEqual([]);
});

test('taste studio: switching topics updates graph and detail without overwriting either unsent draft', async ({ page }) => {
  const sent = writes(page);
  await page.goto('/?mode=chat');
  const plain = page.getByRole('textbox', { name: '发送消息', exact: true });
  await plain.fill('我自己的普通问题草稿');
  await choose(page, 'Python 基础');
  const sample = await preview(page);
  await expect(sample.getByLabel('Python 基础示例图谱', { exact: true })).toBeVisible();
  await expect(sample.getByRole('button', { name: '值与类型', exact: true })).toBeVisible();
  await expect(sample.getByRole('button', { name: '文档分块', exact: true })).toHaveCount(0);
  await sample.getByRole('button', { name: '函数与作用域', exact: true }).click();
  await expect(sample.getByRole('heading', { name: '函数与作用域', exact: true })).toBeVisible();
  await expect(sample).toContainText('参数、返回值与作用域');
  await reveal(page, '对话与内容');
  await expect(plain).toHaveValue('我自己的普通问题草稿');
  await page.getByRole('button', { name: '创建目标', exact: true }).click();
  await page.getByLabel('描述学习目标', { exact: true }).fill('我自己的目标草稿');
  await choose(page, '概率与统计');
  const statistics = await preview(page);
  await expect(statistics.getByLabel('概率与统计示例图谱', { exact: true })).toBeVisible();
  await expect(statistics.getByRole('button', { name: '随机事件', exact: true })).toBeVisible();
  await expect(statistics.getByRole('button', { name: '函数与作用域', exact: true })).toHaveCount(0);
  await statistics.getByRole('button', { name: '统计推断', exact: true }).click();
  await expect(statistics.getByRole('heading', { name: '统计推断', exact: true })).toBeVisible();
  await expect(statistics).toContainText('统计证据与确定结论');
  await reveal(page, '对话与内容');
  await expect(page.getByLabel('描述学习目标', { exact: true })).toHaveValue('我自己的目标草稿');
  await page.reload();
  await expect(page.getByLabel('描述学习目标', { exact: true })).toHaveValue('我自己的目标草稿');
  await page.getByRole('button', { name: '普通提问', exact: true }).click();
  await expect(plain).toHaveValue('我自己的普通问题草稿');
  expect(sent).toEqual([]);
});

test('taste studio: explicit use fills the selected topic in goal mode but does not submit or erase the plain draft', async ({ page }) => {
  const sent = writes(page);
  await page.goto('/?mode=chat');
  await page.getByRole('textbox', { name: '发送消息', exact: true }).fill('保留我的普通输入');
  await choose(page, 'Python 基础');
  await (await preview(page)).getByRole('button', { name: useTheme, exact: true }).click();
  await expect(page).toHaveURL(/\?mode=goal$/);
  const input = page.getByLabel('描述学习目标', { exact: true });
  await expect(input).toHaveValue(pythonPrompt);
  await expect(input).toBeFocused();
  await expect(page.getByRole('button', { name: '发送并创建目标', exact: true })).toBeEnabled();
  await page.reload();
  await expect(input).toHaveValue(pythonPrompt);
  await page.getByRole('button', { name: '普通提问', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '发送消息', exact: true })).toHaveValue('保留我的普通输入');
  expect(sent).toEqual([]);
});

test('taste studio: cancelling topic replacement keeps the goal draft and current mode after reload', async ({ page }) => {
  const sent = writes(page);
  await page.goto('/?mode=goal');
  const input = page.getByLabel('描述学习目标', { exact: true });
  await input.fill('不能被示例覆盖的目标草稿');
  await choose(page, 'Python 基础');
  const dialogs: { type: string; message: string }[] = [];
  page.once('dialog', async dialog => {
    dialogs.push({ type: dialog.type(), message: dialog.message() });
    await dialog.dismiss();
  });
  await (await preview(page)).getByRole('button', { name: useTheme, exact: true }).click();
  expect(dialogs).toHaveLength(1);
  expect(dialogs[0].type).toBe('confirm');
  expect(dialogs[0].message).toContain('草稿');
  await reveal(page, '对话与内容');
  await expect(input).toHaveValue('不能被示例覆盖的目标草稿');
  await expect(page).toHaveURL(/\?mode=goal$/);
  await page.reload();
  await expect(input).toHaveValue('不能被示例覆盖的目标草稿');
  expect(sent).toEqual([]);
});

test('taste studio: keyboard can choose a topic, browse sample nodes and explicitly use it without sending', async ({ page }) => {
  const sent = writes(page);
  await page.goto('/');
  const topic = page.getByRole('group', { name: '探索知识示例', exact: true }).getByRole('button', { name: 'Python 基础', exact: true });
  await topic.focus();
  await page.keyboard.press('Enter');
  await expect(topic).toHaveAttribute('aria-pressed', 'true');
  const sample = await preview(page);
  const first = sample.getByRole('button', { name: '值与类型', exact: true });
  await first.focus();
  await page.keyboard.press('Space');
  await expect(first).toHaveAttribute('aria-pressed', 'true');
  await expect(sample.getByRole('heading', { name: '值与类型', exact: true })).toBeVisible();
  await page.keyboard.press('Tab');
  const second = sample.getByRole('button', { name: '容器与引用', exact: true });
  await expect(second).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(second).toHaveAttribute('aria-pressed', 'true');
  await expect(sample.getByRole('heading', { name: '容器与引用', exact: true })).toBeVisible();
  // Complete the native tab sequence rather than invoking a mouse handler directly.
  for (let index = 0; index < 4; index++) await page.keyboard.press('Tab');
  await expect(sample.getByRole('button', { name: useTheme, exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('描述学习目标', { exact: true })).toBeFocused();
  await expect(page.getByLabel('描述学习目标', { exact: true })).toHaveValue(pythonPrompt);
  expect(sent).toEqual([]);
});

for (const width of [375, 768]) {
  test(`taste studio: ${width}px keyboard topic choice transfers focus into the visible graph`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const sent = writes(page);
    await page.goto('/');
    const topic = page.getByRole('group', { name: '探索知识示例', exact: true }).getByRole('button', { name: 'Python 基础', exact: true });
    await topic.focus();
    await page.keyboard.press('Enter');
    const sample = page.getByRole('region', { name: previewName, exact: true });
    await expect(sample).toBeVisible();
    await expect(sample.getByRole('button', { name: '条件与循环', exact: true })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(sample.getByRole('button', { name: '函数与作用域', exact: true })).toBeFocused();
    expect(sent).toEqual([]);
  });
}

test.describe('touch feedback', () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });
  test('taste studio: touch selection keeps sample nodes readable without sticky dark hover on neutral controls', async ({ page }) => {
    const sent = writes(page);
    await page.goto('/');
    await page.getByRole('group', { name: '探索知识示例', exact: true }).getByRole('button', { name: 'Python 基础', exact: true }).tap();
    const sample = page.getByRole('region', { name: previewName, exact: true });
    const node = sample.getByRole('button', { name: '值与类型', exact: true });
    await node.tap();
    await expect(node).toHaveCSS('color', 'rgb(255, 255, 255)');
    await expect(node).toHaveCSS('background-color', 'rgb(37, 75, 61)');
    await expect(sample.getByRole('button', { name: useTheme, exact: true })).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    expect(sent).toEqual([]);
  });
});

test('taste studio: a model-status read error leaves the composer and panel bottoms reachable', async ({ page }) => {
  await page.route('**/api/model/status', route => route.fulfill({ status: 503, json: { detail: '状态暂不可用' } }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toBeVisible();
  const input = page.getByRole('textbox', { name: '描述学习目标', exact: true });
  await input.fill('错误状态下仍保留的草稿');
  const submit = page.locator('.message-composer button[type=submit]');
  await submit.scrollIntoViewIfNeeded();
  const box = await submit.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(await page.evaluate(() => innerHeight));
  await expect(input).toHaveValue('错误状态下仍保留的草稿');
});

for (const viewport of viewports) {
  test(`taste studio: ${viewport.width}px start and goal-mode sample keep roots inside the viewport`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const sent = writes(page);
    await page.goto('/');
    await expect(page.getByRole('textbox', { name: '描述学习目标', exact: true })).toBeVisible();
    if (viewport.width <= 768) {
      await expect(page.getByLabel('当前对话范围', { exact: true })).toBeHidden();
      await expect(page.getByRole('navigation', { name: '工作台区域', exact: true })).toBeVisible();
    }
    for (const area of ['学习空间', '对话与内容', '图谱与节点'] as const) {
      await reveal(page, area);
      await noRootOverflow(page);
    }
    await choose(page, 'Python 基础');
    await expect(page.getByRole('region', { name: previewName, exact: true })).toBeVisible();
    if (viewport.width <= 768) {
      await expect(page.getByRole('navigation', { name: '工作台区域', exact: true }).getByRole('button', { name: '图谱与节点', exact: true })).toHaveAttribute('aria-pressed', 'true');
    }
    await (await preview(page)).getByRole('button', { name: useTheme, exact: true }).click();
    await expect(page.getByLabel('描述学习目标', { exact: true })).toBeVisible();
    await expect(page.getByLabel('描述学习目标', { exact: true })).toHaveValue(pythonPrompt);
    if (viewport.width <= 768) {
      await expect(page.getByRole('navigation', { name: '工作台区域', exact: true }).getByRole('button', { name: '对话与内容', exact: true })).toHaveAttribute('aria-pressed', 'true');
    }
    for (const area of ['对话与内容', '图谱与节点'] as const) {
      await reveal(page, area);
      await noRootOverflow(page);
    }
    expect(sent).toEqual([]);
  });
}

test('taste studio: reduced motion leaves the start, switched sample and goal input painted and usable', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const sent = writes(page);
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await noHiddenAncestors(page.getByRole('region', { name: '创建目标', exact: true }).getByRole('heading', { level: 1 }));
    await noHiddenAncestors(page.getByRole('textbox', { name: '描述学习目标', exact: true }));
    await choose(page, 'Python 基础');
    const sample = await preview(page);
    await noHiddenAncestors(sample.getByLabel('Python 基础示例图谱', { exact: true }));
    await sample.getByRole('button', { name: '函数与作用域', exact: true }).click();
    await noHiddenAncestors(sample.getByRole('heading', { name: '函数与作用域', exact: true }));
    await noHiddenAncestors(sample.getByRole('button', { name: useTheme, exact: true }));
    await sample.getByRole('button', { name: useTheme, exact: true }).click();
    const input = page.getByLabel('描述学习目标', { exact: true });
    await noHiddenAncestors(input);
    await expect(input).toBeEnabled();
    await expect(input).toHaveValue(pythonPrompt);
  }
  expect(sent).toEqual([]);
});

test('taste studio: KnowledgeOverview node clicks only browse and preserve the saved conversation draft', async ({ page, request }) => {
  await page.setViewportSize(viewports[2]);
  const goal = await learningGoal(request, 'n', false);
  const initial: Plan = await (await request.get(`/api/goals/${goal}`)).json();
  const edited = await request.patch(`/api/goals/${goal}/graph`, { data: {
    expected_version: initial.version,
    nodes: [initial.graph!.nodes[0], { id: 'evidence', title: '证据与核对', explanation: '浏览证据并不切换学习会话', learning_outcome: '核对来源', estimated_minutes: 15, priority: 2 }],
    edges: [{ source: 'n', target: 'evidence', kind: 'prerequisite' }],
  } });
  expect(edited.ok()).toBe(true);
  const draft: Plan = await edited.json();
  expect((await request.post(`/api/goals/${goal}/graph/publish`, { data: {
    expected_version: draft.version, expected_revision: draft.graph!.revision,
  } })).ok()).toBe(true);
  const session = await openLearning(page, request, goal);
  await page.getByLabel('向当前节点提问', { exact: true }).fill('原节点未发送的问题');
  const saved = await (await request.get(`/api/goals/${goal}`)).json();
  const conversations = (await (await request.get('/api/conversations')).json() as Conversation[]).filter(item => item.goal_id === goal);
  const sent = writes(page);
  await page.goto(workbenchURL(goal));
  const overview = page.getByRole('region', { name: '知识图谱全景', exact: true });
  await expect(overview).toBeVisible();
  await expect(overview).toContainText('已发布');
  // Scope to the main map rather than the node directory or a conversation's compact map.
  await overview.locator('.react-flow__node').filter({ hasText: '证据与核对' }).click();
  await expect(page.getByRole('region', { name: '所查看节点', exact: true })).toContainText('证据与核对');
  await expect(page.getByLabel('当前对话范围', { exact: true })).toContainText('浏览图谱 · 尚未进入学习对话');
  expect(new URL(page.url()).searchParams.get('goal')).toBe(goal);
  expect(new URL(page.url()).searchParams.has('session')).toBe(false);
  await expect(page.getByRole('button', { name: '开始学习此节点', exact: true })).toBeEnabled();
  expect(await (await request.get(`/api/goals/${goal}`)).json()).toEqual(saved);
  expect((await (await request.get('/api/conversations')).json() as Conversation[]).filter(item => item.goal_id === goal)).toEqual(conversations);
  await page.goto(workbenchURL(goal, session));
  await expect(page.getByLabel('向当前节点提问', { exact: true })).toHaveValue('原节点未发送的问题');
  await expect(page.getByLabel('当前对话范围', { exact: true })).toContainText('节点：错误与恢复');
  expect(sent).toEqual([]);
});

test('taste studio: overview nodes paint at every width after tool navigation and viewport changes', async ({ page, request }) => {
  const goal = await learningGoal(request, 'n', false);
  const plan: Plan = await (await request.get(`/api/goals/${goal}`)).json();
  const nodes = Array.from({ length: 7 }, (_, index) => ({ id: `paint-${index}`, title: `知识节点 ${index + 1}`, explanation: '用于验证实际图谱节点测量', learning_outcome: '浏览图谱', estimated_minutes: 20, priority: 2 }));
  const edges = [[0, 2], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6]].map(([source, target]) => ({ source: nodes[source].id, target: nodes[target].id, kind: 'prerequisite' }));
  const draft: Plan = await (await request.patch(`/api/goals/${goal}/graph`, { data: { expected_version: plan.version, nodes, edges } })).json();
  expect((await request.post(`/api/goals/${goal}/graph/publish`, { data: { expected_version: draft.version, expected_revision: draft.graph!.revision } })).ok()).toBe(true);
  const session = crypto.randomUUID();
  expect((await request.post('/api/conversations', { data: { session_id: session, goal_id: goal, node_id: nodes[0].id, title: '只读图谱测量回归' } })).ok()).toBe(true);
  const sent = writes(page);
  for (const viewport of [...viewports].reverse()) {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await expect(page.getByRole('textbox', { name: '描述学习目标', exact: true })).toBeVisible();
    await page.goto(workbenchURL(goal));
    const overview = page.getByRole('region', { name: '知识图谱全景', exact: true });
    await expect(overview).toBeVisible();
    await expect.poll(() => overview.locator('.react-flow__node').evaluateAll(elements => elements.filter(element => {
      const rect = element.getBoundingClientRect(), canvas = element.closest('.graph-canvas')!.getBoundingClientRect();
      return getComputedStyle(element).visibility === 'visible' && rect.right > canvas.left && rect.left < canvas.right && rect.bottom > canvas.top && rect.top < canvas.bottom;
    }).length), { message: `${viewport.width}px: every measured graph node must actually paint inside its canvas` }).toBe(7);
    await page.goto(workbenchURL(goal, session));
    await expect(page.getByLabel('向当前节点提问', { exact: true })).toBeEnabled();
    await page.goto(workbenchURL(goal, session, 'documents'));
    await expect(page.getByRole('region', { name: '工作台资料管理', exact: true })).toBeVisible();
    await page.goto(workbenchURL(goal, undefined, 'graph'));
  }
  expect(sent).toEqual([]);
});
