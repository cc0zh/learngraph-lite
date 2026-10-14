import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import { ErrorBox, GraphCanvas, PendingRequest, RunStatus } from '../components';
import type { Goal, Graph, Plan } from '../types';
import { useRuns } from '../useRuns';

export function Planning({ goalId }: { goalId: string }) {
  const [plan, setPlan] = useState<Plan>();
  const [form, setForm] = useState<Goal>();
  const [graph, setGraph] = useState<Graph>();
  const [selected, setSelected] = useState('');
  const [dirty, setDirty] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const dirtyFields = useRef({ goal: false, graph: false });
  const refreshVersion = useRef(0);
  const refresh = useCallback(async () => {
    const version = ++refreshVersion.current;
    try {
      const value = await api<Plan>(`/goals/${goalId}`);
      if (version !== refreshVersion.current) return;
      setPlan(value);
      if (!dirtyFields.current.goal) setForm(value.goal);
      if (!dirtyFields.current.graph) setGraph(value.graph || undefined);
      setError('');
    } catch (e) { if (version === refreshVersion.current) setError(String(e)); }
  }, [goalId]);
  const tasks = useRuns(`planning:${goalId}`, () => { void refresh(); });
  useEffect(() => { void refresh(); }, [refresh]);
  const busy = saving || tasks.busy;
  const published = graph?.status === 'published';
  async function write(path: string, body: unknown, method = 'POST', saved?: 'goal' | 'graph') {
    setSaving(true); setError('');
    try {
      await api(path, body, method);
      if (saved) dirtyFields.current[saved] = false;
      if (saved === 'goal') setEditing(false);
      if (saved === 'graph') setDirty(false);
      await refresh();
    }
    catch (e) { setError(String(e)); }
    finally { setSaving(false); }
  }
  async function saveGoal(event: FormEvent) {
    event.preventDefault(); if (!plan || !form) return;
    await write(`/goals/${goalId}`, { expected_version: plan.version, title: form.title, desired_outcome: form.desired_outcome, current_level: form.current_level, time_budget_minutes: form.time_budget_minutes, constraints: form.constraints }, 'PATCH', 'goal');
  }
  function updateGoal(patch: Partial<Goal>) { dirtyFields.current.goal = true; setForm(value => value ? { ...value, ...patch } : value); }
  function updateGraph(value: Graph) { dirtyFields.current.graph = true; setGraph(value); setDirty(true); }
  const node = graph?.nodes.find(n => n.id === selected) || graph?.nodes[0];
  function updateNode(field: string, value: string | number) {
    if (!graph || !node) return;
    updateGraph({ ...graph, nodes: graph.nodes.map(n => n.id === node.id ? { ...n, [field]: value } : n) });
  }
  if (!plan || !form) return <div className="page"><ErrorBox error={error}/><p role="status">正在读取目标…</p></div>;
  const locked = busy || published || (plan.goal.confirmed && !editing);
  return <div className="page"><a className="back" href="/">← 我的学习</a><div className="page-heading"><div><p className="eyebrow">01 目标 · 02 路线 · 03 学习</p><h1>规划你的学习路线</h1></div><span className="tag">{published ? '已发布' : graph ? '路线草稿' : plan.goal.confirmed ? '目标已确认' : '目标待确认'}</span></div>
    <ErrorBox error={error || tasks.error}/><PendingRequest command={tasks.pending} checked={tasks.pendingChecked} sending={tasks.sending} query={() => { void tasks.refresh(); void refresh(); }} resend={() => { void tasks.recover(); }}/><div className="plan-grid"><section className="panel"><div className="section-title"><h2>学习目标</h2>{plan.goal.confirmed && !published && <button className="quiet" disabled={busy} onClick={() => setEditing(true)}>修改目标</button>}</div>
    {!!plan.questions.length && <div className="hint"><strong>先明确这几件事</strong>{plan.questions.map(q => <p key={q}>{q}</p>)}</div>}
    <form onSubmit={saveGoal}><fieldset disabled={locked}><label>目标<input value={form.title} onChange={e => updateGoal({ title: e.target.value })} required maxLength={2000}/></label><label>期望成果<textarea value={form.desired_outcome} onChange={e => updateGoal({ desired_outcome: e.target.value })} placeholder="能够独立完成什么？" maxLength={2000}/></label><label>已有基础<textarea value={form.current_level} onChange={e => updateGoal({ current_level: e.target.value })} placeholder="已掌握什么，哪些概念还陌生？" maxLength={2000}/></label><label>可投入时间（分钟）<input type="number" min="1" value={form.time_budget_minutes ?? ''} onChange={e => updateGoal({ time_budget_minutes: e.target.value ? Number(e.target.value) : null })}/></label><label>其他约束<textarea value={form.constraints} onChange={e => updateGoal({ constraints: e.target.value })} maxLength={2000}/></label><button className="secondary" type="submit">保存目标信息</button></fieldset></form>
    {!published && !plan.goal.confirmed && <div className="actions"><button className="secondary" disabled={busy || plan.clarification_round >= 2} onClick={() => tasks.execute({ path: `/goals/${goalId}/clarify`, body: { request_id: crypto.randomUUID(), expected_version: plan.version } })}>获取澄清问题</button><button disabled={busy} onClick={() => write(`/goals/${goalId}/confirm`, { expected_version: plan.version })}>确认已保存目标</button></div>}
    <p className="muted small">先保存信息，再确认目标。AI 生成的路线需要你审核后发布。</p></section>
    <section className="panel route-panel"><div className="section-title"><h2>学习路线</h2>{plan.goal.confirmed && !published && <button className="secondary" disabled={busy || dirty || editing} onClick={() => tasks.execute({ path: `/goals/${goalId}/graph-drafts`, body: { request_id: crypto.randomUUID(), expected_version: plan.version, node_count: 10 } })}>{graph ? '重新生成' : '生成路线草稿'}</button>}</div>
    <RunStatus run={tasks.runs.at(-1)} stop={tasks.stop} retry={tasks.retry} readOnly={!!tasks.pending}/>
    <button className="quiet" disabled={saving} onClick={() => { void tasks.refresh(); void refresh(); }}>刷新目标与路线</button>
    {!graph ? <div className="empty"><span className="empty-icon">◇</span><h3>路线从明确目标开始</h3><p>确认目标后生成小型依赖图。每个节点都有成果和预计时间。</p></div> : <><GraphCanvas graph={graph} selected={node?.id} onSelect={setSelected}/><div className="node-chips" aria-label="选择路线节点">{graph.nodes.map((n, i) => <button className={node?.id === n.id ? 'selected' : 'quiet'} key={n.id} onClick={() => setSelected(n.id)}>{i+1}. {n.title}</button>)}</div>
    {node && <form className="node-editor" onSubmit={e => { e.preventDefault(); void write(`/goals/${goalId}/graph`, { expected_version: plan.version, nodes: graph.nodes, edges: graph.edges }, 'PATCH', 'graph'); }}><fieldset disabled={busy || published}><label>节点标题<input value={node.title} required onChange={e => updateNode('title', e.target.value)}/></label><div className="two-cols"><label>预计分钟<input type="number" value={node.estimated_minutes} min="1" required onChange={e => updateNode('estimated_minutes', Number(e.target.value))}/></label><label>优先级<input type="number" value={node.priority} min="0" max="5" required onChange={e => updateNode('priority', Number(e.target.value))}/></label></div><label>节点说明<textarea value={node.explanation} required onChange={e => updateNode('explanation', e.target.value)}/></label><label>学习成果<textarea value={node.learning_outcome} required onChange={e => updateNode('learning_outcome', e.target.value)}/></label>
    <label>前置节点</label><div className="prerequisite-options">{graph.nodes.filter(n => n.id !== node.id).map(n => <label key={n.id}><input type="checkbox" checked={graph.edges.some(e => e.source === n.id && e.target === node.id)} onChange={e => { updateGraph({ ...graph, edges: e.target.checked ? [...graph.edges, { source: n.id, target: node.id, kind: 'prerequisite' }] : graph.edges.filter(edge => !(edge.source === n.id && edge.target === node.id)) }); }}/>{n.title}</label>)}</div>
    {!published && <div className="actions"><button className="secondary" disabled={!dirty}>保存路线修改</button><button className="quiet" type="button" disabled={graph.nodes.length <= 1} onClick={() => { updateGraph({ ...graph, nodes: graph.nodes.filter(n => n.id !== node.id), edges: graph.edges.filter(e => e.source !== node.id && e.target !== node.id) }); setSelected(''); }}>删除该节点</button><button className="quiet" type="button" disabled={graph.nodes.length >= 30} onClick={() => { const id = crypto.randomUUID(); updateGraph({ ...graph, nodes: [...graph.nodes, { id, title: '新增节点', explanation: '补充节点说明', learning_outcome: '补充学习成果', estimated_minutes: 20, priority: 3, citation_ids: [] }] }); setSelected(id); }}>添加节点</button></div>}</fieldset></form>}
    <div className="publish-bar"><span className="muted">{dirty ? '有未保存修改，请先保存。' : `${graph.nodes.length} 个节点 · ${graph.nodes.reduce((sum, n) => sum+n.estimated_minutes, 0)} 分钟`}</span>{published ? <a className="button" href={`/goals/${goalId}/learn`}>进入学习 →</a> : <button disabled={busy || dirty} onClick={() => write(`/goals/${goalId}/graph/publish`, { expected_version: plan.version, expected_revision: graph.revision })}>审核完成，发布路线</button>}</div></>}
    </section></div></div>;
}
