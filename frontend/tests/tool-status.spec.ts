import { expect, learningGoal, openLearning, runDTO, test } from './fixtures';

test('tool status describes learning actions without exposing protocol names as user-facing labels', async ({ page, request }) => {
  const goal = await learningGoal(request);
  const labels: Record<string, string> = {
    read_planning_context: '读取当前目标与路线', request_clarification: '整理需要澄清的问题',
    propose_goal_draft: '提炼目标摘要', generate_route_draft: '整理学习路线草稿',
    get_learning_context: '读取当前学习状态', get_next_action: '查询下一步建议',
    search_documents: '检索学习资料', read_document_chunk: '读取资料原文',
    create_exercise: '生成练习', create_lesson: '生成学习包',
    propose_graph_change: '提出图谱调整建议', read_skill: '读取学习指南',
    future_operation: '处理学习操作',
  };
  const run = { ...runDTO('tool-labels', '给我一道练习题'), tool_activity: Object.fromEntries(
    Object.keys(labels).map(name => [name, { call_id: name, name, status: 'completed' }]),
  ) };
  await page.route('**/api/sessions/*/runs', route => route.fulfill({ json: [run] }));
  await openLearning(page, request, goal);
  const status = page.locator('.wb-conversation > .run-status');
  for (const [name, label] of Object.entries(labels)) {
    const action = status.locator(`.tool[data-tool-name="${name}"]`);
    await expect(action).toContainText(label);
    await expect(action).not.toContainText(name);
  }
});
