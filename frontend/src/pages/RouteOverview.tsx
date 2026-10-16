import type { Goal, Graph, GraphNode } from '../types';

// Stable topological order: prerequisite first, original order for independent nodes.
export function orderedStages(graph: Graph): GraphNode[] {
  const remaining = [...graph.nodes];
  const done = new Set<string>();
  const result: GraphNode[] = [];
  while (remaining.length) {
    const index = remaining.findIndex(node => graph.edges.filter(edge => edge.target === node.id).every(edge => done.has(edge.source)));
    if (index < 0) return []; // Invalid legacy drafts must not present an invented order.
    const [node] = remaining.splice(index, 1);
    done.add(node.id); result.push(node);
  }
  return result;
}

export function RouteOverview({ graph, goal, knowledgeMap = false }: { graph: Graph; goal: Goal; knowledgeMap?: boolean }) {
  const stages = orderedStages(graph);
  const minutes = graph.nodes.reduce((sum, node) => sum + node.estimated_minutes, 0);
  const budget = goal.time_budget_minutes ?? 240;
  if (knowledgeMap) return <div className="route-overview knowledge-map-overview">
    <h3>这些主题是否覆盖你想了解的内容？</h3>
    <p>围绕「{goal.title}」整理了 {graph.nodes.length} 个知识节点。图谱用于理解主题之间的联系，不要求把探索收窄成项目交付。</p>
    <p className="muted small">可以从感兴趣的节点开始；连线表示已标明的前置关系，不是一条必须依次完成的任务清单。学习建议和时间估算仅供参考。</p>
    <ul className="wb-map-topics" aria-label="图谱知识节点">{graph.nodes.map(node => <li key={node.id}>
      <h3>{node.title}</h3><p>{node.explanation}</p>
      {node.learning_outcome && <p className="muted small">理解参考：{node.learning_outcome}</p>}
    </li>)}</ul>
  </div>;
  return <div className="route-overview">
    <h3>这是不是你想学的？</h3>
    <p>围绕「{goal.title}」，逐步达到：{goal.desired_outcome || '理解核心概念、完成适合主题的练习并解释结果'}。</p>
    <div className="route-estimate"><strong>{stages.length} 个阶段 · 预计 {minutes} 分钟</strong><span>{goal.time_budget_minutes ? `你的总投入：${budget} 分钟` : '总投入未提供，暂按 240 分钟规划参考'}</span></div>
    {minutes > budget && <p className="hint">当前估算超出{goal.time_budget_minutes ? '你的总投入' : '默认规划参考'} {minutes - budget} 分钟。可以反馈「范围太宽」缩小路线，或修改目标中的投入。</p>}
    <p className="muted small">先学前置知识，再做后续应用；互不依赖的阶段也可以灵活安排。时间是初步估算，实践和复盘可能额外耗时，不是完成保证。</p>
    <p className="muted small">实践与验证建议：每阶段先解释或尝试一个小例子，再对照预期成果自查。进入学习后可以生成练习获取反馈；自查和少量练习不等于能力认证。</p>
    {!stages.length && <p role="alert" className="error">当前依赖无法形成学习顺序，请在高级编辑中修正，或重新生成路线。</p>}
    <ol className="stage-list" aria-label="学习阶段">{stages.map((node, index) => {
      const prerequisites = graph.edges.filter(edge => edge.target === node.id).map(edge => graph.nodes.find(item => item.id === edge.source)?.title).filter(Boolean);
      return <li key={node.id} className="stage-card">
        <div className="stage-heading"><span className="stage-number">{index + 1}</span><h3>{node.title}</h3><span className="muted small">约 {node.estimated_minutes} 分钟</span></div>
        <p><strong>预期成果：</strong>{node.learning_outcome || '旧路线未说明成果，可反馈补充或在高级编辑中完善。'}</p>
        <details><summary>为什么学 · 实践与验证</summary>
          <p><strong>为什么必要：</strong>{node.explanation || '旧路线未说明必要性，可要求重新生成。'}</p>
          <p><strong>学习顺序：</strong>{prerequisites.length ? `在「${prerequisites.join('」「')}」之后，使用前面学到的内容继续。` : '没有前置要求，可以作为起点。'}</p>
          <p><strong>实践建议：</strong>围绕「{node.title}」用自己的话解释，或完成一个小例子。</p>
          <p><strong>验证建议：</strong>对照「{node.learning_outcome || node.title}」检查成果，并在学习页用练习反馈发现薄弱处。</p>
        </details>
      </li>;
    })}</ol>
  </div>;
}
