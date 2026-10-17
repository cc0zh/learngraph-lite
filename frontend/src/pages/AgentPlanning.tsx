import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api, HttpError } from '../api';
import { ErrorBox, PendingRequest, RunStatus, SafeMarkdown } from '../components';
import { Citations } from '../documents';
import type { Goal, Plan, PlanningAnswer, PlanningCard, Run } from '../types';
import { useRuns } from '../useRuns';
import { orderedStages, RouteOverview } from './RouteOverview';
import { MessageComposer } from '../MessageComposer';

function sameInputs(a: Goal, b: Goal) {
  return ['title', 'desired_outcome', 'current_level', 'constraints'].every(key => String(a[key as keyof Goal]).trim() === String(b[key as keyof Goal]).trim())
    && a.time_budget_minutes === b.time_budget_minutes
    && JSON.stringify([...(a.skipped_fields || [])].sort()) === JSON.stringify([...(b.skipped_fields || [])].sort());
}

function GoalFacts({ goal }: { goal: Goal }) {
  return <dl className="goal-summary"><dt>主题与范围</dt><dd>{goal.title}</dd>
    {goal.desired_outcome && <><dt>希望理解的内容</dt><dd>{goal.desired_outcome}</dd></>}
    <dt>已有背景（用户自述）</dt><dd>{goal.current_level || '未说明，可在学习中继续补充'}</dd>
    {goal.constraints && <><dt>关注重点</dt><dd>{goal.constraints}</dd></>}
    {goal.time_budget_minutes && <><dt>投入参考（非完成承诺）</dt><dd>{goal.time_budget_minutes} 分钟</dd></>}
  </dl>;
}

function Questions({ run, card, locked, send }: { run: Run; card: Extract<PlanningCard, { kind: 'questions' }>; locked: boolean; send: (text: string, answers: PlanningAnswer[]) => Promise<boolean | undefined> }) {
  const key = `learngraph:planning:answers:${run.run_id}`;
  const [answers, setAnswers] = useState<Record<string, PlanningAnswer>>(() => JSON.parse(localStorage.getItem(key) || '{}'));
  function answer(question_id: string, value: string, skipped = false) {
    const next = { ...answers, [question_id]: { question_id, value, skipped } };
    setAnswers(next); localStorage.setItem(key, JSON.stringify(next));
  }
  const ready = card.questions.every(q => answers[q.id]?.skipped || answers[q.id]?.value.trim());
  return <section className="planning-card" aria-label="澄清问题"><h3>{card.title}</h3>
    <p className="muted small">可以回答，也可以直接在下方提问或说明想法。不确定的项目可跳过。</p>
    <form onSubmit={event => { event.preventDefault();
      const values = card.questions.map(q => answers[q.id]);
      void send(card.questions.map(q => `${q.prompt}：${answers[q.id].skipped ? '暂时跳过' : answers[q.id].value}`).join('\n'), values);
    }}><fieldset disabled={locked}>
      {card.questions.map(q => <div className="planning-question" key={q.id}>
        <h4>{q.prompt}</h4><p className="muted small">为什么问：{q.reason}</p>
        <div className="guide-options">{q.options.map(option => <button key={option.id} type="button" className={!answers[q.id]?.skipped && answers[q.id]?.value === option.value ? 'selected' : 'quiet'} aria-pressed={!answers[q.id]?.skipped && answers[q.id]?.value === option.value} onClick={() => answer(q.id, option.value)}>{option.label}</button>)}</div>
        <label>{q.prompt}（自定义回答）<textarea value={answers[q.id]?.value || ''} maxLength={2000} onChange={event => answer(q.id, event.target.value)}/></label>
        {q.allow_skip && <button type="button" className={answers[q.id]?.skipped ? 'selected' : 'quiet'} aria-pressed={!!answers[q.id]?.skipped} onClick={() => answer(q.id, '', !answers[q.id]?.skipped)}>跳过：{q.prompt}</button>}
      </div>)}
      <button type="submit" disabled={!ready}>发送这些回答</button>
    </fieldset></form>{locked && <p className="muted small">历史卡片只读，或当前正在处理请求。请使用最新方案。</p>}
  </section>;
}

const continueText = '目标已由我确认，请根据已确认目标生成学习图谱，给我审核，不要发布。';
export function AgentPlanning({ goalId, sidebarTarget, onPlanChange }: {
  goalId: string; sidebarTarget?: HTMLElement | null; onPlanChange?: (plan: Plan) => void;
}) {
  const scope = `learngraph:planning:${goalId}`;
  const [plan, setPlan] = useState<Plan>();
  const [form, setForm] = useState<Goal | undefined>(() => JSON.parse(localStorage.getItem(`${scope}:edit`) || 'null') || undefined);
  const [editing, setEditing] = useState(!!form);
  const [text, setText] = useState(() => localStorage.getItem(`${scope}:text`) || '');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(() => localStorage.getItem(`${scope}:notice`) || '');
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(true);
  const [uncertain, setUncertain] = useState(() => !!localStorage.getItem(`${scope}:confirmation`));
  const dirty = useRef(!!form);
  const currentForm = useRef<Goal | undefined>(form);
  const planRef = useRef<Plan | undefined>(undefined);
  const planChanged = useRef(onPlanChange);
  planChanged.current = onPlanChange;
  const acceptPlan = useCallback((value: Plan) => {
    planRef.current = value; setPlan(value); planChanged.current?.(value);
  }, []);
  const epoch = useRef(0);
  const writing = useRef(false);
  const history = useRef<HTMLDivElement>(null);
  const refresh = useCallback(async () => {
    const version = ++epoch.current; setChecking(true);
    try {
      const value = await api<Plan>(`/goals/${goalId}`);
      if (version !== epoch.current) return;
      acceptPlan(value);
      const pendingConfirmation = JSON.parse(localStorage.getItem(`${scope}:confirmation`) || 'null') as { expected_version: number; goal: Goal } | null;
      // Read acknowledgement only. A lost confirm response never authorizes a
      // second confirm or a model continuation on mount/refresh.
      if (pendingConfirmation && value.version > pendingConfirmation.expected_version && value.goal.confirmed && sameInputs(value.goal, pendingConfirmation.goal)) {
        if (currentForm.current && sameInputs(currentForm.current, pendingConfirmation.goal)) {
          dirty.current = false; setEditing(false); localStorage.removeItem(`${scope}:edit`);
        }
        setUncertain(false); localStorage.removeItem(`${scope}:confirmation`);
      } else if (pendingConfirmation && value.version === pendingConfirmation.expected_version) {
        setUncertain(false); localStorage.removeItem(`${scope}:confirmation`);
      }
      if (!dirty.current) { currentForm.current = value.goal; setForm(value.goal); }
      setError('');
      setChecking(false);
    } catch (e) { if (version === epoch.current) { setError(`读取当前方案失败：${String(e)}。请查询状态后再操作。`); } }
  }, [goalId, scope, acceptPlan]);
  const tasks = useRuns(`planning:${goalId}`, () => { void refresh(); });
  useEffect(() => { void refresh(); return () => { ++epoch.current; }; }, [refresh]);
  const latestRun = tasks.runs.at(-1);
  const hasPlan = !!plan;
  useEffect(() => {
    const container = history.current;
    const latestTurn = container?.querySelector<HTMLElement>('.turn:last-child');
    if (!container || !latestTurn) return;
    // Keep new turns and completed cards in the conversation viewport, without
    // moving the page or chasing every token while the user reviews history.
    container.scrollTop += latestTurn.getBoundingClientRect().top - container.getBoundingClientRect().top;
  }, [latestRun?.run_id, latestRun?.status, hasPlan]);
  function changeText(value: string) { setText(value); localStorage.setItem(`${scope}:text`, value); }
  const published = plan?.graph?.status === 'published';
  const busy = saving || checking || tasks.busy;
  const latestCardRun = [...tasks.runs].reverse().find(run => run.status === 'completed' && run.output?.planning_agent?.card);
  const consumed = new Set(tasks.runs.map(run => run.response_to_run_id || run.output?.planning_agent?.response_to_run_id).filter(Boolean));
  const cardCurrent = (run: Run) => !published && !busy && !uncertain && !dirty.current && !consumed.has(run.run_id)
    && run.run_id === latestCardRun?.run_id && run.output?.planning_agent?.planning.version === plan?.version;
  const savedRouteNeedsReview = !!plan?.graph && !published && plan.goal.confirmed
    && !tasks.runs.some(run => run.status === 'completed' && run.output?.planning_agent?.card?.kind === 'route_review' && run.output.planning_agent.planning.version === plan.version);
  const savedRouteAvailable = savedRouteNeedsReview && !busy && !uncertain && !dirty.current
    && !tasks.runs.some(run => (run.output?.planning_agent?.planning.version ?? -1) > (plan?.version ?? -1));

  async function send(user_text: string, response_to_run_id?: string, answers?: PlanningAnswer[], confirmedPlan?: Plan) {
    const current = confirmedPlan || planRef.current;
    if (!current || current.graph?.status === 'published' || (!confirmedPlan && (busy || dirty.current || uncertain))) return;
    ++epoch.current; setChecking(true);
    const accepted = await tasks.execute({ path: `/goals/${goalId}/planning-runs`, body: {
      request_id: crypto.randomUUID(), expected_version: current.version, user_text,
      ...(response_to_run_id ? { response_to_run_id } : {}), ...(answers ? { answers } : {}),
    } });
    if (accepted) { setNotice(''); localStorage.removeItem(`${scope}:notice`); }
    await refresh();
    return accepted;
  }
  function updateGoal(patch: Partial<Goal>) {
    if (!currentForm.current) return;
    dirty.current = true; currentForm.current = { ...currentForm.current, ...patch };
    setForm(currentForm.current); localStorage.setItem(`${scope}:edit`, JSON.stringify(currentForm.current));
  }
  function openEditor(goal: Goal) {
    currentForm.current = { ...goal }; setForm(currentForm.current); setEditing(true);
    dirty.current = true; localStorage.setItem(`${scope}:edit`, JSON.stringify(currentForm.current));
  }
  function discardEdit() {
    dirty.current = false; setEditing(false); localStorage.removeItem(`${scope}:edit`);
    currentForm.current = planRef.current?.goal; setForm(currentForm.current);
  }
  async function confirmGoal(goal: Goal) {
    const current = planRef.current;
    if (!current || tasks.busy || checking || writing.current || published || uncertain) return;
    writing.current = true; ++epoch.current; setSaving(true); setError('');
    const body = { expected_version: current.version, title: goal.title, desired_outcome: goal.desired_outcome,
      current_level: goal.current_level, time_budget_minutes: goal.time_budget_minutes, constraints: goal.constraints, skipped_fields: goal.skipped_fields || [] };
    localStorage.setItem(`${scope}:confirmation`, JSON.stringify({ expected_version: current.version, goal }));
    try {
      const confirmed = await api<Plan>(`/goals/${goalId}/confirm`, body);
      localStorage.removeItem(`${scope}:confirmation`); setUncertain(false);
      dirty.current = false; setEditing(false); localStorage.removeItem(`${scope}:edit`);
      currentForm.current = confirmed.goal; setForm(confirmed.goal); acceptPlan(confirmed);
      // Only this click (not a read or reload) authorizes the next model run.
      const accepted = await send(continueText, undefined, undefined, confirmed);
      if (!accepted) setError('目标已确认，生成图谱的请求未成功确认。可查询运行状态、恢复未确认请求，或显式继续生成图谱。');
    } catch (e) {
      if (e instanceof HttpError && e.status >= 400 && e.status < 500) {
        localStorage.removeItem(`${scope}:confirmation`);
        setError(`确认被拒绝：${e.message}。编辑已保留，请先刷新当前方案。`); setChecking(true);
      } else {
        setUncertain(true); setError(`确认结果尚不确定：${String(e)}。输入已保留，请刷新目标与路线；不会再次确认或自动调用模型。`);
      }
    } finally { writing.current = false; setSaving(false); }
  }
  async function publish(run?: Run) {
    const current = planRef.current;
    if (!current?.graph || !current.goal.confirmed || !(run ? cardCurrent(run) : savedRouteAvailable) || writing.current) return;
    writing.current = true; ++epoch.current; setSaving(true); setError('');
    try {
      const value = await api<Plan>(`/goals/${goalId}/graph/publish`, { expected_version: current.version, expected_revision: current.graph.revision });
      acceptPlan(value);
    } catch (e) { setChecking(true); setError(`发布结果需要查询：${String(e)}。请刷新当前方案，不会自动重发。`); }
    finally { writing.current = false; setSaving(false); }
  }

  if (!plan) return <div className="agent-planning-embedded"><ErrorBox error={error}/><p role="status">正在读取目标…</p><button className="quiet" onClick={() => { void refresh(); }}>刷新目标与路线</button></div>;
  const canTalk = !published && !busy && !dirty.current && !uncertain;
  const currentPlan = <aside className="panel current-plan" aria-label="当前方案"><div className="section-title"><h2>当前方案</h2><span className="tag">v{plan.version}</span></div>
    <p className="muted small">以下是服务器保存的当前事实，与历史卡片和本地编辑分开显示。</p><h3>{plan.goal.confirmed ? '已确认目标' : '待确认目标'}</h3>
    <GoalFacts goal={plan.goal}/>
    {!published && !editing && <button className="quiet" disabled={busy || uncertain} onClick={() => openEditor(plan.goal)}>编辑当前目标</button>}
    {editing && form && !published && <form className="summary-editor" aria-label="本地目标编辑" onSubmit={event => { event.preventDefault(); void confirmGoal(form); }}><h3>本地编辑（尚未确认）</h3><fieldset disabled={saving || tasks.busy || uncertain}>
      <label>目标<input required maxLength={2000} value={form.title} onChange={event => updateGoal({ title: event.target.value })}/></label>
      <label>期望成果<textarea maxLength={2000} value={form.desired_outcome} onChange={event => updateGoal({ desired_outcome: event.target.value, skipped_fields: (form.skipped_fields || []).filter(field => field !== 'desired_outcome') })}/></label>
      <label>已有基础（用户自述，未验证）<textarea maxLength={2000} value={form.current_level} onChange={event => updateGoal({ current_level: event.target.value, skipped_fields: (form.skipped_fields || []).filter(field => field !== 'current_level') })}/></label>
      <label>可投入时间（总分钟）<input type="number" min="1" step="1" value={form.time_budget_minutes ?? ''} onChange={event => updateGoal({ time_budget_minutes: event.target.value ? Number(event.target.value) : null, skipped_fields: (form.skipped_fields || []).filter(field => field !== 'time_budget_minutes') })}/></label>
      <label>其他约束与重点<textarea maxLength={2000} value={form.constraints} onChange={event => updateGoal({ constraints: event.target.value })}/></label>
      <p className="muted small">确认修改会使旧路线失效，并调用模型生成新图谱草稿。</p>
      <div className="actions"><button disabled={checking}>确认目标并生成图谱</button><button type="button" className="quiet" onClick={discardEdit}>放弃本地编辑</button></div>
    </fieldset></form>}
    {plan.graph ? <details className="current-route"><summary>{savedRouteNeedsReview ? '审核已保存路线草稿' : '当前路线'} · {plan.graph.nodes.length} 个阶段 · {plan.graph.nodes.reduce((sum, node) => sum + node.estimated_minutes, 0)} 分钟</summary>
      <RouteOverview graph={plan.graph} goal={plan.goal} knowledgeMap/>
      {savedRouteNeedsReview && <><p className="muted small">这份草稿已保存，但没有可操作的对话审核卡。请直接审核当前服务器版本；确认只发布这份路线，不会调用模型。</p>
        <button disabled={!savedRouteAvailable || !orderedStages(plan.graph).length} onClick={() => { void publish(); }}>确认并发布路线</button></>}
    </details> : <p className="muted small">还没有路线。先讨论并明确确认目标。</p>}
    {published && <p className="hint">图谱已发布，请在“图谱与节点”区域选择节点开始学习。</p>}
  </aside>;
  return <div className="agent-planning agent-planning-embedded">
    <ErrorBox error={error || tasks.error || notice}/>
    <PendingRequest command={tasks.pending} checked={tasks.pendingChecked} sending={tasks.sending} readOnly={!!published} query={() => { void tasks.refresh(); void refresh(); }} resend={() => { if (!published) void tasks.recover(); }}/>
    {published && <p className="hint">这张图谱已发布，不再调用规划模型修改。请在“图谱与节点”区域选择节点开始学习；调整通过“图谱管理”审核提案。</p>}
    <div className="agent-plan-main"><section className="panel planning-dialogue" aria-label="规划对话">
      <div className="section-title"><h2>一起规划</h2><button type="button" className="quiet" disabled={saving || tasks.sending} onClick={() => { void tasks.refresh(); void refresh(); }}>刷新目标与路线</button></div>
      <p className="muted small">直接说想法、追问原因或提出调整。模型可以提出草稿，但不能替你确认目标或发布路线。</p>
      <div className="planning-history" ref={history} aria-label="规划对话记录" aria-live="polite">
        {!tasks.runs.length && <div className="empty"><h3>从你现在的想法开始</h3><p>这里还没有对话。刷新只会读取；点击下方按钮才会调用模型。</p>
          <button disabled={!canTalk} onClick={() => { void send(plan.goal.title); }}>让 Agent 开始规划</button></div>}
        {tasks.runs.map(run => {
          const output = run.output?.planning_agent;
          const card = output?.card;
          const activeCard = cardCurrent(run);
          return <article className="turn" key={run.run_id}>
            <div className="user-message"><strong>你</strong><SafeMarkdown>{run.user_text}</SafeMarkdown></div>
            <div className="assistant-message"><strong>Agent</strong><SafeMarkdown>{run.final_text || run.partial_text || (run.status === 'completed'
              ? card?.kind === 'questions' ? '请查看下方问题卡。' : card ? '已提出待审核方案，请查看下方卡片。' : '本轮已完成，当前方案未改变。'
              : run.error || ['failed', 'cancelled', 'interrupted', 'budget_exceeded'].includes(run.status) ? '本轮未完成，输入仍保留在对话记录中。' : '正在整理公开回复…')}</SafeMarkdown></div>
            {run.status === 'completed' && output && card && <>
              {card.kind === 'questions' && <Questions run={run} card={card} locked={!activeCard} send={(value, answers) => send(value, run.run_id, answers)}/>}
              {card.kind === 'goal_review' && <section className="planning-card" aria-label="目标审核"><div className="section-title"><h3>目标摘要</h3><span className="tag">方案 v{output.planning.version}</span></div>
                <GoalFacts goal={output.planning.goal}/>
                <p className="muted small">确认的是学习意图，不是能力认证。点击确认会保存目标，并调用模型生成图谱草稿，不会发布。</p>
                <div className="actions"><button disabled={!activeCard} onClick={() => { void confirmGoal(output.planning.goal); }}>确认目标并生成图谱</button>
                  <button className="quiet" disabled={!activeCard} onClick={() => openEditor(output.planning.goal)}>修改摘要</button></div>
                {!activeCard && <p className="muted small">此卡只读。以右侧当前方案和最新可用卡片为准。</p>}
              </section>}
              {card.kind === 'route_review' && output.planning.graph && <section className="planning-card" aria-label="路线审核"><div className="section-title"><h3>路线草稿</h3><span className="tag">方案 v{output.planning.version}</span></div>
                <RouteOverview graph={output.planning.graph} goal={output.planning.goal} knowledgeMap/>
                <Citations citationMap={output.planning.graph.citation_map || {}} endpoint={`/api/goals/${goalId}/graph/citations/{citationId}?version=${output.planning.version}`} goalId={goalId}/>
                <p className="muted small">有疑问？直接在下方要求解释或调整。确认只发布图谱，不会自动发起学习；发布后请在“图谱与节点”选择节点。</p>
                <button disabled={!activeCard || !orderedStages(output.planning.graph).length} onClick={() => { void publish(run); }}>确认并发布路线</button>
                {!activeCard && <p className="muted small">此卡只读。以当前方案和最新可用卡片为准。</p>}
              </section>}
            </>}
            {run.status === 'completed' && output?.changes && <section className="route-diff" aria-label="路线变更"><h3>本轮路线变更（程序对比）</h3>
              <p>预计投入：{output.changes.before_minutes} → {output.changes.after_minutes} 分钟</p>
              {(['added', 'removed', 'updated'] as const).map(key => <p key={key}><strong>{{ added: '新增', removed: '移除', updated: '修改' }[key]}：</strong>{output.changes![key].map(id => output.changes!.node_titles?.[id] || id).join('、') || '无'}</p>)}
            </section>}
          </article>;
        })}
      </div>
      <RunStatus run={tasks.runs.at(-1)} stop={tasks.stop} retry={tasks.retry} readOnly={!!tasks.pending || !!published || saving || (!tasks.active && (checking || dirty.current || uncertain))}/>
      {!published && plan.goal.confirmed && !plan.graph && <div className="hint"><p>目标已确认。生成图谱需要你显式授权；刷新不会自动继续。</p><button disabled={!canTalk} onClick={() => { void send(continueText); }}>继续生成图谱</button></div>}
      {!published && <MessageComposer id={`planning-input-${goalId}`} label="和 Agent 讨论目标与路线" value={text} onChange={changeText} onSubmit={() => { const submitted = text.trim();
        void send(submitted).then(accepted => { if (accepted) setText(value => { if (value === submitted || value.trim() === submitted) { localStorage.removeItem(`${scope}:text`); return ''; } return value; }); });
      }} maxLength={2000} placeholder="例如：为什么先学这个？我只有两小时，想多做实践。" submitLabel="发送消息" disabled={!canTalk || !text.trim()}
        note={<><span>发送会调用模型。可以随时提问，不必先回答卡片问题。</span>{dirty.current && <p className="hint">摘要有本地编辑，请先确认或放弃编辑，再继续对话。输入不会被刷新覆盖。</p>}</>}>
        <span>目标与路线对话</span>
      </MessageComposer>}
    </section>
    {sidebarTarget ? createPortal(currentPlan, sidebarTarget) : null}</div>
  </div>;
}
