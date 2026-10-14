import { expect, learningGoal, test } from './fixtures';

test('P1: upload, persist, explicitly bind goal/node, locate/search/cite, unbind and delete', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const name = `资料验收-${Date.now()}.md`;
  const original = '# 错误与恢复\n错误与恢复需要显式查询状态，不自动重发。\n<img src="https://untrusted.invalid/x" onerror="alert(1)">\n';
  await page.goto('/documents');
  await expect(page.getByRole('heading', { name: '我的资料', exact: true })).toBeVisible();
  await page.getByLabel('选择资料文件').setInputFiles({ name, mimeType: 'text/markdown', buffer: Buffer.from(original) });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/documents') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '上传资料', exact: true }).click();
  const doc = await (await uploaded).json();
  expect(doc.document_id).toBeTruthy();
  await expect(page.getByRole('article').filter({ hasText: name })).toContainText('解析完成');
  const writes: string[] = [];
  page.on('request', r => { if (!['GET', 'HEAD'].includes(r.method())) writes.push(r.method()); });
  await page.reload();
  await expect(page.getByRole('link', { name, exact: true })).toBeVisible();
  expect(writes).toEqual([]);
  await page.getByRole('link', { name, exact: true }).click();
  await expect(page.getByRole('region', { name: '资料原文' })).toContainText('错误与恢复需要显式查询状态');
  await expect(page.locator('.documents-scope img')).toHaveCount(0);
  await page.getByLabel('绑定目标').selectOption(goal);
  await page.getByLabel('绑定节点').selectOption('n');
  await expect(page.getByRole('region', { name: '节点资料绑定' }).getByRole('button', { name: '绑定所选资料' })).toBeDisabled();
  await expect(page.getByRole('region', { name: '节点资料绑定' })).toContainText('请切换到“目标级”先绑定');
  await page.getByLabel('绑定节点').selectOption('');
  const bindings = page.getByRole('region', { name: '目标资料绑定' });
  await expect(bindings).toContainText('不是自动继承');
  await bindings.getByRole('button', { name: '绑定所选资料' }).click();
  await expect(bindings.getByRole('list', { name: '已绑定资料' })).toContainText(name);
  await page.getByLabel('绑定节点').selectOption('n');
  const nodeBindings = page.getByRole('region', { name: '节点资料绑定' });
  await nodeBindings.getByRole('button', { name: '绑定所选资料' }).click();
  await expect(nodeBindings.getByRole('list', { name: '已绑定资料' })).toContainText(name);
  writes.length = 0;
  await page.reload();
  await expect(nodeBindings.getByRole('list', { name: '已绑定资料' })).toContainText(name);
  expect(writes).toEqual([]);
  await nodeBindings.getByLabel('检索绑定资料').fill('错误与恢复');
  await nodeBindings.getByRole('button', { name: '检索资料', exact: true }).click();
  await expect(nodeBindings.getByRole('region', { name: '资料检索结果' })).toContainText('错误与恢复');
  await nodeBindings.getByRole('link', { name: '查看片段原文' }).first().click();
  await expect(page.locator('[data-selected-chunk="true"]')).toBeVisible();
  await page.goto(`/goals/${goal}/learn`);
  await page.getByLabel('向当前节点提问').fill('检索错误与恢复资料，使用原文引用解释');
  await page.getByRole('button', { name: '发送问题' }).click();
  const citations = page.locator('.assistant-message').last().getByRole('region', { name: '资料引用' });
  await expect(citations.getByRole('button', { name: /C1.*查看原文/ })).toBeVisible();
  await citations.getByRole('button', { name: /C1.*查看原文/ }).click();
  await expect(page).toHaveURL(new RegExp(`/documents/${doc.document_id}\\?`));
  await expect(page.locator('[data-selected-chunk="true"]')).toBeVisible();
  await page.getByLabel('绑定节点').selectOption('');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('region', { name: '目标资料绑定' }).getByRole('button', { name: '解绑资料' }).click();
  const nodeState = await request.get(`/api/goals/${goal}/document-bindings?node_id=n`);
  expect((await nodeState.json()).document_ids).toEqual([]);
  await page.goto(`/goals/${goal}/learn`);
  const restored = page.locator('.assistant-message').last().getByRole('region', { name: '资料引用' });
  // Completed run sources are snapshots: the click must revalidate live bindings.
  await restored.getByRole('button', { name: /C1.*查看原文/ }).click();
  await expect(restored).toContainText('409');
  await page.goto(`/documents/${doc.document_id}`);
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '删除资料', exact: true }).click();
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByRole('link', { name, exact: true })).toHaveCount(0);
  expect((await request.get(`/api/documents/${doc.document_id}`)).status()).toBe(404);
  await page.goto(`/goals/${goal}/learn`);
  await restored.getByRole('button', { name: /C1.*查看原文/ }).click();
  await expect(restored).toContainText('409');
});

test('P1: chunk pagination, deep link, unsupported format, reparse and responsive plain text', async ({ page, request }) => {
  const name = `分页-${Date.now()}.md`;
  const uploaded = await request.post('/api/documents', { multipart: { file: {
    name, mimeType: 'text/markdown', buffer: Buffer.from(Array.from({ length: 65 }, (_, i) => `# 第${i + 1}节\n分页原文 ${i + 1}`).join('\n')),
  } } });
  expect(uploaded.ok()).toBe(true);
  const doc = await uploaded.json();
  await expect.poll(async () => (await (await request.get(`/api/documents/${doc.document_id}`)).json()).status).toBe('ready');
  const chunks = await (await request.get(`/api/documents/${doc.document_id}/chunks?offset=50&limit=50`)).json();
  await page.goto(`/documents/${doc.document_id}?chunk=${encodeURIComponent(chunks.chunks[0].id)}`);
  await expect(page.locator('[data-selected-chunk="true"]')).toContainText('分页原文 51');
  await page.getByRole('button', { name: '上一页原文' }).click();
  await expect(page.getByRole('region', { name: '资料原文' })).toContainText('分页原文 1');
  await page.goto(`/documents/${doc.document_id}?chunk=unknown-chunk`);
  await expect(page.getByRole('alert')).toContainText('指定片段不存在');
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
  await page.goto('/documents');
  await page.getByLabel('选择资料文件').setInputFiles({ name: `unsupported-${Date.now()}.bin`, mimeType: 'application/octet-stream', buffer: Buffer.from('not supported') });
  const response = page.waitForResponse(r => r.url().endsWith('/api/documents') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '上传资料', exact: true }).click();
  const unsupported = await (await response).json();
  await page.goto(`/documents/${unsupported.document_id}`);
  await expect(page.getByRole('status').filter({ hasText: '不支持' }).first()).toBeVisible();
  await expect(page.getByText('支持 UTF-8 TXT / Markdown 和含文本的 PDF', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '重新解析', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '不支持' }).first()).toBeVisible();
});

test('P1: oversized uploads and parser failure have explicit recovery without refresh writes', async ({ page, request }) => {
  const tooLarge = await request.post('/api/documents', { multipart: { file: {
    name: 'too-large.txt', mimeType: 'text/plain', buffer: Buffer.alloc(10 * 1024 * 1024 + 1, 97),
  } } });
  expect(tooLarge.status()).toBe(413);
  await page.goto('/documents');
  await page.getByLabel('选择资料文件').setInputFiles({ name: 'too-large.txt', mimeType: 'text/plain', buffer: Buffer.alloc(10 * 1024 * 1024 + 1, 97) });
  await page.getByRole('button', { name: '上传资料', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('文件超过 10 MB');
  const response = await request.post('/api/documents', { multipart: { file: {
    name: `parse-failed-${Date.now()}.txt`, mimeType: 'text/plain', buffer: Buffer.from('a'.repeat(200001)),
  } } });
  expect(response.ok()).toBe(true);
  const doc = await response.json();
  await page.goto(`/documents/${doc.document_id}`);
  await expect(page.getByRole('status').filter({ hasText: '解析失败' })).toBeVisible();
  await expect(page.getByText('提取文本超过 20 万字符，请拆分文件。', { exact: false })).toBeVisible();
  const writes: string[] = [];
  page.on('request', r => { if (!['GET', 'HEAD'].includes(r.method())) writes.push(r.method()); });
  await page.reload();
  await expect(page.getByRole('button', { name: '重新解析', exact: true })).toBeEnabled();
  expect(writes).toEqual([]);
});
