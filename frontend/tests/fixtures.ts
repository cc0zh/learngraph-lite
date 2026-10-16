import { expect, test as base } from '@playwright/test';
import type { APIRequestContext, Page } from '@playwright/test';

// No browser request may leave the local fixture app, including model Markdown.
export const test = base.extend<{ externalRequests: string[] }>({
  externalRequests: [async ({ context, baseURL }, use) => {
    const requests: string[] = [];
    await context.route('**/*', async route => {
      if (new URL(route.request().url()).origin === new URL(baseURL!).origin) await route.continue();
      else { requests.push(route.request().url()); await route.abort('blockedbyclient'); }
    });
    await use(requests);
    expect(requests, 'Unexpected external requests (blocked before sending)').toEqual([]);
  }, { auto: true }],
});
export { expect };

export async function learningGoal(request: APIRequestContext, nodeId = 'n', publish = true) {
  const created = await request.post('/api/goals', { data: { title: 'P0 恢复回归' } });
  expect(created.ok()).toBe(true);
  const plan = await created.json();
  const goal = plan.goal_id as string;
  const confirmed = await request.post(`/api/goals/${goal}/confirm`, { data: { expected_version: plan.version } });
  expect(confirmed.ok()).toBe(true);
  const version = (await confirmed.json()).version;
  const drafted = await request.patch(`/api/goals/${goal}/graph`, { data: { expected_version: version,
    nodes: [{ id: nodeId, title: '错误与恢复', explanation: '识别失败', learning_outcome: '显式恢复', estimated_minutes: 20, priority: 3 }], edges: [] } });
  expect(drafted.ok()).toBe(true);
  const draft = await drafted.json();
  if (publish) {
    const published = await request.post(`/api/goals/${goal}/graph/publish`, { data: { expected_version: draft.version, expected_revision: draft.graph.revision } });
    expect(published.ok()).toBe(true);
  }
  return goal;
}

// Metadata setup deliberately does not start teaching: fault tests own the first POST.
// The goal is already a unique UUID; reusing it for node n keeps mock scopes stable.
// Existing legacy-run tests navigate their original session explicitly instead.
export async function openLearning(page: Page, request: APIRequestContext, goal: string, node = 'n') {
  const session = node === 'n' ? goal : crypto.randomUUID();
  const existing = await request.get(`/api/conversations/${encodeURIComponent(session)}`);
  if (existing.status() === 404) {
    const created = await request.post('/api/conversations', { data: {
      session_id: session, title: '测试学习会话', goal_id: goal, node_id: node,
    } });
    expect(created.ok()).toBe(true);
  } else expect(existing.ok()).toBe(true);
  await page.goto(workbenchURL(goal, session));
  await expect(page.getByLabel('向当前节点提问')).toBeEnabled();
  return session;
}

export function workbenchURL(goal?: string, session?: string, tool?: string) {
  const params = new URLSearchParams();
  if (goal) params.set('goal', goal);
  if (session) params.set('session', session);
  if (tool) params.set('tool', tool);
  return `/${params.size ? `?${params}` : ''}`;
}

export async function learningContent(page: Page) {
  await page.getByRole('tab', { name: '学习内容', exact: true }).click();
}

export function runDTO(runId: string, userText: string, status = 'completed', finalText = '模拟回答已完成') {
  return { run_id: runId, mode: 'teaching', user_text: userText, status, created_at: new Date().toISOString(),
    partial_text: '', final_text: finalText, tool_activity: {} };
}
