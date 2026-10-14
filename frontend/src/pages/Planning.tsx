import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { ErrorBox, GraphCanvas, PendingRequest, RunStatus } from '../components';
import type { Goal, Graph, Plan } from '../types';
import { useRuns } from '../useRuns';
import { Citations, DocumentBindings } from '../documents';
import { GoalGuide } from './GoalGuide';
import { orderedStages, RouteOverview } from './RouteOverview';

const feedbackOptions = [
  ['太难了', '这条路线对我来说太难，请补充必要入门内容、减小学习跨度，在总投入内降低深度。'],
  ['范围太宽', '范围太宽，请在总投入内聚焦最必要的内容，缩小成果范围。'],
  ['我已有基础', '我已有部分基础（自述，未验证），希望减少重复内容，并用简短实践检查起点。具体基础：'],
  ['调整学习重点', '我希望调整学习重点，请围绕以下重点重新安排：'],
];

function sameGoalInputs(left: Goal, right: Goal) {
  return ['title', 'desired_outcome', 'current_level', 'constraints'].every(name =>
    String(left[name as keyof Goal]).trim() === String(right[name as keyof Goal]).trim())
    && left.time_budget_minutes === right.time_budget_minutes
    && JSON.stringify([...(left.skipped_fields || [])].sort()) === JSON.stringify([...(right.skipped_fields || [])].sort());
}

export function Planning({ goalId }: { goalId: string }) {
  const [plan, setPlan] = useState<Plan>();
  const [form, setForm] = useState<Goal>();
  const [graph, setGraph] = useState<Graph>();
  const [selected, setSelected] = useState('');
  const [dirty, setDirty] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [nodeCount, setNodeCount] = useState(10);
  const [feedback, setFeedback] = useState('');
  const dirtyFields = useRef({ goal: false, graph: false });
  const currentForm = useRef<Goal | undefined>(undefined);
  const refreshVersion = useRef(0);
  const refresh = useCallback(async () => {
    const version = ++refreshVersion.current;
    try {
      const value = await api<Plan>(`/goals/${goalId}`);
      if (version !== refreshVersion.current) return;
      setPlan(value);
      // A confirmation response may be lost. A read can acknowledge exactly the
      // same confirmed summary, but must never discard different local edits.
      if (dirtyFields.current.goal && currentForm.current && value.goal.confirmed && sameGoalInputs(currentForm.current, value.goal)) {
        dirtyFields.current.goal = false; setEditing(false);
      }
      if (!dirtyFields.current.goal) { currentForm.current = value.goal; setForm(value.goal); }
      if (!dirtyFields.current.graph) setGraph(value.graph || undefined);
      setError('');
    } catch (e) { if (version === refreshVersion.current) setError(String(e)); }
  }, [goalId]);
  const tasks = useRuns(`planning:${goalId}`, () => { void refresh(); });
  useEffect(() => { void refresh(); }, [refresh]);
  const busy = saving || tasks.busy;
  const published = plan?.graph?.status === 'published';
  async function write(path: string, body: unknown, method = 'POST', saved?: 'goal' | 'graph') {
    ++refreshVersion.current;
    setSaving(true); setError('');
    try {
      const value = await api<Plan>(path, body, method);
      setPlan(value);
      if (saved) dirtyFields.current[saved] = false;
      if (saved === 'goal') { setEditing(false); currentForm.current = value.goal; setForm(value.goal); }
      if (saved === 'graph') setDirty(false);
      await refresh();
    }
    catch (e) { setError(`${String(e)}。输入已保留；若结果不确定，请先刷新目标与路线查看已保存状态。`); }
    finally { setSaving(false); }
  }
  function confirmGoal() {
    if (!plan || !form) return;
    void write(`/goals/${goalId}/confirm`, { expected_version: plan.version, title: form.title,
      desired_outcome: form.desired_outcome, current_level: form.current_level, time_budget_minutes: form.time_budget_minutes,
      constraints: form.constraints, skipped_fields: form.skipped_fields || [] }, 'POST', 'goal');
  }
  function updateGoal(patch: Partial<Goal>) {
    if (!currentForm.current) return;
    dirtyFields.current.goal = true; currentForm.current = { ...currentForm.current, ...patch }; setForm(currentForm.current);
  }
  function updateGraph(value: Graph) { dirtyFields.current.graph = true; setGraph(value); setDirty(true); }
  const node = graph?.nodes.find(n => n.id === selected) || graph?.nodes[0];
  function updateNode(field: string, value: string | number) {
    if (!graph || !node) return;
    updateGraph({ ...graph, nodes: graph.nodes.map(n => n.id === node.id ? { ...n, [field]: value } : n) });
  }
  if (!plan || !form) return <div className="page"><ErrorBox error={error}/><p role="status">正在读取目标…</p></div>;
  const goalEditing = editing || dirtyFields.current.goal;
  const routeLocked = busy || dirty || goalEditing || !plan.goal.confirmed;
  return <div className="page"><a className="back" href="/">← 我的学习</a>
    <div className="page-heading"><div><p className="eyebrow">01 目标 · 02 路线 · 03 学习</p><h1>规划你的学习路线</h1></div><span className="tag">{published ? '已发布' : graph ? '路线草稿' : plan.goal.confirmed ? '目标已确认' : '目标待确认'}</span></div>
    <ErrorBox error={error || tasks.error}/><PendingRequest command={tasks.pending} checked={tasks.pendingChecked} sending={tasks.sending} query={() => { void tasks.refresh(); void refresh(); }} resend={() => { void tasks.recover(); }}/>
    <div className="plan-grid"><section className="panel"><div className="section-title"><h2>学习目标</h2>{plan.goal.confirmed && !published && !editing && <button className="quiet" disabled={busy} onClick={() => setEditing(true)}>修改目标</button>}</div>
      <GoalGuide goal={form} confirmed={plan.goal.confirmed || !!published} editing={!published && goalEditing && plan.goal.confirmed} busy={busy} onChange={updateGoal} onConfirm={confirmGoal}/>
      {!!plan.questions.length && <details><summary>此前的澄清建议（可选）</summary>{plan.questions.map(question => <p key={question}>{question}</p>)}</details>}
      <details><summary>参考资料（可选）</summary><DocumentBindings goalId={goalId}/></details>
    </section>
    <section className="panel route-panel"><div className="section-title"><h2>学习路线</h2>{plan.goal.confirmed && !published && <button className="secondary" disabled={routeLocked} onClick={() => tasks.execute({ path: `/goals/${goalId}/graph-drafts`, body: { request_id: crypto.randomUUID(), expected_version: plan.version, node_count: nodeCount } })}>{graph ? '重新生成' : '生成路线草稿'}</button>}</div>
      {plan.goal.confirmed && !published && <details><summary>路线长度（可选）</summary><label>路线节点数<select value={nodeCount} disabled={routeLocked} onChange={event => setNodeCount(Number(event.target.value))}><option value={3}>3 个 · 小型验证</option><option value={5}>5 个 · 短路线</option><option value={10}>10 个 · 完整路线</option></select></label><p className="muted small">不确定时保留默认即可，具体投入仍需查看草稿。</p></details>}
      <RunStatus run={tasks.runs.at(-1)} stop={tasks.stop} retry={tasks.retry} readOnly={!!tasks.pending}/>
      <div className="actions"><button className="quiet" disabled={saving} onClick={() => { void tasks.refresh(); void refresh(); }}>刷新目标与路线</button>
        {!!tasks.runs.length && <button className="quiet" disabled={saving || tasks.sending} onClick={() => { void tasks.refresh(); }}>查询运行状态</button>}
      </div>
      {goalEditing && graph && <p className="hint">目标有未确认修改，请先确认目标摘要。修改目标会使旧路线草稿失效；本地的高级编辑不会被刷新覆盖。</p>}
      {!graph ? <div className="empty"><span className="empty-icon">◇</span><h3>路线从你的意图开始</h3><p>确认目标摘要后生成路线。你只需判断是否符合想学的内容，无需设计节点和依赖。</p></div> : <>
        <RouteOverview graph={graph} goal={plan.goal}/>
        {!published && <form className="route-feedback" onSubmit={event => { event.preventDefault(); void tasks.execute({ path: `/goals/${goalId}/graph-drafts`, body: { request_id: crypto.randomUUID(), expected_version: plan.version, node_count: graph.nodes.length, feedback: feedback.trim() } }); }}>
          <fieldset disabled={routeLocked || !plan.graph}>
            <h3>不合适？用你的话告诉我们</h3>
            <div className="actions">{feedbackOptions.map(([label, value]) => <button type="button" className="quiet" key={label} onClick={() => setFeedback(value)}>{label}</button>)}</div>
            <label>希望怎样调整路线？<textarea required maxLength={2000} value={feedback} onChange={event => setFeedback(event.target.value)} placeholder="例如：少讲理论，把重点放在能用的例子上"/></label>
            <button type="submit" className="secondary" disabled={!feedback.trim()}>根据反馈调整路线</button>
            <p className="muted small">调整会生成新草稿，不会自动发布。若需要减少总阶段数，可使用路线长度选项重新生成。</p>
          </fieldset>
        </form>}
        <details className="advanced-route"><summary>高级：图谱与节点编辑</summary>
          <p className="muted small">可选。无需修改优先级或依赖关系，也可以直接确认发布。</p>
          <GraphCanvas graph={graph} selected={node?.id} onSelect={setSelected}/><div className="node-chips" aria-label="选择路线节点">{graph.nodes.map((n, i) => <button className={node?.id === n.id ? 'selected' : 'quiet'} key={n.id} onClick={() => setSelected(n.id)}>{i + 1}. {n.title}</button>)}</div>
          {node && <form className="node-editor" onSubmit={event => { event.preventDefault(); void write(`/goals/${goalId}/graph`, { expected_version: plan.version, nodes: graph.nodes, edges: graph.edges }, 'PATCH', 'graph'); }}><fieldset disabled={busy || published || goalEditing || !plan.goal.confirmed}>
            <label>节点标题<input value={node.title} required onChange={event => updateNode('title', event.target.value)}/></label><div className="two-cols"><label>预计分钟<input type="number" value={node.estimated_minutes} min="1" required onChange={event => updateNode('estimated_minutes', Number(event.target.value))}/></label><label>优先级<input type="number" value={node.priority} min="0" max="5" required onChange={event => updateNode('priority', Number(event.target.value))}/></label></div>
            <label>节点说明<textarea value={node.explanation} required onChange={event => updateNode('explanation', event.target.value)}/></label><label>学习成果<textarea value={node.learning_outcome} required onChange={event => updateNode('learning_outcome', event.target.value)}/></label>
            <label>前置节点</label><div className="prerequisite-options">{graph.nodes.filter(n => n.id !== node.id).map(n => <label key={n.id}><input type="checkbox" checked={graph.edges.some(edge => edge.source === n.id && edge.target === node.id)} onChange={event => updateGraph({ ...graph, edges: event.target.checked ? [...graph.edges, { source: n.id, target: node.id, kind: 'prerequisite' }] : graph.edges.filter(edge => !(edge.source === n.id && edge.target === node.id)) })}/>{n.title}</label>)}</div>
            {!published && <div className="actions"><button className="secondary" disabled={!dirty}>保存路线修改</button><button className="quiet" type="button" disabled={graph.nodes.length <= 1} onClick={() => { updateGraph({ ...graph, nodes: graph.nodes.filter(n => n.id !== node.id), edges: graph.edges.filter(edge => edge.source !== node.id && edge.target !== node.id) }); setSelected(''); }}>删除该节点</button><button className="quiet" type="button" disabled={graph.nodes.length >= 30} onClick={() => { const id = crypto.randomUUID(); updateGraph({ ...graph, nodes: [...graph.nodes, { id, title: '新增节点', explanation: '补充节点说明', learning_outcome: '补充学习成果', estimated_minutes: 20, priority: 3, citation_ids: [] }] }); setSelected(id); }}>添加节点</button></div>}
          </fieldset></form>}
        </details>
        <Citations citationMap={graph.citation_map || {}} endpoint={`/api/goals/${goalId}/graph/citations/{citationId}?version=${plan.version}`} goalId={goalId}/>
        <div className="publish-bar"><span className="muted">{dirty ? '有未保存修改，请先保存。' : published ? '这是已确认发布的路线。' : '只有点击确认发布，才会开始使用这条路线。'}</span>{published ? <a className="button" href={`/goals/${goalId}/learn`}>进入学习 →</a> : <button disabled={routeLocked || !plan.graph || !orderedStages(graph).length} onClick={() => write(`/goals/${goalId}/graph/publish`, { expected_version: plan.version, expected_revision: graph.revision })}>审核完成，发布路线</button>}</div>
      </>}
    </section></div>
  </div>;
}
