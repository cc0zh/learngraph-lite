import type { APIRequestContext, Locator, Page } from '@playwright/test';
import type { Plan, Run } from '../src/types';
import { expect, learningGoal, openLearning, test, workbenchURL } from './fixtures';

const viewports = [
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'phone', width: 375, height: 812 },
] as const;
const areas = ['学习空间', '对话与内容', '图谱与节点'] as const;
type Area = typeof areas[number];
const controls = 'button, a[href], input:not([type="hidden"]), textarea, select, summary, [role="button"], [role="tab"]';

function panel(page: Page, area: Area) {
  return area === '对话与内容' ? page.locator('.wb-main')
    : page.getByRole('complementary', { name: area, exact: true });
}
async function reveal(page: Page, area: Area) {
  const nav = page.getByRole('navigation', { name: '工作台区域', exact: true });
  if (await nav.isVisible()) await nav.getByRole('button', { name: area, exact: true }).click();
  await expect(panel(page, area)).toBeVisible();
  return panel(page, area);
}
function posts(page: Page) {
  const sent: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST') sent.push(new URL(request.url()).pathname);
  });
  return sent;
}

// All state comes from the business fixture API, never intercepted DTOs or fake UI data.
async function businessGraph(request: APIRequestContext, title: string) {
  const created = await request.post('/api/goals', { data: { title } });
  expect(created.ok()).toBe(true);
  const initial: Plan = await created.json();
  const confirmed = await request.post(`/api/goals/${initial.goal_id}/confirm`, { data: { expected_version: initial.version } });
  expect(confirmed.ok()).toBe(true);
  const saved: Plan = await confirmed.json();
  const edited = await request.patch(`/api/goals/${initial.goal_id}/graph`, { data: {
    expected_version: saved.version,
    nodes: [
      { id: 'one', title: '分块与上下文', explanation: '比较分块粒度', learning_outcome: '解释上下文边界', estimated_minutes: 20, priority: 3 },
      { id: 'two', title: '检索与证据', explanation: '定位检索证据', learning_outcome: '说明证据来源', estimated_minutes: 30, priority: 2 },
    ], edges: [{ source: 'one', target: 'two', kind: 'prerequisite' }],
  } });
  expect(edited.ok()).toBe(true);
  const draft: Plan = await edited.json();
  const published = await request.post(`/api/goals/${initial.goal_id}/graph/publish`, { data: {
    expected_version: draft.version, expected_revision: draft.graph!.revision,
  } });
  expect(published.ok()).toBe(true);
  return initial.goal_id;
}
async function savedConversation(request: APIRequestContext, goal: string, node: string, title: string, question: string) {
  const session = crypto.randomUUID();
  const created = await request.post('/api/conversations', { data: { session_id: session, goal_id: goal, node_id: node, title } });
  expect(created.ok()).toBe(true);
  const started = await request.post(`/api/sessions/${session}/runs`, { data: {
    request_id: crypto.randomUUID(), goal_id: goal, node_id: node, mode: 'teaching', user_text: question,
  } });
  expect(started.ok()).toBe(true);
  const run: Run = await started.json();
  await expect.poll(async () => {
    const response = await request.get(`/api/runs/${run.run_id}`);
    expect(response.ok()).toBe(true);
    return ((await response.json()) as Run).status;
  }).toBe('completed');
  return session;
}

async function controlBoxes(scope: Locator) {
  return scope.locator(controls).evaluateAll(elements => elements.flatMap(element => {
    // ReactFlow owns the scale and hit geometry of controls inside its canvas.
    if (element.closest('.react-flow')) return [];
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    if (!element.getClientRects().length || !rect.width || !rect.height || style.visibility === 'hidden') return [];
    return [{ name: element.getAttribute('aria-label') || element.textContent?.trim().replace(/\s+/g, ' ').slice(0, 70) || element.tagName,
      height: rect.height, left: rect.left, right: rect.right }];
  }));
}
async function noOverflow(scope: Locator, label: string) {
  const box = await scope.evaluate(element => {
    const rect = element.getBoundingClientRect();
    return { left: rect.left, right: rect.right, viewport: innerWidth, scroll: element.scrollWidth, client: element.clientWidth };
  });
  expect.soft(box.left, `${label}: left edge`).toBeGreaterThanOrEqual(-1);
  expect.soft(box.right, `${label}: right edge`).toBeLessThanOrEqual(box.viewport + 1);
  expect.soft(box.scroll, `${label}: internal horizontal overflow`).toBeLessThanOrEqual(box.client + 1);
  const outside = (await controlBoxes(scope)).filter(control => control.left < box.left - 1 || control.right > box.right + 1);
  expect.soft(outside, `${label}: actions must stay inside the panel`).toEqual([]);
}

// Inspect rendered paint, not CSS variable names or implementation-specific token files.
async function palette(page: Page) {
  return page.locator('.workbench').evaluate(root => {
    let accent = false;
    const bluePurple: string[] = [], brightOrangeText: string[] = [];
    const luminance = (rgb: number[]) => rgb.map(value => value / 255).map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
      .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
    for (const element of [root, ...root.querySelectorAll('*')]) {
      const style = getComputedStyle(element), rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
      const ownText = [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent?.trim());
      const paints = [style.backgroundColor, style.backgroundImage];
      if (ownText) paints.push(style.color);
      for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
        if (parseFloat(style.getPropertyValue(`border-${side.toLowerCase()}-width`)) > 0) paints.push(style.getPropertyValue(`border-${side.toLowerCase()}-color`));
      }
      if (element instanceof SVGElement) paints.push(style.fill, style.stroke);
      for (const paint of paints) for (const match of paint.matchAll(/rgba?\(([^)]+)\)/g)) {
        const values = match[1].split(/[,\s/]+/).filter(Boolean).map(Number), rgb = values.slice(0, 3);
        if (values.length > 3 && values[3] === 0) continue;
        if (rgb.every((value, index) => value === [234, 76, 22][index])) accent = true;
        const [r, g, b] = rgb.map(value => value / 255), high = Math.max(r, g, b), low = Math.min(r, g, b), delta = high - low;
        if (delta < 0.1 || delta / (high || 1) < 0.2) continue; // neutral ink/paper is not a hue violation
        let hue = high === r ? ((g - b) / delta) % 6 : high === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
        hue = (hue * 60 + 360) % 360;
        if (hue >= 200 && hue <= 320) bluePurple.push(`${element.tagName}: ${paint}`);
      }
      const text = style.color.match(/^rgba?\(([^)]+)\)/);
      if (ownText && text) {
        const rgb = text[1].split(/[,\s/]+/).filter(Boolean).slice(0, 3).map(Number);
        if (rgb[0] > rgb[1] * 1.5 && rgb[1] > rgb[2] && luminance(rgb) >= luminance([234, 76, 22])) {
          brightOrangeText.push(`${element.textContent?.trim().slice(0, 50)}: ${style.color}`);
        }
      }
    }
    return { accent, bluePurple: [...new Set(bluePurple)], brightOrangeText: [...new Set(brightOrangeText)] };
  });
}

for (const viewport of viewports) {
  test(`editorial: ${viewport.name} root and each panel have no horizontal overflow`, async ({ page, request }) => {
    await page.setViewportSize(viewport);
    await openLearning(page, request, await learningGoal(request));
    for (const area of areas) {
      const visible = await reveal(page, area);
      await noOverflow(page.locator('html'), `${viewport.name} document`);
      await noOverflow(page.locator('.workbench'), `${viewport.name} root`);
      await noOverflow(visible, `${viewport.name} ${area}`);
    }
  });

  test(`editorial: ${viewport.name} interactive controls are at least 44px high outside ReactFlow`, async ({ page, request }) => {
    await page.setViewportSize(viewport);
    await openLearning(page, request, await learningGoal(request));
    const small: { area: string; name: string; height: number }[] = [];
    for (const area of areas) {
      await reveal(page, area);
      const boxes = await controlBoxes(page.locator('.workbench'));
      expect(boxes.length, `${area} must expose real controls`).toBeGreaterThan(0);
      small.push(...boxes.filter(box => box.height < 44 - 0.1).map(({ name, height }) => ({ area, name, height })));
    }
    await reveal(page, '对话与内容');
    await page.getByRole('tab', { name: '学习内容', exact: true }).click();
    small.push(...(await controlBoxes(panel(page, '对话与内容'))).filter(box => box.height < 44 - 0.1)
      .map(({ name, height }) => ({ area: '学习内容', name, height })));
    expect(small, 'Visible controls need 44px hit heights (including links, tabs and summaries)').toEqual([]);
  });
}

test('editorial: the main paper background is rgb(247,245,240)', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.workbench')).toBeVisible();
  const canvas = await page.locator('.workbench').evaluate(element => {
    for (let current: Element | null = element; current; current = current.parentElement) {
      const color = getComputedStyle(current).backgroundColor;
      if (color !== 'transparent' && color !== 'rgba(0, 0, 0, 0)') return color;
    }
    return 'transparent';
  });
  expect(canvas, 'The painted workbench canvas, whether supplied by the root or an ancestor').toBe('rgb(247, 245, 240)');
});

test('editorial: the rendered accent includes #ea4c16', async ({ page, request }) => {
  await openLearning(page, request, await learningGoal(request));
  expect((await palette(page)).accent, 'The brand orange must be rendered, not merely declared as an unused token').toBe(true);
});

test('editorial: visible workbench and graph paints contain no saturated blue or purple', async ({ page, request }) => {
  await openLearning(page, request, await learningGoal(request));
  const found: string[] = [];
  for (const area of areas) {
    await reveal(page, area);
    found.push(...(await palette(page)).bluePurple);
  }
  expect([...new Set(found)], 'Blue/purple paint must be replaced by the editorial palette').toEqual([]);
});

test('editorial: orange text uses a darker tone than the brand accent', async ({ page, request }) => {
  await openLearning(page, request, await learningGoal(request));
  expect((await palette(page)).brightOrangeText, 'Keep bright #ea4c16 for accents; orange text needs a darker ink tone').toEqual([]);
});

test('editorial: new conversation, goal-mode switches and refresh never POST at any viewport', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const sent = posts(page);
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await openLearning(page, request, goal);
    await reveal(page, '学习空间');
    await page.getByRole('button', { name: '新对话', exact: true }).click();
    await reveal(page, '对话与内容');
    await expect(page.getByRole('textbox', { name: '发送消息', exact: true })).toBeVisible();
    await page.reload();
    await reveal(page, '对话与内容');
    await expect(page.getByRole('textbox', { name: '发送消息', exact: true })).toBeVisible();
    await reveal(page, '对话与内容');
    await page.getByRole('button', { name: '创建目标', exact: true }).click();
    await reveal(page, '对话与内容');
    await expect(page.getByRole('region', { name: '创建目标', exact: true })).toBeVisible();
    await page.reload();
    await reveal(page, '对话与内容');
    await expect(page.getByLabel('描述学习目标')).toBeVisible();
    expect(sent, `${viewport.name}: navigation/restore must be read-only`).toEqual([]);
  }
});

test('editorial: phone can switch all three areas without changing conversation scope or drafts', async ({ page, request }) => {
  await page.setViewportSize(viewports[2]);
  const goal = await businessGraph(request, `手机三栏-${crypto.randomUUID()}`);
  const title = `手机原会话-${crypto.randomUUID()}`;
  const session = await savedConversation(request, goal, 'one', title, '手机原会话的已保存问题');
  const sent = posts(page);
  await page.goto(workbenchURL(goal, session));
  await reveal(page, '对话与内容');
  await expect(page.getByLabel('当前会话记录')).toContainText('手机原会话的已保存问题');
  await page.getByLabel('向当前节点提问').fill('手机未发送的草稿');
  await reveal(page, '图谱与节点');
  await page.getByRole('region', { name: '浏览图谱节点' }).getByRole('button', { name: '检索与证据', exact: true }).click();
  await expect(page.getByRole('region', { name: '所查看节点' })).toContainText('检索与证据');
  await reveal(page, '学习空间');
  await expect(panel(page, '学习空间').getByText(title, { exact: true })).toBeVisible();
  await reveal(page, '对话与内容');
  await expect(page.getByLabel('向当前节点提问')).toHaveValue('手机未发送的草稿');
  await expect(page.getByLabel('当前对话范围')).toContainText('分块与上下文');
  expect(new URL(page.url()).searchParams.get('session')).toBe(session);
  await page.reload();
  await reveal(page, '对话与内容');
  await expect(page.getByLabel('向当前节点提问')).toHaveValue('手机未发送的草稿');
  expect(sent).toEqual([]);
});

test('editorial: a long Chinese goal keeps its full accessible name and never pushes actions outside panels', async ({ page, request }) => {
  const title = `面向中文长篇学习资料的知识图谱与证据检索实践${'完整保留目标名称并核对操作边界'.repeat(5)}-${crypto.randomUUID()}`;
  const goal = await businessGraph(request, title);
  const session = await savedConversation(request, goal, 'one', '长目标会话', '核对长目标的学习范围');
  const sent = posts(page);
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto(workbenchURL(goal, session));
    await expect(page.getByLabel('向当前节点提问')).toBeEnabled();
    const space = await reveal(page, '学习空间');
    // The directory uses native details/summary, which Playwright does not expose as role=button.
    const goalControl = space.locator('summary').filter({ hasText: title });
    await expect.soft(goalControl, `${viewport.name}: full goal name must remain accessible`).toBeVisible();
    await expect.soft(goalControl).toHaveAccessibleName(new RegExp(title));
    await expect(page.getByLabel('当前对话范围').getByRole('heading', { level: 1 })).toHaveAccessibleName(title);
    for (const area of areas) await noOverflow(await reveal(page, area), `${viewport.name} long-title ${area}`);
    await noOverflow(page.locator('html'), `${viewport.name} long-title document`);
  }
  const response = await request.get(`/api/goals/${goal}`);
  expect(response.ok()).toBe(true);
  expect(((await response.json()) as Plan).goal.title).toBe(title);
  expect(sent).toEqual([]);
});

test('editorial: reduced-motion leaves real content, scope and the composer visible', async ({ page, request }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const goal = await learningGoal(request);
  const question = '减少动态效果时仍能阅读的已保存问题';
  const session = await savedConversation(request, goal, 'n', '静态阅读会话', question);
  const sent = posts(page);
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto(workbenchURL(goal, session));
    for (const area of areas) await reveal(page, area);
    await reveal(page, '对话与内容');
    const history = page.getByLabel('当前会话记录');
    await expect(history).toBeVisible();
    await expect(history).toContainText(question);
    await expect(page.getByLabel('当前对话范围')).toContainText('错误与恢复');
    await expect(page.getByLabel('向当前节点提问')).toBeVisible();
    await expect(page.getByLabel('向当前节点提问')).toBeEnabled();
    for (const content of [history, page.getByLabel('当前对话范围'), page.getByLabel('向当前节点提问')]) {
      const hiddenAncestors = await content.evaluate(element => {
        const hidden: string[] = [];
        for (let current: Element | null = element; current; current = current.parentElement) {
          const style = getComputedStyle(current);
          if (Number(style.opacity) <= 0.01 || style.visibility === 'hidden' || style.display === 'none') hidden.push(current.tagName);
        }
        return hidden;
      });
      expect(hiddenAncestors, `${viewport.name}: reduced-motion must not leave content awaiting an entrance animation`).toEqual([]);
    }
  }
  expect(sent).toEqual([]);
});

test('editorial: real published graph, viewed node and independent saved conversations stay distinguishable', async ({ page, request }) => {
  await page.setViewportSize(viewports[0]);
  const goal = await businessGraph(request, `真实图谱-${crypto.randomUUID()}`);
  const first = await savedConversation(request, goal, 'one', '分块独立会话', '只属于分块会话的问题');
  const second = await savedConversation(request, goal, 'two', '检索独立会话', '只属于检索会话的问题');
  const sent = posts(page);
  await page.goto(workbenchURL(goal, first));
  await expect(panel(page, '图谱与节点')).toContainText('已发布');
  const nodes = page.getByRole('region', { name: '浏览图谱节点', exact: true });
  await expect(nodes.getByRole('button', { name: '分块与上下文' })).toBeVisible();
  await expect(nodes.getByRole('button', { name: '分块与上下文' })).toContainText('对话焦点');
  await expect(nodes.getByRole('button', { name: '检索与证据', exact: true })).toBeVisible();
  await expect(page.getByLabel('当前会话记录')).toContainText('只属于分块会话的问题');
  await expect(page.getByLabel('当前会话记录')).not.toContainText('只属于检索会话的问题');
  await nodes.getByRole('button', { name: '检索与证据', exact: true }).click();
  await expect(page.getByRole('region', { name: '所查看节点' })).toContainText('检索与证据');
  await expect(page.getByLabel('当前对话范围')).toContainText('分块与上下文');
  expect(new URL(page.url()).searchParams.get('session')).toBe(first);
  await page.goto(workbenchURL(goal, second));
  await expect(page.getByLabel('当前对话范围')).toContainText('检索与证据');
  await expect(page.getByLabel('当前会话记录')).toContainText('只属于检索会话的问题');
  await expect(page.getByLabel('当前会话记录')).not.toContainText('只属于分块会话的问题');
  await page.reload();
  await expect(page.getByLabel('当前会话记录')).toContainText('只属于检索会话的问题');
  expect(sent).toEqual([]);
});

test('editorial: short viewports and a long conversation title keep the composer vertically reachable', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const session = crypto.randomUUID();
  expect((await request.post('/api/conversations', { data: {
    session_id: session, goal_id: goal, node_id: 'n', title: '保留完整的独立会话名称'.repeat(8),
  } })).ok()).toBe(true);
  const sent = posts(page);
  for (const viewport of [{ width: 568, height: 320 }, { width: 390, height: 550 }, { width: 1024, height: 500 }]) {
    await page.setViewportSize(viewport);
    await page.goto(workbenchURL(goal, session));
    await expect(panel(page, '对话与内容')).toBeVisible();
    const input = page.getByLabel('向当前节点提问');
    await input.scrollIntoViewIfNeeded({ timeout: 3000 });
    await input.click({ timeout: 3000 });
    await expect(input).toBeFocused();
    const bounds = await input.boundingBox();
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height);
    await input.fill('短屏仍能保留的输入草稿');
    await expect(input).toHaveValue('短屏仍能保留的输入草稿');
  }
  expect(sent).toEqual([]);
});
