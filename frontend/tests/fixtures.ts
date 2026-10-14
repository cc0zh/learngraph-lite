import { expect, test as base } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';

// No browser request may leave the local fixture app, including model Markdown.
export const test = base.extend<{ externalRequests: string[] }>({
  externalRequests: [async ({ context }, use) => {
    const requests: string[] = [];
    await context.route('**/*', async route => {
      if (new URL(route.request().url()).origin === 'http://127.0.0.1:5173') await route.continue();
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

export function runDTO(runId: string, userText: string, status = 'completed', finalText = '模拟回答已完成') {
  return { run_id: runId, mode: 'teaching', user_text: userText, status, created_at: new Date().toISOString(),
    partial_text: '', final_text: finalText, tool_activity: {} };
}
