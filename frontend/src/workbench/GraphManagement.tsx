import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { ErrorBox, GraphCanvas, PendingRequest, RunStatus } from '../components';
import { Citations } from '../documents';
import { orderedStages, RouteOverview } from '../pages/RouteOverview';
import { ProposalPanel } from '../proposals/ProposalPanel';
import type { Goal, Graph, Plan } from '../types';
import { useRuns } from '../useRuns';
import { navigateWorkbench, workbenchHref } from './navigation';
import './graph-management.css';

interface Props {
  goalId: string;
  onPlanChange: (plan: Plan) => void;
  onDirtyChange?: (dirty: boolean) => void;
}
const feedbackOptions = [
  ['太难了', '这张图谱对我来说太难，请补充必要入门内容、减小学习跨度。'],
  ['范围太宽', '范围太宽，请聚焦最必要的主题，缩小知识范围。'],
  ['我已有基础', '我已有部分基础（自述，未验证），希望减少重复内容。具体基础：'],
  ['调整学习重点', '我希望调整学习重点，请围绕以下重点重新组织图谱：'],
];
function sameGoalInputs(left: Goal, right: Goal) {
  return (['title', 'desired_outcome', 'current_level', 'constraints'] as const).every(name => left[name].trim() === right[name].trim())
    && left.time_budget_minutes === right.time_budget_minutes
    && JSON.stringify([...(left.skipped_fields || [])].sort()) === JSON.stringify([...(right.skipped_fields || [])].sort());
}
function sameGraphInputs(left: Graph, right: Graph) {
  return JSON.stringify([left.nodes, left.edges]) === JSON.stringify([right.nodes, right.edges]);
}

function GoalForm({ goal, locked, confirmed, changed, onChange, onConfirm }: {
  goal: Goal; locked: boolean; confirmed: boolean; changed: boolean;
  onChange: (patch: Partial<Goal>) => void; onConfirm: () => void;
}) {
  function answer(field: 'desired_outcome' | 'current_level' | 'time_budget_minutes', value: string | number | null) {
    onChange({ [field]: value, skipped_fields: (goal.skipped_fields || []).filter(name => name !== field) });
  }
  return <form onSubmit={event => { event.preventDefault(); onConfirm(); }}>
    <h3>目标摘要</h3>
    <dl className="goal-summary">
      <dt>学习意图</dt><dd>{goal.title}</dd>
      <dt>成果与深度</dt><dd>{goal.desired_outcome || '未提供：理解核心概念、尝试适合主题的练习仅作为默认规划参考。'}</dd>
      <dt>起点</dt><dd>{goal.current_level || '基础未知，从必要的入门内容开始，不假设已经掌握。'}{goal.current_level && <small>用户自述 · 未验证</small>}</dd>
      <dt>总投入</dt><dd>{goal.time_budget_minutes ? `${goal.time_budget_minutes} 分钟` : '未提供：暂按 240 分钟作为规划参考，不代表你的承诺。'}</dd>
      <dt>约束与重点</dt><dd>{goal.constraints || '未提供，不额外假设期限或工具偏好。'}</dd>
    </dl>
    <p className="muted small">直接填写想探索的主题，其他字段可选；已有基础仅为自述，不是能力认证。确认目标不会自动生成或发布图谱。</p>
    <fieldset disabled={locked}>
      <label>目标<input required maxLength={2000} value={goal.title} onChange={event => onChange({ title: event.target.value })}/></label>
      <label>期望成果<textarea maxLength={2000} value={goal.desired_outcome} onChange={event => answer('desired_outcome', event.target.value)}/></label>
      <label>已有基础（用户自述，未验证）<textarea maxLength={2000} value={goal.current_level} onChange={event => answer('current_level', event.target.value)}/></label>
      <label>可投入时间（总分钟）<input type="number" min="1" step="1" value={goal.time_budget_minutes ?? ''} onChange={event => answer('time_budget_minutes', event.target.value ? Number(event.target.value) : null)}/></label>
      <label>其他约束与重点<textarea maxLength={2000} value={goal.constraints} onChange={event => onChange({ constraints: event.target.value })}/></label>
      <button disabled={!goal.title.trim() || (confirmed && !changed)}>确认目标摘要</button>
    </fieldset>
    {confirmed && !changed && <p className="hint">目标已明确确认。图谱不会自动发布；已发布图谱只读，后续调整需审核提案。</p>}
  </form>;
}

// A new goal must not inherit another goal's run recovery key or local edits.
export function GraphManagement(props: Props) {
  return <GraphManagementScope key={props.goalId} {...props}/>;
}

function GraphManagementScope({ goalId, onPlanChange, onDirtyChange }: Props) {
  const [plan, setPlan] = useState<Plan>();
  const [form, setForm] = useState<Goal>();
  const [graph, setGraph] = useState<Graph>();
  const [selected, setSelected] = useState('');
  const [goalDirty, setGoalDirty] = useState(false);
  const [graphDirty, setGraphDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [nodeCount, setNodeCount] = useState(10);
  const [feedback, setFeedback] = useState('');
  const dirtyFields = useRef({ goal: false, graph: false });
  const editVersion = useRef({ goal: 0, graph: 0 });
  const currentForm = useRef<Goal | undefined>(undefined);
  const currentGraph = useRef<Graph | undefined>(undefined);
  const currentPlan = useRef<Plan | undefined>(undefined);
  const refreshVersion = useRef(0);
  const mounted = useRef(true);
  const writeLock = useRef(false);
  const changed = useRef(onPlanChange);
  changed.current = onPlanChange;
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; ++refreshVersion.current; };
  }, []);
  const acceptPlan = useCallback((value: Plan, saved?: 'goal' | 'graph') => {
    if (!mounted.current || value.goal_id !== goalId || (currentPlan.current && value.version < currentPlan.current.version)) return;
    currentPlan.current = value; setPlan(value);
    // Reads can acknowledge a lost write only when the exact local input was saved.
    if (saved === 'goal' || (dirtyFields.current.goal && value.version > editVersion.current.goal && value.goal.confirmed
      && currentForm.current && sameGoalInputs(currentForm.current, value.goal))) {
      dirtyFields.current.goal = false; setGoalDirty(false);
    }
    if (saved === 'graph' || (dirtyFields.current.graph && value.version > editVersion.current.graph && value.graph
      && currentGraph.current && sameGraphInputs(currentGraph.current, value.graph))) {
      dirtyFields.current.graph = false; setGraphDirty(false);
    }
    if (!dirtyFields.current.goal) { currentForm.current = value.goal; setForm(value.goal); }
    if (!dirtyFields.current.graph) { currentGraph.current = value.graph || undefined; setGraph(value.graph || undefined); }
    changed.current(value);
  }, [goalId]);
  const refresh = useCallback(async () => {
    if (!mounted.current) return;
    const version = ++refreshVersion.current;
    try {
      const value = await api<Plan>(`/goals/${goalId}`);
      if (!mounted.current || version !== refreshVersion.current) return;
      acceptPlan(value); setError('');
    } catch (e) { if (mounted.current && version === refreshVersion.current) setError(String(e)); }
  }, [goalId, acceptPlan]);
  const tasks = useRuns(`planning:${goalId}`, () => { void refresh(); });
  useEffect(() => { void refresh(); }, [refresh]);
  const dirty = goalDirty || graphDirty || !!feedback.trim();
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  const dirtyCallback = useRef(onDirtyChange);
  dirtyCallback.current = onDirtyChange;
  useEffect(() => () => dirtyCallback.current?.(false), []);
  useEffect(() => {
    if (!dirty && !saving) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, saving]);
  const busy = saving || tasks.busy;
  const published = plan?.graph?.status === 'published';
  const stale = !!plan && ((goalDirty && editVersion.current.goal !== plan.version) || (graphDirty && editVersion.current.graph !== plan.version));
  async function write(path: string, body: unknown, method = 'POST', saved?: 'goal' | 'graph') {
    if (writeLock.current || tasks.busy) return;
    writeLock.current = true; ++refreshVersion.current;
    setSaving(true); setError(''); setNotice('');
    try {
      const value = await api<Plan>(path, body, method);
      if (!mounted.current) return;
      acceptPlan(value, saved);
      setNotice(value.graph?.status === 'published' ? '图谱已发布。返回工作台浏览节点，再选择节点开始学习。' : saved === 'goal' ? '目标已确认，请显式生成图谱草稿。' : '图谱修改已保存，仍需显式发布。');
      await refresh();
    } catch (e) {
      if (!mounted.current) return;
      setError(`${String(e)}。输入已保留；若结果不确定，请先刷新目标与图谱查看已保存状态。`);
    } finally { writeLock.current = false; if (mounted.current) setSaving(false); }
  }
  function confirmGoal() {
    if (!plan || !form || published || stale || graphDirty || busy) return;
    void write(`/goals/${goalId}/confirm`, { expected_version: goalDirty ? editVersion.current.goal : plan.version,
      title: form.title, desired_outcome: form.desired_outcome, current_level: form.current_level,
      time_budget_minutes: form.time_budget_minutes, constraints: form.constraints, skipped_fields: form.skipped_fields || [] }, 'POST', 'goal');
  }
  function updateGoal(patch: Partial<Goal>) {
    if (!currentForm.current || !plan) return;
    if (!dirtyFields.current.goal) editVersion.current.goal = plan.version;
    currentForm.current = { ...currentForm.current, ...patch }; setForm(currentForm.current);
    dirtyFields.current.goal = !sameGoalInputs(currentForm.current, plan.goal); setGoalDirty(dirtyFields.current.goal);
  }
  function updateGraph(value: Graph) {
    if (!plan) return;
    if (!dirtyFields.current.graph) editVersion.current.graph = plan.version;
    dirtyFields.current.graph = !plan.graph || !sameGraphInputs(value, plan.graph); setGraphDirty(dirtyFields.current.graph);
    currentGraph.current = value; setGraph(value);
  }
  async function generate(revision = false) {
    if (!plan || !plan.goal.confirmed || published || busy || goalDirty || graphDirty || stale || (revision && !feedback.trim())) return;
    const input = feedback;
    const accepted = await tasks.execute({ path: `/goals/${goalId}/graph-drafts`, body: {
      request_id: crypto.randomUUID(), expected_version: plan.version, node_count: revision ? graph!.nodes.length : nodeCount,
      ...(revision ? { feedback: input.trim() } : {}),
    } });
    if (accepted && revision && mounted.current) setFeedback(value => value === input ? '' : value);
  }
  async function recover() {
    const input = tasks.pending?.body.feedback;
    if (await tasks.recover() && mounted.current && typeof input === 'string') {
      setFeedback(value => value.trim() === input.trim() ? '' : value);
    }
  }
  function discard() {
    if (!plan || busy || !window.confirm('放弃本地未保存的目标、图谱和反馈修改，重新读取服务器版本？')) return;
    dirtyFields.current = { goal: false, graph: false }; setGoalDirty(false); setGraphDirty(false); setFeedback('');
    currentForm.current = plan.goal; setForm(plan.goal); currentGraph.current = plan.graph || undefined; setGraph(plan.graph || undefined);
    void refresh();
  }
  const node = graph?.nodes.find(item => item.id === selected) || graph?.nodes[0];
  function updateNode(field: string, value: string | number) {
    if (graph && node) updateGraph({ ...graph, nodes: graph.nodes.map(item => item.id === node.id ? { ...item, [field]: value } : item) });
  }
  if (!plan || !form) return <section className="graph-management"><ErrorBox error={error}/><p role="status">正在读取目标与图谱…</p><button className="quiet" onClick={() => { void refresh(); }}>重新读取</button></section>;
  const routeLocked = busy || graphDirty || goalDirty || stale || !plan.goal.confirmed;
  const directRun = tasks.runs.filter(run => run.mode === 'graph' || run.mode === 'clarify').at(-1);
  const totalMinutes = graph?.nodes.reduce((sum, item) => sum + item.estimated_minutes, 0) || 0;
  const budget = plan.goal.time_budget_minutes ?? 240;
  return <div className="graph-management" aria-label="图谱管理">
    <div className="section-title"><h2>图谱管理</h2><span className="tag">{published ? '已发布 · 只读' : graph ? '图谱草稿' : plan.goal.confirmed ? '目标已确认' : '目标待确认'}</span></div>
    <p className="muted small">版本 {plan.version}{plan.graph && ` · 图谱修订 ${plan.graph.revision}`}。这里的生成任务和提案任务不是新的学习对话；资料请使用工作台统一入口。</p>
    <ErrorBox error={error || tasks.error}/>{notice && <p className="hint" role="status">{notice}</p>}
    {stale && <p className="hint" role="alert">服务器版本已变化，本地修改已保留，不能覆盖新版本。请先复制需要的内容，再放弃本地修改并重新编辑。</p>}
    <div className="actions"><button className="quiet" disabled={saving} onClick={() => { void tasks.refresh(); void refresh(); }}>刷新目标与图谱</button>
      {dirty && <button className="quiet" disabled={busy} onClick={discard}>放弃本地修改并刷新</button>}</div>
    <PendingRequest command={tasks.pending} checked={tasks.pendingChecked} sending={tasks.sending}
      query={() => { void tasks.refresh(); void refresh(); }} resend={() => { void recover(); }}/>
    <section className="panel" aria-label="学习目标"><h2>学习目标</h2>
      <GoalForm goal={form} locked={busy || !!published || stale || graphDirty} confirmed={plan.goal.confirmed} changed={goalDirty} onChange={updateGoal} onConfirm={confirmGoal}/>
      {!!plan.questions.length && <details><summary>此前的澄清建议（可选）</summary>{plan.questions.map(question => <p key={question}>{question}</p>)}</details>}
    </section>
    <section className="panel route-panel" aria-label="图谱草稿与发布"><div className="section-title"><h2>知识图谱</h2>
      {plan.goal.confirmed && !published && <button className="secondary" disabled={routeLocked} onClick={() => { void generate(); }}>{graph ? '重新生成图谱' : '生成图谱草稿'}</button>}</div>
      {plan.goal.confirmed && !published && <label>生成节点数<select value={nodeCount} disabled={routeLocked} onChange={event => setNodeCount(Number(event.target.value))}><option value={3}>3 个 · 小型验证</option><option value={5}>5 个 · 小图谱</option><option value={10}>10 个 · 默认</option></select></label>}
      <RunStatus run={directRun} stop={tasks.stop} retry={() => { void tasks.retry(directRun?.run_id); }} readOnly={!!tasks.pending || !!published || goalDirty || graphDirty || saving || stale || (!!tasks.active && tasks.active.run_id !== directRun?.run_id)}/>
      {tasks.active?.mode === 'planning' && <p className="hint">目标创建对话正在运行，请等待完成，或返回原对话查看和停止；这里不会混入其聊天记录。</p>}
      {!!tasks.runs.length && <button className="quiet" disabled={saving || tasks.sending} onClick={() => { void tasks.refresh(); }}>查询生成运行状态</button>}
      {goalDirty && graph && <p className="hint">目标有未确认修改。确认目标会使旧图谱草稿失效，请先保存或放弃图谱修改，再确认目标。</p>}
      {!graph ? <div className="empty"><h3>从学习目标建立知识图谱</h3><p>确认目标后，点击生成图谱草稿。生成结果仍需审核，不会自动发布。</p></div> : <>
        <RouteOverview graph={graph} goal={plan.goal} knowledgeMap/>
        <p className="muted small">参考总投入：{totalMinutes} 分钟 · {plan.goal.time_budget_minutes ? `目标总投入：${budget} 分钟` : '总投入未提供，暂按 240 分钟比较'}。估算不是完成承诺，也不要求按阶段执行。</p>
        {totalMinutes > budget && <p className="hint">当前估算超出{plan.goal.time_budget_minutes ? '目标总投入' : '默认规划参考'} {totalMinutes - budget} 分钟。可反馈收窄范围，或调整目标中的投入。</p>}
        {!orderedStages(graph).length && <p className="error" role="alert">当前前置依赖无法形成无环图谱，不能发布。请在节点编辑中修正前置关系，或重新生成图谱。</p>}
        {!published && <form className="route-feedback" onSubmit={event => { event.preventDefault(); void generate(true); }}><fieldset disabled={routeLocked || !plan.graph}>
          <h3>用反馈调整图谱</h3><div className="actions">{feedbackOptions.map(([label, value]) => <button type="button" className="quiet" key={label} onClick={() => setFeedback(value)}>{label}</button>)}</div>
          <label>希望怎样调整图谱？<textarea required maxLength={2000} value={feedback} onChange={event => setFeedback(event.target.value)} placeholder="例如：少讲理论，重点放在具体例子上"/></label>
          <button type="submit" className="secondary" disabled={!feedback.trim()}>根据反馈调整图谱</button><p className="muted small">修订只生成新草稿；调整节点数可使用上方重新生成。</p>
        </fieldset></form>}
        <details className="advanced-route"><summary>图谱与节点编辑{published ? '（已发布只读）' : ''}</summary>
          <GraphCanvas graph={graph} selected={node?.id} onSelect={setSelected}/>
          <div className="node-chips" aria-label="选择图谱节点">{graph.nodes.map((item, index) => <button className={node?.id === item.id ? 'selected' : 'quiet'} key={item.id} onClick={() => setSelected(item.id)}>{index + 1}. {item.title}</button>)}</div>
          {node && <form className="node-editor" onSubmit={event => { event.preventDefault(); if (graphDirty && !busy && !published && !goalDirty && !stale) void write(`/goals/${goalId}/graph`, { expected_version: editVersion.current.graph, nodes: graph.nodes, edges: graph.edges }, 'PATCH', 'graph'); }}><fieldset disabled={busy || !!published || goalDirty || stale || !plan.goal.confirmed}>
            <label>节点标题<input required maxLength={2000} value={node.title} onChange={event => updateNode('title', event.target.value)}/></label>
            <div className="two-cols"><label>预计分钟<input type="number" required min="1" value={node.estimated_minutes} onChange={event => updateNode('estimated_minutes', Number(event.target.value))}/></label><label>优先级<input type="number" required min="0" max="5" value={node.priority} onChange={event => updateNode('priority', Number(event.target.value))}/></label></div>
            <label>节点说明<textarea required value={node.explanation} onChange={event => updateNode('explanation', event.target.value)}/></label>
            <label>学习成果<textarea required value={node.learning_outcome} onChange={event => updateNode('learning_outcome', event.target.value)}/></label>
            <label>前置节点</label><div className="prerequisite-options">{graph.nodes.filter(item => item.id !== node.id).map(item => <label key={item.id}><input type="checkbox" checked={graph.edges.some(edge => edge.source === item.id && edge.target === node.id)} onChange={event => updateGraph({ ...graph, edges: event.target.checked ? [...graph.edges, { source: item.id, target: node.id, kind: 'prerequisite' }] : graph.edges.filter(edge => !(edge.source === item.id && edge.target === node.id)) })}/>{item.title}</label>)}</div>
            {!published && <div className="actions"><button className="secondary" disabled={!graphDirty}>保存图谱修改</button>
              <button className="quiet" type="button" disabled={graph.nodes.length <= 1} onClick={() => { updateGraph({ ...graph, nodes: graph.nodes.filter(item => item.id !== node.id), edges: graph.edges.filter(edge => edge.source !== node.id && edge.target !== node.id) }); setSelected(''); }}>删除该节点</button>
              <button className="quiet" type="button" disabled={graph.nodes.length >= 30} onClick={() => { const id = crypto.randomUUID(); updateGraph({ ...graph, nodes: [...graph.nodes, { id, title: '新增节点', explanation: '补充节点说明', learning_outcome: '补充学习成果', estimated_minutes: 20, priority: 3, citation_ids: [] }] }); setSelected(id); }}>添加节点</button>
            </div>}
          </fieldset></form>}
        </details>
        <p className="muted small">来源：{graph.source_mode === 'documents' ? '已绑定资料' : graph.source_mode === 'edited' ? '经人工修改，来源不代表修改后内容已验证' : '通用知识，未声明资料来源'}。来源定位以服务器已保存版本为准。</p>
        <Citations citationMap={plan.graph?.citation_map || {}} endpoint={`/api/goals/${goalId}/graph/citations/{citationId}?version=${plan.version}`} goalId={goalId}/>
        <div className="publish-bar"><span className="muted">{graphDirty || goalDirty ? '有未确认或未保存修改，请先保存。' : published ? '已发布图谱只读；调整请使用下方提案。' : '只有明确审核发布，图谱才用于节点学习。'}</span>
          {published ? <button onClick={() => navigateWorkbench(workbenchHref({ tool: undefined }))}>返回工作台浏览节点</button> : <button disabled={routeLocked || !!feedback.trim() || !plan.graph || !orderedStages(graph).length} onClick={() => { void write(`/goals/${goalId}/graph/publish`, { expected_version: plan.version, expected_revision: graph.revision }); }}>审核完成，发布图谱</button>}
        </div>
      </>}
    </section>
    {published && plan.graph && !goalDirty && !graphDirty && <ProposalPanel goalId={goalId} graph={plan.graph} refreshKey={plan.version} onAccepted={acceptPlan}/>}
  </div>;
}
