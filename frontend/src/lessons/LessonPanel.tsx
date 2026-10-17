import { useCallback, useEffect, useRef, useState } from 'react';
import { api, sessionFor, terminal } from '../api';
import { ErrorBox, PendingRequest, RunCitations, RunStatus } from '../components';
import { Citations } from '../documents';
import type { Feedback } from '../types';
import { useRuns } from '../useRuns';
import type { Command } from '../useRuns';
import { LessonMarkdown } from './LessonMarkdown';
import { QuizCard } from './QuizCard';
import { acknowledge, newEvent, readSaved, useSaved } from './persistence';
import type { ExplanationLink, PublicExercise, PublicLesson, SavedEvent, ValidComponent } from './types';
import { validComponent } from './types';
import './lessons.css';

type Tasks = ReturnType<typeof useRuns>;
const readonly = (lesson: PublicLesson) => lesson.schema_version !== 1 || lesson.outdated;
const eventScope = (lesson: PublicLesson, componentId: string) => `learngraph:lesson:${lesson.goal_id}:${lesson.id}:${lesson.version}:${componentId}`;

function Explanation({ lesson, componentId, sourceEvent, tasks, session, inlineExplanation, sourceLabel, onAcknowledged }: {
  lesson: PublicLesson; componentId: string; sourceEvent?: SavedEvent; tasks: Tasks; session: string;
  inlineExplanation: boolean; sourceLabel: string;
  onAcknowledged?: (event: SavedEvent) => void;
}) {
  // A step transition is a new logical explanation. Explicit re-explanation alone changes its slot.
  const key = `${eventScope(lesson, componentId)}:explanation:${sourceEvent?.event_id || 'component'}${inlineExplanation ? `:${session}` : ''}`;
  const [link, saveLink] = useSaved<ExplanationLink | undefined>(key, undefined);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const locked = readonly(lesson);
  function commandFor(runId: string) { return readSaved<Command | undefined>(`learngraph:command:${session}:${runId}`, undefined); }
  const related = tasks.runs.filter(run => {
    const body = commandFor(run.run_id)?.body;
    return run.mode === 'explanation' && !!link && body?.source_event_id === link.event.event_id && body?.explanation_slot === link.slot;
  });
  const latest = related.at(-1);
  async function explain(again = false) {
    if (locked || saving || tasks.busy) return;
    setSaving(true); setError('');
    // Persist BEFORE either POST: losing an ACK or run response must retain both identities.
    let current = link;
    // Slots are deduplicated by event (not session) on the server. A shared step
    // event therefore needs its own persisted initial slot in each conversation.
    if (!current) current = { event: sourceEvent || newEvent(lesson, componentId, 'request_explanation'), slot: inlineExplanation ? crypto.randomUUID() : 'initial', requestId: crypto.randomUUID() };
    else if (again) current = { ...current, slot: crypto.randomUUID(), requestId: crypto.randomUUID() };
    saveLink(current);
    try {
      if (!current.event.acknowledged) {
        current = { ...current, event: await acknowledge(lesson, current.event) };
        saveLink(current);
        onAcknowledged?.(current.event);
      }
      // Restoring the same logical explanation also preserves any explicit retry command.
      const existing = !again && latest ? commandFor(latest.run_id) : undefined;
      await tasks.execute(existing || { path: `/sessions/${session}/runs`, body: {
        request_id: current.requestId, mode: 'explanation', goal_id: lesson.goal_id, node_id: lesson.node_id,
        source_event_id: current.event.event_id, explanation_slot: current.slot,
      } });
    } catch (e) { setError(`事件尚未确认：${String(e)}。请显式重试保存，未调用 Agent。`); }
    finally { setSaving(false); }
  }
  return <div className="lesson-explanation"><div className="lesson-actions">
    <button className="secondary" disabled={locked || saving || tasks.busy} onClick={() => { void explain(); }}>{saving ? '正在确认事件…' : link ? '恢复此解释' : '让 Agent 解释'}</button>
    {link?.event.acknowledged && <button className="quiet" disabled={locked || saving || tasks.busy} onClick={() => { void explain(true); }}>重新解释</button>}
  </div><ErrorBox error={error}/>
    {link && <p className="lesson-save">{inlineExplanation ? `解释请求：${link.event.acknowledged ? '来源已保存' : '来源尚未保存'}` : `解释事件：${link.event.acknowledged ? '已确认' : '尚未确认'} · slot：${link.slot}`}</p>}
    {inlineExplanation ? related.map(run => <article className="lesson-run lesson-explanation-run" aria-label="组件解释" key={run.run_id}>
      <strong>解释来源：{lesson.title} · 版本 {lesson.version} · {sourceLabel}</strong>
      <LessonMarkdown>{run.final_text || run.partial_text || '正在准备解释…'}</LessonMarkdown>
      <RunStatus run={run} stop={tasks.stop} retry={() => { void tasks.retry(run.run_id); }} readOnly={locked || run !== latest || !!tasks.pending || (tasks.busy && terminal(run.status))}/>
      <RunCitations run={run} goalId={lesson.goal_id} nodeId={lesson.node_id}/>
    </article>) : latest && <p className="lesson-save">此解释已关联运行 {latest.run_id}；状态与内容见下方解释会话。</p>}
  </div>;
}

function MarkRead({ lesson, componentId }: { lesson: PublicLesson; componentId: string }) {
  const [event, saveEvent] = useSaved<SavedEvent | undefined>(`${eventScope(lesson, componentId)}:mark_read`, undefined);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  async function mark() {
    if (readonly(lesson) || saving || event?.acknowledged) return;
    const current = event || newEvent(lesson, componentId, 'mark_read');
    saveEvent(current); setSaving(true); setError('');
    try { saveEvent(await acknowledge(lesson, current)); }
    catch (e) { setError(`尚未保存阅读记录：${String(e)}`); }
    finally { setSaving(false); }
  }
  return <div className="lesson-actions"><button className="quiet" disabled={readonly(lesson) || saving || event?.acknowledged} onClick={() => { void mark(); }}>{event?.acknowledged ? '已读（已保存）' : event ? '重试保存已读' : '标记已读'}</button><span className="lesson-save">阅读记录不改变成绩</span><ErrorBox error={error}/></div>;
}

function Stepper({ lesson, component, tasks, session, inlineExplanation, sourceLabel }: { lesson: PublicLesson; component: Extract<ValidComponent, { kind: 'stepper' }>; tasks: Tasks; session: string; inlineExplanation: boolean; sourceLabel: string }) {
  const stepKey = `${eventScope(lesson, component.id)}:step`;
  const [saved, save] = useSaved<{ step: number; event?: SavedEvent }>(stepKey, { step: 0 });
  const step = Number.isInteger(saved.step) && saved.step >= 0 && saved.step < component.props.steps.length ? saved.step : 0;
  const current = component.props.steps[step];
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  async function change(index: number, retry = false) {
    if (readonly(lesson) || saving) return;
    const event = retry && saved.event ? saved.event : newEvent(lesson, component.id, 'step_changed', { step: index });
    save({ step: index, event }); setSaving(true); setError('');
    try { save({ step: index, event: await acknowledge(lesson, event) }); }
    catch (e) { setError(`步骤仅在本地更新，尚未保存：${String(e)}`); }
    finally { setSaving(false); }
  }
  return <><div className="lesson-step"><h3>{current.title}</h3><p className="scope-label">步骤 {step + 1} / {component.props.steps.length}</p><LessonMarkdown>{current.description}</LessonMarkdown>{current.slots.text && <LessonMarkdown>{current.slots.text}</LessonMarkdown>}</div>
    <div className="lesson-actions"><button className="quiet" disabled={readonly(lesson) || saving || step === 0} onClick={() => { void change(step - 1); }}>上一步</button>
      <button className="secondary" disabled={readonly(lesson) || saving || step === component.props.steps.length - 1} onClick={() => { void change(step + 1); }}>下一步</button>
      <button className="quiet" disabled={readonly(lesson) || saving} onClick={() => { void change(0); }}>重置步骤</button>
      {saved.event && !saved.event.acknowledged && <button className="quiet" disabled={readonly(lesson) || saving} onClick={() => { void change(step, true); }}>重试保存步骤</button>}
    </div><p className="lesson-save">{saved.event ? saved.event.acknowledged ? '步骤已保存' : '步骤尚未保存' : '步骤仅在本地'} · 切换步骤不调用模型、不改变成绩</p><ErrorBox error={error}/>
    <Explanation key={saved.event?.event_id || 'initial'} lesson={lesson} componentId={component.id} sourceEvent={saved.event} tasks={tasks} session={session} inlineExplanation={inlineExplanation} sourceLabel={`${sourceLabel} · 步骤 ${step + 1}：${current.title}`} onAcknowledged={event => {
      const current = readSaved(stepKey, saved);
      // A late ACK must not overwrite a newer step transition or the initial explanation link.
      if (current.event?.event_id === event.event_id) save({ ...current, event });
    }}/>
  </>;
}

function LessonQuiz({ lesson, exerciseId, onChanged }: { lesson: PublicLesson; exerciseId: string; onChanged?: () => void | Promise<void> }) {
  const [exercise, setExercise] = useState<PublicExercise>();
  const [feedback, setFeedback] = useState<Feedback>();
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try {
      const [publicExercise, history] = await Promise.all([
        api<PublicExercise>(`/goals/${lesson.goal_id}/exercises/${exerciseId}`),
        api<{ feedback: Feedback | null }>(`/goals/${lesson.goal_id}/exercises/${exerciseId}/feedback`),
      ]);
      if (publicExercise.goal_id !== lesson.goal_id || publicExercise.node_id !== lesson.node_id || publicExercise.graph_content_revision !== lesson.graph_content_revision) throw new Error('题目不属于此学习包节点和内容版本。');
      // Public exercise never includes the answer. Feedback exists only after a real attempt.
      setFeedback(history.feedback || undefined); setExercise(publicExercise); setError('');
    } catch (e) { setError(String(e)); }
  }, [lesson.goal_id, lesson.node_id, lesson.graph_content_revision, exerciseId]);
  useEffect(() => { void load(); }, [load]);
  return <><ErrorBox error={error}/>{exercise ? <QuizCard goalId={lesson.goal_id} exercise={exercise} title="学习包练习" feedback={feedback} readOnly={readonly(lesson)} onChanged={async () => { await load(); await onChanged?.(); }}/>
    : <p className="muted">正在读取服务端题目…</p>}{/* Exercise citations belong exclusively to exercise.citation_map. */}</>;
}

function LessonDetail({ lesson, tasks, session, inlineExplanation, onChanged }: { lesson: PublicLesson; tasks: Tasks; session: string; inlineExplanation: boolean; onChanged?: () => void | Promise<void> }) {
  const ids = new Set<string>();
  return <article aria-label="学习包详情"><h3>{lesson.title}</h3><p className="muted small">版本 {lesson.version} · 内容修订 {lesson.graph_content_revision} · {lesson.source_mode === 'documents' ? '资料辅助' : '通用知识'}</p>
    {readonly(lesson) && <p className="hint" role="status">{lesson.schema_version !== 1 ? '历史 schema 0 / 不支持的学习包' : '内容版本已过期'}：只读，不接受作答、事件或解释。可生成新的学习包。</p>}
    <section className="lesson-block" aria-label="学习包章节"><LessonMarkdown>{lesson.markdown}</LessonMarkdown><MarkRead lesson={lesson} componentId="chapter"/><Explanation lesson={lesson} componentId="chapter" tasks={tasks} session={session} inlineExplanation={inlineExplanation} sourceLabel="章节正文"/></section>
    {(Array.isArray(lesson.components) ? lesson.components : []).slice(0, 19).map((raw, index) => {
      const component = validComponent(raw);
      if (!component || ids.has(component.id)) return <section className="lesson-block" key={`unsupported-${index}`}><p className="hint">不支持或无效的学习组件（仅安全占位，不执行内容）。</p></section>;
      ids.add(component.id);
      const sourceLabel = `教学组件 ${index + 1} · ${{ markdown: '阅读内容', quiz_choice: '练习', stepper: '分步学习', comparison_table: '对照表' }[component.kind]}`;
      return <section className="lesson-block" data-component-kind={component.kind} key={component.id} aria-label={`学习组件 ${component.kind}`}>
        {component.kind === 'markdown' && <><LessonMarkdown>{component.props.text}</LessonMarkdown><MarkRead lesson={lesson} componentId={component.id}/></>}
        {component.kind === 'quiz_choice' && <LessonQuiz lesson={lesson} exerciseId={component.props.exercise_id} onChanged={onChanged}/>}
        {component.kind === 'stepper' && <Stepper lesson={lesson} component={component} tasks={tasks} session={session} inlineExplanation={inlineExplanation} sourceLabel={sourceLabel}/>}
        {component.kind === 'comparison_table' && <div className="lesson-table"><table><thead><tr>{component.props.columns.map((column, i) => <th key={i} scope="col">{column}</th>)}</tr></thead><tbody>{component.props.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}><LessonMarkdown>{cell}</LessonMarkdown></td>)}</tr>)}</tbody></table></div>}
        {component.kind !== 'stepper' && <Explanation lesson={lesson} componentId={component.id} tasks={tasks} session={session} inlineExplanation={inlineExplanation} sourceLabel={sourceLabel}/>}
      </section>;
    })}
    <Citations citationMap={lesson.citation_map || {}} unverifiedIds={lesson.unverified_citation_ids}
      endpoint={`/api/goals/${lesson.goal_id}/lessons/${lesson.id}/citations/{citationId}`} goalId={lesson.goal_id} nodeId={lesson.node_id}/>
  </article>;
}

interface LessonPanelProps { goalId: string; nodeId: string; conversationId?: string; refreshKey?: number; onChanged?: () => void | Promise<void> }

export function LessonPanel(props: LessonPanelProps) {
  // useRuns/useSaved retain scope-specific state; changing conversations must not
  // briefly expose or recover the previous conversation's commands or transcript.
  return <LessonPanelContent key={`${props.goalId}:${props.nodeId}:${props.conversationId || ''}`} {...props}/>;
}

function LessonPendingRequest({ tasks, inlineExplanation, locked = false, query, resend }: {
  tasks: Tasks; inlineExplanation: boolean; locked?: boolean; query: () => void; resend: () => void;
}) {
  if (!inlineExplanation) return <PendingRequest command={tasks.pending} checked={tasks.pendingChecked && !locked} sending={tasks.sending} query={query} resend={resend}/>;
  if (!tasks.pending) return null;
  return <div className="hint" role="region" aria-label="未确认请求恢复"><strong>请求尚未确认</strong>
    <p>输入已保留。请先查询状态，再显式恢复原请求；刷新不会重新生成。</p>
    <div className="actions"><button type="button" className="quiet" disabled={tasks.sending} onClick={query}>查询运行状态</button>
      <button type="button" disabled={!tasks.pendingChecked || locked || tasks.sending} onClick={resend}>重发未确认请求</button></div>
  </div>;
}

function LessonPanelContent({ goalId, nodeId, conversationId, refreshKey = 0, onChanged }: LessonPanelProps) {
  const [lessons, setLessons] = useState<PublicLesson[]>([]);
  const [selected, saveSelected] = useSaved(`learngraph:lesson-selected:${goalId}:${nodeId}`, '');
  const [detail, setDetail] = useState<PublicLesson>();
  const [exercises, setExercises] = useState<PublicExercise[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const latestRequested = useRef(false);
  const generationBaseline = useRef(0);
  const queryVersion = useRef(0);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const inlineExplanation = !!conversationId;
  const conversationScope = conversationId ? `:conversation:${conversationId}` : '';
  const generationSession = sessionFor(`lesson:${goalId}:${nodeId}${conversationScope}`);
  const explanationSession = sessionFor(`explanation:${goalId}:${nodeId}${conversationScope}`);
  const refresh = useCallback(async () => {
    const query = ++queryVersion.current;
    try {
      const [packages, questions] = await Promise.all([
        api<{ lessons: PublicLesson[] }>(`/goals/${goalId}/nodes/${nodeId}/lessons`),
        api<{ exercises: PublicExercise[] }>(`/goals/${goalId}/nodes/${nodeId}/exercises`),
      ]);
      if (query !== queryVersion.current) return;
      const list = [...packages.lessons].sort((a, b) => b.version - a.version);
      setLessons(list); setExercises(questions.exercises); setError('');
      setChosen(ids => ids.filter(id => questions.exercises.some(exercise => exercise.id === id)));
      const generated = latestRequested.current && (list[0]?.version || 0) > generationBaseline.current;
      const id = !generated && list.some(item => item.id === selectedRef.current) ? selectedRef.current : list[0]?.id || '';
      if (generated) latestRequested.current = false;
      localStorage.setItem(`learngraph:lesson-selected:${goalId}:${nodeId}`, JSON.stringify(id));
      saveSelected(id);
    } catch (e) { if (query === queryVersion.current) setError(String(e)); }
    finally { if (query === queryVersion.current) setLoading(false); }
  }, [goalId, nodeId]);
  const generation = useRuns(generationSession, () => { void refresh(); void onChanged?.(); });
  const explanations = useRuns(explanationSession, () => { void onChanged?.(); });
  useEffect(() => { void refresh(); }, [refresh, refreshKey]);
  useEffect(() => {
    setDetail(current => current?.id === selected ? current : undefined);
    if (!selected) return;
    let current = true;
    api<PublicLesson>(`/goals/${goalId}/lessons/${selected}`).then(lesson => { if (current) setDetail(lesson); }).catch(e => { if (current) setError(String(e)); });
    return () => { current = false; };
  }, [goalId, selected, lessons]);
  async function generate() {
    if (generation.busy || loading) return;
    ++queryVersion.current;
    generationBaseline.current = lessons[0]?.version || 0;
    latestRequested.current = true;
    await generation.execute({ path: `/goals/${goalId}/nodes/${nodeId}/lessons`, body: { session_id: generationSession, request_id: crypto.randomUUID(), purpose: '学习当前节点', exercise_ids: chosen.slice(0, 3) } });
  }
  const latestGeneration = generation.runs.filter(run => run.mode === 'lesson').at(-1);
  // Recovery belongs to its original package, not whichever version is currently selected.
  const pendingEventId = explanations.pending?.body.source_event_id;
  const pendingArtifact = typeof pendingEventId === 'string' ? readSaved<{ packageId: string } | undefined>(`learngraph:lesson-event:${pendingEventId}`, undefined) : undefined;
  const pendingLesson = lessons.find(lesson => lesson.id === pendingArtifact?.packageId);
  const recoveryLocked = loading || !pendingLesson || readonly(pendingLesson);
  return <div className={inlineExplanation ? 'lesson-content lesson-inline-explanations' : 'lesson-content'}><div className="lesson-header"><h2>学习包</h2><button className="quiet" onClick={() => { void refresh(); void generation.refresh(); void explanations.refresh(); }}>刷新学习包与状态</button></div>
    <p className="muted small">固定教学组件，步骤操作与阅读记录不改变成绩。只有提交练习答案产生作答证据。</p>
    <ErrorBox error={error || generation.error || explanations.error}/>
    <details><summary>选择已有题目加入学习包（最多 3 题）</summary><div className="lesson-selection">{!exercises.length && <p>请先在「练习与进度」生成题目，然后刷新学习包。</p>}{exercises.map((exercise, index) => <label key={exercise.id}><input type="checkbox" aria-label={`加入题目 ${index + 1}`} checked={chosen.includes(exercise.id)} disabled={generation.busy || (!chosen.includes(exercise.id) && chosen.length >= 3)} onChange={e => setChosen(ids => e.target.checked ? [...ids, exercise.id] : ids.filter(id => id !== exercise.id))}/><span>{exercise.prompt}</span></label>)}</div></details>
    <div className="lesson-actions"><button disabled={generation.busy || loading} onClick={() => { void generate(); }}>{lessons.length ? '重新生成学习包' : '生成学习包'}</button>
      {!!lessons.length && <label>学习包版本 <select aria-label="学习包版本" value={selected} onChange={e => saveSelected(e.target.value)}>{lessons.map(lesson => <option value={lesson.id} key={lesson.id}>版本 {lesson.version} · {lesson.title}{readonly(lesson) ? '（只读）' : ''}</option>)}</select></label>}
    </div>
    <LessonPendingRequest tasks={generation} inlineExplanation={inlineExplanation} query={() => { void generation.refresh(); }} resend={() => { latestRequested.current = true; void generation.recover(); }}/>
    {latestGeneration && <div className="lesson-run"><strong>{inlineExplanation ? '学习包生成' : '学习包生成 · lesson'}</strong><RunStatus run={latestGeneration} stop={generation.stop} retry={() => { latestRequested.current = true; void generation.retry(latestGeneration.run_id); }} readOnly={!!generation.pending}/></div>}
    <section aria-label="学习包解释会话"><LessonPendingRequest tasks={explanations} inlineExplanation={inlineExplanation} locked={recoveryLocked} query={() => { void explanations.refresh(); }} resend={() => { if (!recoveryLocked) void explanations.recover(); }}/>
      {explanations.pending && <p className="muted small">{inlineExplanation ? '恢复只处理原解释来源，不会创建新的解释。' : '解释会话与节点教学对话分别保存，恢复不提交客户端 user_text。'}</p>}
      {explanations.pending && recoveryLocked && <p className="hint">原解释学习包尚未读取、已过期或不可用；仅可查询，不接受重发。</p>}
    </section>
    {loading && <p role="status">正在读取学习包…</p>}
    {!loading && !lessons.length && <p className="empty">还没有学习包。生成章节、练习、步骤和对照表，按自己的节奏学习。</p>}
    {detail && <LessonDetail key={`${detail.id}:${detail.version}`} lesson={detail} tasks={explanations} session={explanationSession} inlineExplanation={inlineExplanation} onChanged={async () => { await refresh(); await onChanged?.(); }}/>}
    {!inlineExplanation && <section className="lesson-explanation-history" aria-label="学习包解释记录"><h3>Agent 解释会话 · explanation</h3>
      {!explanations.runs.some(run => run.mode === 'explanation') && <p className="muted small">解释与节点教学对话分开显示。只有明确点击解释按钮才调用 Agent。</p>}
      {explanations.runs.filter(run => run.mode === 'explanation').map(run => {
        const command = readSaved<Command | undefined>(`learngraph:command:${explanationSession}:${run.run_id}`, undefined);
        const eventId = command?.body.source_event_id;
        const artifact = typeof eventId === 'string' ? readSaved<{ packageId: string; componentId: string } | undefined>(`learngraph:lesson-event:${eventId}`, undefined) : undefined;
        const sourceLesson = lessons.find(lesson => lesson.id === artifact?.packageId);
        const superseded = explanations.runs.some(other => {
          if (other.run_id === run.run_id || explanations.runs.indexOf(other) < explanations.runs.indexOf(run)) return false;
          const body = readSaved<Command | undefined>(`learngraph:command:${explanationSession}:${other.run_id}`, undefined)?.body;
          return !!command && body?.source_event_id === eventId && body?.explanation_slot === command.body.explanation_slot;
        });
        return <article className="lesson-run lesson-explanation-run" aria-label="组件解释" key={run.run_id}><strong>Agent 解释 · {sourceLesson ? `版本 ${sourceLesson.version}` : '历史事件'} · {artifact?.componentId || '已保存事件'}</strong>
          <LessonMarkdown>{run.final_text || run.partial_text || '正在准备解释…'}</LessonMarkdown>
          <RunStatus run={run} stop={explanations.stop} retry={() => { void explanations.retry(run.run_id); }} readOnly={!sourceLesson || readonly(sourceLesson) || superseded || !!explanations.pending || (explanations.busy && terminal(run.status))}/>
          <RunCitations run={run} goalId={goalId} nodeId={nodeId}/>
        </article>;
      })}
    </section>}
  </div>;
}
