import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api, sessionFor } from '../api';
import { ErrorBox, GraphCanvas, PendingRequest, RunCitations, RunStatus, SafeMarkdown } from '../components';
import { DocumentBindings } from '../documents';
import type { Context, Exercise, Feedback, Graph, NextAction, Plan } from '../types';
import { useRuns } from '../useRuns';
import { LessonPanel } from '../lessons/LessonPanel';
import { QuizCard } from '../lessons/QuizCard';
import { ProposalPanel } from '../proposals/ProposalPanel';

const mastery: Record<string, string> = { unknown: '未开始', learning: '学习中', needs_review: '需要复习', proficient: '已掌握' };

function NodeLearning({ goalId, nodeId, onSelect, onResult }: { goalId: string; nodeId: string; onSelect: (id: string) => void; onResult: () => void }) {
  const [context, setContext] = useState<Context>();
  const [next, setNext] = useState<NextAction>();
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [feedback, setFeedback] = useState<Record<string, Feedback>>({});
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [tab, setTab] = useState('chat');
  const [resultVersion, setResultVersion] = useState(0);
  const scope = `learn:${goalId}:${nodeId}`;
  // Keep valid legacy sessions/history; long scopes need a bounded persisted ID.
  const session = sessionFor(scope, scope.length <= 128 ? scope : undefined);
  const refresh = useCallback(async () => {
    try {
      const [c, n, e] = await Promise.all([api<Context>(`/goals/${goalId}/nodes/${nodeId}/context`), api<NextAction>(`/goals/${goalId}/nodes/${nodeId}/next-action`), api<{ exercises: Exercise[]; feedback: Record<string, Feedback> }>(`/goals/${goalId}/nodes/${nodeId}/exercises`)]);
      setContext(c); setNext(n); setExercises(e.exercises); setFeedback(e.feedback); setError(''); setResultVersion(value => value + 1); onResult();
    } catch (e) { setError(String(e)); }
  }, [goalId, nodeId, onResult]);
  const tasks = useRuns(session, () => { void refresh(); });
  useEffect(() => { void refresh(); }, [refresh]);
  const exercisePending = tasks.pending?.path.endsWith('/exercises');
  useEffect(() => { if (exercisePending) setTab('practice'); }, [exercisePending]);
  async function send(event: FormEvent) {
    event.preventDefault(); if (!text.trim()) return;
    const userText = text; setText('');
    const accepted = await tasks.execute({ path: `/sessions/${session}/runs`, body: { request_id: crypto.randomUUID(), user_text: userText, goal_id: goalId, node_id: nodeId, mode: 'teaching' } });
    if (accepted === false) setText(current => current || userText);
  }
  async function recover() {
    const userText = tasks.pending?.body.user_text;
    if (await tasks.recover() === false && typeof userText === 'string') setText(current => current || userText);
  }
  const recovery = <PendingRequest command={tasks.pending} checked={tasks.pendingChecked} sending={tasks.sending} query={() => { void tasks.refresh(); }} resend={() => { void recover(); }}/>;
  return <><div className="mobile-tabs" role="tablist" aria-label="学习面板">{[['chat', '节点对话'], ['practice', '练习与进度'], ['lesson', '学习包']].map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>)}</div><ErrorBox error={error || tasks.error}/>
    <section className={`panel chat-panel mobile-${tab === 'chat' ? 'show' : 'hide'}`}><p className="eyebrow">当前节点</p><h2>{context?.node.title || '正在读取节点…'}</h2><p className="muted">{context?.node.learning_outcome}</p>
      {!exercisePending && recovery}
      {context && <details><summary>节点说明与前置知识</summary><p>{context.node.explanation}</p><p>{context.prerequisites.map(n => n.title).join('、') || '无前置节点'}</p></details>}
      <DocumentBindings goalId={goalId} nodeId={nodeId}/>
      <div className="conversation" aria-label="节点对话记录">{!tasks.runs.some(r => (r.mode === 'runner' || r.mode === 'teaching')) && <div className="empty"><h3>从一个问题开始</h3><p>让助手解释概念、举例，或帮你检查理解。</p></div>}{tasks.runs.filter(r => (r.mode === 'runner' || r.mode === 'teaching')).map(run => <article className="turn" key={run.run_id}><div className="user-message"><strong>你</strong><p>{run.user_text}</p></div><div className="assistant-message"><strong>学习助手</strong><SafeMarkdown>{run.final_text || run.partial_text || '正在准备回答…'}</SafeMarkdown><RunCitations run={run} goalId={goalId} nodeId={nodeId}/><RunStatus run={run} stop={tasks.stop} retry={() => { void tasks.retry(run.run_id); }} readOnly={!!tasks.pending || run.run_id !== tasks.runs.at(-1)?.run_id}/></div></article>)}</div>
      <form className="composer" onSubmit={send}><label htmlFor="question">向当前节点提问</label><textarea id="question" value={text} onChange={e => setText(e.target.value)} maxLength={16000} required placeholder="用一个具体例子解释这个概念"/><div className="actions"><button disabled={tasks.busy || !text.trim()}>发送问题</button><button type="button" className="quiet" onClick={() => tasks.refresh()}>查询运行状态</button></div></form>
    </section>
    <aside className={`panel practice-panel mobile-${tab === 'practice' ? 'show' : 'hide'}`}><h2>练习与进度</h2><div className="progress-card"><span className="tag">{context ? mastery[context.node.mastery] || context.node.mastery : '读取中'}</span><p><strong>{context?.node.sample_count || 0}</strong> 个有效样本 · 正确率 {Math.round((context?.node.accuracy || 0) * 100)}%</p><p className="muted small">掌握度依据作答证据计算。重复答题不重复计分。</p></div>
      {exercisePending && recovery}
      <button className="secondary" disabled={tasks.busy} onClick={() => tasks.execute({ path: `/goals/${goalId}/nodes/${nodeId}/exercises`, body: { session_id: session, request_id: crypto.randomUUID(), count: 1, purpose: 'practice' } })}>生成练习</button>
      {tasks.runs.at(-1)?.mode === 'exercise' && <RunStatus run={tasks.runs.at(-1)} stop={tasks.stop} retry={tasks.retry} readOnly={!!tasks.pending}/>}
      {!exercises.length && <p className="muted">生成一道练习，检验当前节点的理解。</p>}
      {exercises.map((exercise, index) => <QuizCard key={exercise.id} goalId={goalId} exercise={exercise} feedback={feedback[exercise.id]} title={`练习 ${index + 1}`} onChanged={refresh}/>)}
      {next && <div className="recommendation"><h3>下一步建议</h3><p>{next.reason_text}</p><p className="muted">预计 {next.estimated_minutes} 分钟</p>{next.node_id && <button className="secondary" onClick={() => { onSelect(next.node_id!); setTab('chat'); }}>查看推荐节点</button>}</div>}
    </aside>
    <section className={`panel lesson-panel mobile-${tab === 'lesson' ? 'show' : 'hide'}`}><LessonPanel goalId={goalId} nodeId={nodeId} refreshKey={resultVersion} onChanged={refresh}/></section>
    </>;
}

export function Learning({ goalId }: { goalId: string }) {
  const [graph, setGraph] = useState<Graph>();
  const [proposalRefresh, setProposalRefresh] = useState(0);
  const onResult = useCallback(() => setProposalRefresh(value => value + 1), []);
  const [selected, setSelected] = useState(localStorage.getItem(`learngraph:node:${goalId}`) || '');
  const [error, setError] = useState('');
  useEffect(() => { api<Plan>(`/goals/${goalId}/graph`).then(p => setGraph(p.graph || undefined)).catch(e => setError(String(e))); }, [goalId]);
  const nodeId = graph?.nodes.find(n => n.id === selected)?.id || graph?.nodes[0]?.id;
  function select(id: string) { localStorage.setItem(`learngraph:node:${goalId}`, id); setSelected(id); }
  if (!graph || !nodeId) return <div className="page"><ErrorBox error={error}/><p role="status">正在读取学习路线…</p></div>;
  if (graph.status !== 'published') return <div className="page"><p>请先审核并发布路线。</p><a href={`/goals/${goalId}/plan`}>返回规划</a></div>;
  return <div className="page learning-page"><div className="page-heading"><div><p className="eyebrow">一步一步，留下学习证据</p><h1>沿着路线学习</h1></div><a className="back" href={`/goals/${goalId}/plan`}>查看目标与路线</a></div><div className="learning-grid"><aside className="panel learning-route"><h2>学习路线</h2><GraphCanvas graph={graph} selected={nodeId} onSelect={select}/><div className="route-list">{graph.nodes.map((n, i) => <button className={n.id === nodeId ? 'selected' : 'quiet'} key={n.id} aria-current={n.id === nodeId ? 'step' : undefined} onClick={() => select(n.id)}><span>{i + 1}</span><span>{n.title}<small>{n.estimated_minutes} 分钟</small></span></button>)}</div></aside><NodeLearning key={`${nodeId}:${graph.revision}`} goalId={goalId} nodeId={nodeId} onSelect={select} onResult={onResult}/><ProposalPanel goalId={goalId} graph={graph} refreshKey={proposalRefresh} onAccepted={plan => setGraph(plan.graph || undefined)}/></div></div>;
}
