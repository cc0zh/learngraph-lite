import type { Page } from '@playwright/test';
import type { PublicLesson } from '../src/lessons/types';
import { expect, learningGoal, runDTO, test } from './fixtures';

function lessonDTO(goal: string, id = 'lesson-current', version = 1): PublicLesson {
  return { id, goal_id: goal, node_id: 'n', graph_content_revision: 1, schema_version: 1, version,
    title: `学习包测试版本 ${version}`, markdown: '## 安全章节\n章节内容 [C1]', source_mode: 'general', outdated: false,
    citation_map: {}, unverified_citation_ids: [], components: [
      { id: 'overview', kind: 'markdown', props: { text: '阅读内容' } },
      { id: 'steps', kind: 'stepper', props: { steps: [
        { title: '第一步', description: '说明目标', slots: { text: '步骤正文' } },
        { title: '第二步', description: '验证结果', slots: {} },
      ] } },
      { id: 'compare', kind: 'comparison_table', props: { columns: ['方法', '证据'], rows: [['阅读', '概念'], ['实践', '结果']] } },
    ] };
}
type LessonDTO = ReturnType<typeof lessonDTO>;

test('P1 lessons: delayed old list cannot replace a newer generated lesson or selection', async ({ page, request }) => {
  const goal = await learningGoal(request);
  await page.goto(`/goals/${goal}/learn`);
  const panel = page.locator('.lesson-panel');
  await panel.getByRole('button', { name: '生成学习包', exact: true }).click();
  await expect(panel.getByRole('article', { name: '学习包详情' })).toContainText('版本 1');
  let held = false;
  let release!: () => void;
  let served!: () => void;
  const ready = new Promise<void>(resolve => { release = resolve; });
  const delivered = new Promise<void>(resolve => { served = resolve; });
  await page.route(`**/api/goals/${goal}/nodes/n/lessons`, async route => {
    if (route.request().method() !== 'GET' || held) { await route.continue(); return; }
    const snapshot = await route.fetch(); held = true;
    await ready; await route.fulfill({ response: snapshot }); served();
  });
  await panel.getByRole('button', { name: '刷新学习包与状态' }).click();
  await expect.poll(() => held).toBe(true);
  await panel.getByRole('button', { name: '重新生成学习包', exact: true }).click();
  await expect(panel.getByRole('article', { name: '学习包详情' })).toContainText('版本 2');
  const selected = await panel.getByRole('combobox', { name: '学习包版本' }).inputValue();
  release(); await delivered;
  await expect(panel.getByRole('combobox', { name: '学习包版本' })).toHaveValue(selected);
  await expect(panel.getByRole('combobox', { name: '学习包版本' }).locator('option')).toHaveCount(2);
});
const publicExercise = (goal: string) => ({ id: 'public-question', goal_id: goal, node_id: 'n', graph_content_revision: 1,
  prompt: '只有公开题目，不内嵌答案 [C1]', options: [{ id: 'a', text: '选项 A' }, { id: 'b', text: '选项 B' }], citation_map: {} });

async function mockLessons(page: Page, goal: string, lessons: LessonDTO[], exercise?: ReturnType<typeof publicExercise>) {
  await page.route(`**/api/goals/${goal}/nodes/n/lessons`, route => route.fulfill({ json: { lessons } }));
  await page.route(`**/api/goals/${goal}/lessons/*`, route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1);
    return route.fulfill({ json: lessons.find(lesson => lesson.id === id) });
  });
  await page.route(`**/api/goals/${goal}/nodes/n/exercises`, route => route.fulfill({ json: { exercises: exercise ? [exercise] : [], feedback: {} } }));
  if (exercise) {
    await page.route(`**/api/goals/${goal}/exercises/${exercise.id}`, route => route.fulfill({ json: exercise }));
    await page.route(`**/api/goals/${goal}/exercises/${exercise.id}/feedback`, route => route.fulfill({ json: { feedback: null } }));
  }
  await page.route('**/api/sessions/*/runs', route => route.fulfill({ json: [] }));
}

function eventACK(lesson: LessonDTO, body: Record<string, unknown>) {
  const { event_id, ...fields } = body;
  return { event: { id: event_id, package_id: lesson.id, ...fields } };
}

test('P1 lessons: fixture generates all four components from existing public questions; only answers change mastery', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const generated = await request.post(`/api/goals/${goal}/nodes/n/exercises`, { data: {
    session_id: crypto.randomUUID(), request_id: crypto.randomUUID(), count: 1, purpose: 'practice',
  } });
  expect(generated.ok()).toBe(true);
  const exerciseRun = await generated.json();
  await expect.poll(async () => (await (await request.get(`/api/runs/${exerciseRun.run_id}`)).json()).status).toBe('completed');
  const questions = await (await request.get(`/api/goals/${goal}/nodes/n/exercises`)).json();
  const question = questions.exercises[0];
  const publicQuestion = await (await request.get(`/api/goals/${goal}/exercises/${question.id}`)).json();
  expect(publicQuestion).not.toHaveProperty('correct_option_id');
  expect(publicQuestion).not.toHaveProperty('explanation');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/goals/${goal}/learn`);
  const panel = page.locator('.lesson-panel');
  await panel.getByText('选择已有题目加入学习包（最多 3 题）').click();
  await panel.getByRole('checkbox', { name: '加入题目 1' }).check();
  await panel.getByRole('button', { name: '生成学习包', exact: true }).click();
  const detail = panel.getByRole('article', { name: '学习包详情' });
  await expect(detail).toContainText('当前节点学习包（fixture）');
  for (const kind of ['markdown', 'quiz_choice', 'stepper', 'comparison_table']) {
    await expect(detail.locator(`[data-component-kind="${kind}"]`)).toHaveCount(1);
  }
  await expect(panel.locator('.lesson-run').first()).toContainText('已完成');
  const saved = await (await request.get(`/api/goals/${goal}/nodes/n/lessons`)).json();
  const publicLesson = await (await request.get(`/api/goals/${goal}/lessons/${saved.lessons[0].id}`)).json();
  expect(publicLesson.components.find((component: { kind: string }) => component.kind === 'quiz_choice').props).toEqual({ exercise_id: question.id });
  const posts: string[] = [];
  page.on('request', req => { if (req.method() === 'POST') posts.push(new URL(req.url()).pathname); });
  await detail.locator('.lesson-block').first().getByRole('button', { name: '标记已读', exact: true }).click();
  await expect(detail).toContainText('已读（已保存）');
  await detail.getByRole('button', { name: '下一步', exact: true }).click();
  await expect(detail).toContainText('步骤已保存');
  await expect(detail).toContainText('步骤 2 / 2');
  await expect(page.locator('.progress-card')).toContainText('0 个有效样本');
  expect(posts).toHaveLength(2);
  expect(posts.every(path => path.endsWith('/events'))).toBe(true);
  const quiz = detail.locator('[data-component-kind="quiz_choice"]');
  await quiz.getByRole('radio', { name: '解释原理并完成一个例子' }).check();
  await quiz.getByRole('button', { name: '提交答案', exact: true }).click();
  await expect(quiz).toContainText('回答正确');
  await expect(page.locator('.progress-card')).toContainText('1 个有效样本');
  posts.length = 0;
  await page.reload();
  await expect(detail).toContainText('步骤 2 / 2');
  await expect(quiz).toContainText('回答正确');
  await expect(quiz.getByRole('button', { name: '提交答案', exact: true })).toBeDisabled();
  expect(posts).toEqual([]);
  expect(errors).toEqual([]);
});

test('P1 lessons: no fabricated quiz without existing exercises, and the three tabs fit narrow screens', async ({ page, request }) => {
  const goal = await learningGoal(request);
  await page.goto(`/goals/${goal}/learn`);
  const panel = page.locator('.lesson-panel');
  await panel.getByRole('button', { name: '生成学习包', exact: true }).click();
  const detail = panel.getByRole('article', { name: '学习包详情' });
  await expect(detail).toContainText('当前节点学习包（fixture）');
  await expect(detail.locator('[data-component-kind="quiz_choice"]')).toHaveCount(0);
  await expect(detail.locator('[data-component-kind]')).toHaveCount(3);
  for (const width of [320, 375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    if (width < 768) {
      for (const name of ['节点对话', '练习与进度', '学习包']) {
        await page.getByRole('tab', { name, exact: true }).click();
        await expect(page.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true');
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      }
      await expect(detail).toBeVisible();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
});

test('P1 lessons: schema 0 and outdated packages are read-only; unsupported components and executable Markdown are safe', async ({ page, request, externalRequests }) => {
  const goal = await learningGoal(request);
  const current = lessonDTO(goal, 'safe-current', 3);
  current.markdown = '安全正文 **仍可读** ![tracker](https://untrusted.invalid/lesson.png) <img src="https://untrusted.invalid/raw.png" onerror="alert(1)"> [链接](https://untrusted.invalid/run)';
  // Deliberately bypass the public schema to test the browser's safe fallback boundary.
  const malformed = [null, { id: 'legacy', kind: 'choice_card', props: { correct: 'b' } },
    { id: 'code', kind: 'javascript', props: { code: 'window.alert(1)' } },
    { id: 'unsafe', kind: 'markdown', props: { text: 'not executable', onClick: 'alert(1)' } }];
  current.components.push(...malformed as unknown as LessonDTO['components']);
  const exercise = publicExercise(goal);
  const outdated = { ...lessonDTO(goal, 'outdated', 2), outdated: true, components: [
    ...lessonDTO(goal).components, { id: 'quiz', kind: 'quiz_choice', props: { exercise_id: exercise.id } },
  ] } as LessonDTO;
  const legacy = { ...outdated, id: 'legacy-schema', version: 1, schema_version: 0, outdated: false };
  await mockLessons(page, goal, [current, outdated, legacy], exercise);
  const writes: string[] = [];
  page.on('request', req => { if (req.method() === 'POST') writes.push(req.url()); });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/goals/${goal}/learn`);
  const panel = page.locator('.lesson-panel');
  const detail = panel.getByRole('article', { name: '学习包详情' });
  await expect(detail).toContainText('仍可读');
  await expect(detail.getByText('不支持或无效的学习组件（仅安全占位，不执行内容）。', { exact: true })).toHaveCount(4);
  await expect(detail.locator('img, a, script, iframe')).toHaveCount(0);
  for (const id of ['outdated', 'legacy-schema']) {
    await panel.getByRole('combobox', { name: '学习包版本' }).selectOption(id);
    await expect(detail).toContainText('只读，不接受作答、事件或解释');
    await expect(detail.getByRole('button', { name: '下一步', exact: true })).toBeDisabled();
    for (const button of await detail.getByRole('button', { name: '让 Agent 解释', exact: true }).all()) await expect(button).toBeDisabled();
    await expect(detail.getByRole('radio')).toHaveCount(2);
    for (const radio of await detail.getByRole('radio').all()) await expect(radio).toBeDisabled();
    await expect(detail.getByRole('button', { name: '提交答案', exact: true })).toBeDisabled();
    await panel.getByRole('button', { name: '刷新学习包与状态' }).click();
    await expect(panel.getByRole('combobox', { name: '学习包版本' })).toHaveValue(id);
  }
  await page.reload();
  await expect(panel.getByRole('combobox', { name: '学习包版本' })).toHaveValue('legacy-schema');
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
  expect(externalRequests).toEqual([]);
});

for (const failure of ['not-delivered', 'response-lost', 'mismatched-ack'] as const) {
  test(`P1 lessons: ${failure} ACK preserves event, slot and request; refresh never posts or invokes the Agent`, async ({ page, request }) => {
    const goal = await learningGoal(request);
    const lesson = lessonDTO(goal);
    await mockLessons(page, goal, [lesson]);
    const events: Record<string, unknown>[] = [];
    const commands: Record<string, unknown>[] = [];
    const acceptedEvents = new Map<unknown, ReturnType<typeof eventACK>>();
    await page.route(`**/api/goals/${goal}/lessons/${lesson.id}/events`, async route => {
      const body = route.request().postDataJSON(); events.push(body);
      if (events.length === 1 && failure !== 'mismatched-ack') {
        if (failure === 'response-lost') acceptedEvents.set(body.event_id, eventACK(lesson, body));
        await route.abort('failed'); return;
      }
      const ack = acceptedEvents.get(body.event_id) || eventACK(lesson, body);
      if (events.length === 1) ack.event.id = 'wrong-event';
      await route.fulfill({ json: ack });
    });
    await page.route('**/api/sessions/*/runs', route => {
      if (route.request().method() !== 'POST') return route.fulfill({ json: [] });
      commands.push(route.request().postDataJSON());
      return route.fulfill({ status: 202, json: { ...runDTO('ack-recovered', '', 'completed', '已恢复解释'), mode: 'explanation' } });
    });
    await page.goto(`/goals/${goal}/learn`);
    const panel = page.locator('.lesson-panel');
    const chapter = panel.getByRole('article', { name: '学习包详情' }).locator('.lesson-block').first();
    await chapter.getByRole('button', { name: '让 Agent 解释', exact: true }).click();
    await expect(chapter.getByRole('alert')).toContainText('事件尚未确认');
    expect(commands).toEqual([]);
    expect(events).toHaveLength(1);
    const key = `learngraph:lesson:${goal}:${lesson.id}:1:chapter:explanation:component`;
    const saved = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), key);
    await panel.getByRole('button', { name: '刷新学习包与状态' }).click();
    await page.reload();
    await expect(chapter).toContainText('尚未确认');
    expect(events).toHaveLength(1);
    expect(commands).toEqual([]);
    await chapter.getByRole('button', { name: '恢复此解释', exact: true }).click();
    await expect(panel.getByRole('article', { name: '组件解释' })).toContainText('已恢复解释');
    expect(events).toHaveLength(2);
    expect(events[1]).toEqual(events[0]);
    expect(commands).toEqual([{ request_id: saved.requestId, mode: 'explanation', goal_id: goal, node_id: 'n',
      source_event_id: saved.event.event_id, explanation_slot: saved.slot }]);
    expect(commands[0]).not.toHaveProperty('user_text');
  });
}

for (const failure of ['not-delivered', 'response-lost'] as const) {
  test(`P1 lessons: ${failure} explanation response recovers same command; failed retry keeps scope, explicit re-explanation changes slot`, async ({ page, request }) => {
    const goal = await learningGoal(request);
    const lesson = lessonDTO(goal);
    await mockLessons(page, goal, [lesson]);
    const events: Record<string, unknown>[] = [];
    await page.route(`**/api/goals/${goal}/lessons/${lesson.id}/events`, route => {
      const body = route.request().postDataJSON(); events.push(body);
      return route.fulfill({ json: eventACK(lesson, body) });
    });
    const commands: Record<string, unknown>[] = [];
    const histories = new Map<string, ReturnType<typeof runDTO>[]>();
    await page.route('**/api/sessions/*/runs', async route => {
      const session = new URL(route.request().url()).pathname;
      if (route.request().method() !== 'POST') { await route.fulfill({ json: histories.get(session) || [] }); return; }
      const body = route.request().postDataJSON(); commands.push(body);
      if (commands.length === 1 && failure === 'not-delivered') { await route.abort('failed'); return; }
      const runs = histories.get(session) || [];
      let run = runs.find(run => run.run_id === (body.retry_of_run_id ? 'failed-retry' : commands.length > 3 ? 'explicit-again' : 'failed-root'));
      if (!run) {
        const root = !body.retry_of_run_id && commands.length <= 2;
        run = { ...runDTO(root ? 'failed-root' : body.retry_of_run_id ? 'failed-retry' : 'explicit-again', '', root ? 'failed' : 'completed', root ? '' : '解释已完成'), mode: 'explanation',
          ...(root ? { error: '模拟解释失败' } : {}) };
        histories.set(session, [...runs, run]);
      }
      if (commands.length === 1) await route.abort('failed');
      else await route.fulfill({ status: 202, json: run });
    });
    await page.goto(`/goals/${goal}/learn`);
    const panel = page.locator('.lesson-panel');
    const chapter = panel.getByRole('article', { name: '学习包详情' }).locator('.lesson-block').first();
    await chapter.getByRole('button', { name: '让 Agent 解释', exact: true }).click();
    const pending = panel.getByRole('region', { name: '未确认请求恢复' });
    await expect(pending).toBeVisible();
    await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeEnabled();
    await page.reload();
    await expect(pending).toContainText(String(commands[0].request_id));
    await panel.getByRole('button', { name: '刷新学习包与状态' }).click();
    await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeEnabled();
    expect(commands).toHaveLength(1);
    expect(events).toHaveLength(1);
    await pending.getByRole('button', { name: '重发未确认请求' }).click();
    await expect(pending).not.toBeVisible();
    const history = panel.getByRole('region', { name: '学习包解释记录' });
    await expect(history).toContainText('模拟解释失败');
    expect(commands[1]).toEqual(commands[0]);
    await history.getByRole('button', { name: '重试', exact: true }).click();
    await expect(history.getByRole('article', { name: '组件解释' }).last()).toContainText('解释已完成');
    expect(commands[2]).toEqual({ ...commands[0], request_id: commands[2].request_id, retry_of_run_id: 'failed-root' });
    expect(commands[2].request_id).not.toBe(commands[0].request_id);
    // Restoring the original slot returns the latest retry, without creating a new logical task.
    await chapter.getByRole('button', { name: '恢复此解释', exact: true }).click();
    await expect.poll(() => commands.length).toBe(4);
    expect(commands[3]).toEqual(commands[2]);
    await chapter.getByRole('button', { name: '重新解释', exact: true }).click();
    await expect(history.getByRole('article', { name: '组件解释' })).toHaveCount(3);
    expect(commands[4].source_event_id).toBe(commands[0].source_event_id);
    expect(commands[4].explanation_slot).not.toBe(commands[0].explanation_slot);
    expect(commands[4].request_id).not.toBe(commands[0].request_id);
    expect(commands[4]).not.toHaveProperty('retry_of_run_id');
    expect(events).toHaveLength(1);
    await expect(page.getByLabel('节点对话记录')).not.toContainText('解释已完成');
  });
}

test('P1 lessons: a pending explanation uses its original package lock, not the selected historical version', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const current = lessonDTO(goal, 'current', 2);
  const outdated = { ...lessonDTO(goal, 'old', 1), outdated: true };
  await mockLessons(page, goal, [current, outdated]);
  const commands: Record<string, unknown>[] = [];
  await page.route(`**/api/goals/${goal}/lessons/${current.id}/events`, route => route.fulfill({ json: eventACK(current, route.request().postDataJSON()) }));
  await page.route('**/api/sessions/*/runs', route => {
    if (route.request().method() !== 'POST') return route.fulfill({ json: [] });
    commands.push(route.request().postDataJSON());
    if (commands.length === 1) return route.abort('failed');
    return route.fulfill({ status: 202, json: { ...runDTO('original-package', '', 'completed', '原学习包已恢复'), mode: 'explanation' } });
  });
  await page.goto(`/goals/${goal}/learn`);
  const panel = page.locator('.lesson-panel');
  await panel.getByRole('article', { name: '学习包详情' }).locator('.lesson-block').first().getByRole('button', { name: '让 Agent 解释', exact: true }).click();
  const pending = panel.getByRole('region', { name: '未确认请求恢复' });
  await expect(pending).toBeVisible();
  await panel.getByRole('combobox', { name: '学习包版本' }).selectOption(outdated.id);
  await expect(panel.getByRole('article', { name: '学习包详情' })).toContainText('只读');
  await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeEnabled();
  // Once its actual source package is outdated, GET remains available but POST is locked.
  current.outdated = true;
  await panel.getByRole('button', { name: '刷新学习包与状态' }).click();
  await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeDisabled();
  await expect(pending.getByRole('button', { name: '查询运行状态' })).toBeEnabled();
  expect(commands).toHaveLength(1);
  current.outdated = false;
  await panel.getByRole('button', { name: '刷新学习包与状态' }).click();
  await expect(pending.getByRole('button', { name: '重发未确认请求' })).toBeEnabled();
  await pending.getByRole('button', { name: '重发未确认请求' }).click();
  await expect(panel.getByRole('article', { name: '组件解释' })).toContainText('原学习包已恢复');
  expect(commands[1]).toEqual(commands[0]);
});

test('P1 lessons: historical quiz feedback is read from that exercise, never inferred from a current-node question list', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const exercise = publicExercise(goal);
  const lesson = { ...lessonDTO(goal), outdated: true, components: [
    { id: 'history-quiz', kind: 'quiz_choice', props: { exercise_id: exercise.id } },
  ] } as LessonDTO;
  await mockLessons(page, goal, [lesson], exercise);
  await page.route(`**/api/goals/${goal}/nodes/n/exercises`, route => route.fulfill({ json: { exercises: [], feedback: {} } }));
  const feedbackReads: string[] = [];
  await page.route(`**/api/goals/${goal}/exercises/${exercise.id}/feedback`, route => {
    feedbackReads.push(route.request().method());
    return route.fulfill({ json: { feedback: { attempt: { is_correct: true, counted: true, selected_option_id: 'b' },
      correct_option_id: 'b', explanation: '仅已有历史作答返回的解释' } } });
  });
  const posts: string[] = [];
  page.on('request', req => { if (req.method() === 'POST') posts.push(req.url()); });
  await page.goto(`/goals/${goal}/learn`);
  const quiz = page.locator('.lesson-panel [data-component-kind="quiz_choice"]');
  await expect(quiz).toContainText('仅已有历史作答返回的解释');
  await expect(quiz).toContainText('回答正确');
  await expect(quiz.getByRole('radio', { name: '选项 B' })).toBeChecked();
  await expect(quiz.getByRole('button', { name: '提交答案', exact: true })).toBeDisabled();
  expect(feedbackReads).toEqual(['GET']);
  expect(posts).toEqual([]);
});

test('P1 lessons: a failed step ACK and its explanation reuse the exact saved step event across reload', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const lesson = lessonDTO(goal);
  await mockLessons(page, goal, [lesson]);
  const events: Record<string, unknown>[] = [];
  const commands: Record<string, unknown>[] = [];
  await page.route(`**/api/goals/${goal}/lessons/${lesson.id}/events`, route => {
    const body = route.request().postDataJSON(); events.push(body);
    if (events.length < 3) return route.abort('failed');
    return route.fulfill({ json: eventACK(lesson, body) });
  });
  await page.route('**/api/sessions/*/runs', route => {
    if (route.request().method() !== 'POST') return route.fulfill({ json: [] });
    commands.push(route.request().postDataJSON());
    return route.fulfill({ status: 202, json: { ...runDTO('step-explanation', '', 'completed', '解释已确认步骤'), mode: 'explanation' } });
  });
  await page.goto(`/goals/${goal}/learn`);
  const stepper = page.locator('.lesson-panel [data-component-kind="stepper"]');
  await stepper.getByRole('button', { name: '下一步', exact: true }).click();
  await expect(stepper).toContainText('步骤尚未保存');
  await expect(stepper).toContainText('第二步');
  expect(commands).toEqual([]);
  await stepper.getByRole('button', { name: '让 Agent 解释', exact: true }).click();
  await expect(stepper.locator('.lesson-explanation').getByRole('alert')).toContainText('事件尚未确认');
  const key = `learngraph:lesson:${goal}:${lesson.id}:1:steps:explanation:${events[0].event_id}`;
  const saved = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), key);
  await page.reload();
  await expect(stepper).toContainText('第二步');
  await expect(stepper).toContainText('尚未确认');
  expect(events).toHaveLength(2);
  expect(commands).toEqual([]);
  await stepper.getByRole('button', { name: '恢复此解释', exact: true }).click();
  await expect(page.locator('.lesson-explanation-history')).toContainText('解释已确认步骤');
  await expect(stepper).toContainText('步骤已保存');
  expect(events).toEqual([events[0], events[0], events[0]]);
  expect(events[0]).toMatchObject({ action: 'step_changed', payload: { step: 1 } });
  expect(commands).toEqual([{ request_id: saved.requestId, mode: 'explanation', goal_id: goal, node_id: 'n',
    source_event_id: events[0].event_id, explanation_slot: saved.slot }]);
  await expect(page.locator('.progress-card')).toContainText('0 个有效样本');
});

test('P1 lessons: C1 stays artifact-local for lessons, quizzes, teaching and explanation runs', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const source = (quote: string, documentId: string) => ({ id: 'C1', document_id: documentId, document_version: 1, chunk_id: `${documentId}-chunk`,
    quote, start_offset: 0, end_offset: quote.length, page_number: null, heading: quote, text_hash: 'hash', status: 'valid' as const, cited: true });
  const lessonSource = source('章节来源', 'lesson-document');
  const quizSource = source('题目来源', 'quiz-document');
  const teachingSource = source('对话来源', 'teaching-document');
  const explanationSource = source('解释来源', 'explanation-document');
  const lesson = { ...lessonDTO(goal), citation_map: { C1: lessonSource }, components: [
    ...lessonDTO(goal).components, { id: 'quiz', kind: 'quiz_choice', props: { exercise_id: 'public-question' } },
  ] } as LessonDTO;
  const exercise = { ...publicExercise(goal), citation_map: { C1: quizSource } };
  await mockLessons(page, goal, [lesson], exercise);
  let explanationSession = '';
  await page.route('**/api/sessions/*/runs', route => {
    const session = decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]);
    if (route.request().method() === 'POST') {
      explanationSession = session;
      return route.fulfill({ status: 202, json: { ...runDTO('citation-explanation', '', 'completed', '解释正文 [C1] [C9]'), mode: 'explanation',
        output: { citation_map: { C1: explanationSource }, unverified_citation_ids: ['C9'] } } });
    }
    return route.fulfill({ json: session === `learn:${goal}:n` ? [{ ...runDTO('citation-teaching', '引用测试', 'completed', '节点回答 [C1]'),
      output: { citation_map: { C1: teachingSource } } }] : [] });
  });
  await page.route(`**/api/goals/${goal}/lessons/${lesson.id}/events`, route => route.fulfill({ json: eventACK(lesson, route.request().postDataJSON()) }));
  const lookups: string[] = [];
  await page.route('**/api/**/citations/*', route => {
    lookups.push(new URL(route.request().url()).pathname);
    return route.fulfill({ status: 409, json: { error: { code: 'source_unavailable', message: '已解绑，不能定位原文' } } });
  });
  await page.goto(`/goals/${goal}/learn`);
  await expect(page.getByRole('region', { name: '节点资料绑定' })).toBeVisible();
  const panel = page.locator('.lesson-panel');
  const detail = panel.getByRole('article', { name: '学习包详情' });
  const chapterCitations = detail.locator(':scope > .doc-citations');
  const quizCitations = detail.locator('[data-component-kind="quiz_choice"] .doc-citations');
  const teachingCitations = page.locator('.assistant-message .doc-citations');
  await expect(chapterCitations).toContainText('章节来源');
  await expect(chapterCitations).not.toContainText('题目来源');
  await expect(quizCitations).toContainText('题目来源');
  await expect(quizCitations).not.toContainText('章节来源');
  await expect(teachingCitations).toContainText('对话来源');
  await detail.locator('.lesson-block').first().getByRole('button', { name: '让 Agent 解释', exact: true }).click();
  expect(explanationSession).not.toBe(`learn:${goal}:n`);
  const explanationCitations = panel.getByRole('article', { name: '组件解释' }).locator('.doc-citations');
  await expect(explanationCitations).toContainText('解释来源');
  await expect(explanationCitations).toContainText('未知引用 [C9]');
  await expect(explanationCitations.getByRole('button', { name: 'C9 · 查看原文' })).toHaveCount(0);
  for (const citations of [chapterCitations, quizCitations, teachingCitations, explanationCitations]) {
    await citations.getByRole('button', { name: 'C1 · 查看原文', exact: true }).click();
    await expect(citations.getByRole('alert')).toContainText('409');
  }
  expect(lookups).toEqual([`/api/goals/${goal}/lessons/${lesson.id}/citations/C1`,
    `/api/goals/${goal}/exercises/${exercise.id}/citations/C1`, '/api/runs/citation-teaching/citations/C1', '/api/runs/citation-explanation/citations/C1']);
  await expect(page).toHaveURL(`/goals/${goal}/learn`);
});
