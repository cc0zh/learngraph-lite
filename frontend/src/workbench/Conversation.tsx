import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { ErrorBox, Icon, PendingRequest, RunCitations, RunStatus, SafeMarkdown } from '../components';
import { MessageComposer } from '../MessageComposer';
import { LessonPanel } from '../lessons/LessonPanel';
import { QuizCard } from '../lessons/QuizCard';
import type { Context, Conversation, Exercise, Feedback, NextAction } from '../types';
import { useRuns } from '../useRuns';

export function WorkbenchConversation({ conversation, onChanged, onBrowse }: { conversation: Conversation; onChanged: () => void; onBrowse: (node: string) => void }) {
  const { session_id: session, goal_id: goal, node_id: node } = conversation;
  const draftKey = `learngraph:workbench:text:${session}`;
  const viewKey = `learngraph:workbench:view:${session}`;
  const [text, setText] = useState(() => localStorage.getItem(draftKey) || '');
  const [tab, setTab] = useState(() => localStorage.getItem(viewKey) || 'chat');
  const [context, setContext] = useState<Context>();
  const [next, setNext] = useState<NextAction>();
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [feedback, setFeedback] = useState<Record<string, Feedback>>({});
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const epoch = useRef(0);
  const history = useRef<HTMLDivElement>(null);
  const refresh = useCallback(async () => {
    onChanged();
    if (!goal || !node) return;
    const current = ++epoch.current;
    try {
      const [value, questions, action] = await Promise.all([
        api<Context>(`/goals/${goal}/nodes/${node}/context`),
        api<{ exercises: Exercise[]; feedback: Record<string, Feedback> }>(`/goals/${goal}/nodes/${node}/exercises`),
        api<NextAction>(`/goals/${goal}/nodes/${node}/next-action`),
      ]);
      if (current !== epoch.current) return;
      setContext(value); setExercises(questions.exercises); setFeedback(questions.feedback); setNext(action); setError('');
      setRevision(value => value + 1);
    } catch (e) { if (current === epoch.current) setError(`当前节点暂不可用于新学习：${String(e)}。已保存对话仍可查看。`); }
  }, [goal, node, onChanged]);
  const tasks = useRuns(session, () => { void refresh(); });
  useEffect(() => { void refresh(); return () => { ++epoch.current; }; }, [refresh]);
  const latest = tasks.runs.at(-1);
  const dialogue = tasks.runs.filter(run => run.mode === 'teaching' || run.mode === 'runner');
  const chatMode = conversation.legacy ? dialogue.at(-1)?.mode || 'runner' : node ? 'teaching' : 'runner';
  const historyUnavailable = !!conversation.legacy && !dialogue.length;
  useEffect(() => {
    const container = history.current;
    const turn = container?.querySelector<HTMLElement>('.turn:last-child');
    if (container && turn) container.scrollTop += turn.getBoundingClientRect().top - container.getBoundingClientRect().top;
  }, [latest?.run_id, latest?.status, tab]);
  function edit(value: string) { setText(value); localStorage.setItem(draftKey, value); }
  function show(value: string) { setTab(value); localStorage.setItem(viewKey, value); }
  async function send() {
    const submitted = text.trim();
    if (!submitted || tasks.busy || historyUnavailable || (node && !context)) return;
    const accepted = await tasks.execute({ path: `/sessions/${session}/runs`, body: {
      request_id: crypto.randomUUID(), user_text: submitted,
      ...(goal && node ? { goal_id: goal, node_id: node } : {}), mode: chatMode,
    } });
    if (accepted) setText(value => { if (value.trim() !== submitted) return value; localStorage.removeItem(draftKey); return ''; });
  }
  async function recover() {
    const submitted = tasks.pending?.body.user_text;
    if (await tasks.recover() && typeof submitted === 'string') {
      setText(value => { if (value.trim() !== submitted.trim()) return value; localStorage.removeItem(draftKey); return ''; });
    }
  }
  return <section className="wb-conversation" aria-label="学习对话">
    {node && <div className="wb-content-tabs" role="tablist" aria-label="主区内容" onKeyDown={event => {
      if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 'chat' : event.key === 'End' ? 'content' : tab === 'chat' ? 'content' : 'chat';
      show(next); event.currentTarget.querySelector<HTMLButtonElement>(`[data-view="${next}"]`)?.focus();
    }}>
      <button id={`chat-tab-${session}`} data-view="chat" role="tab" aria-controls={`chat-panel-${session}`} tabIndex={tab === 'chat' ? 0 : -1} aria-selected={tab === 'chat'} onClick={() => show('chat')}><Icon name="chat"/>对话</button>
      <button id={`content-tab-${session}`} data-view="content" role="tab" aria-controls={`content-panel-${session}`} tabIndex={tab === 'content' ? 0 : -1} aria-selected={tab === 'content'} onClick={() => show('content')}><Icon name="book"/>学习内容</button>
    </div>}
    <ErrorBox error={error || tasks.error}/>
    <PendingRequest command={tasks.pending} checked={tasks.pendingChecked} sending={tasks.sending}
      query={() => { void tasks.refresh(); }} resend={() => { void recover(); }}/>
    <div className="wb-dialogue" id={`chat-panel-${session}`} role={node ? 'tabpanel' : undefined} tabIndex={node ? 0 : undefined} aria-labelledby={node ? `chat-tab-${session}` : undefined} hidden={tab !== 'chat'}>
      <div className="wb-turns" ref={history} aria-label="当前会话记录" aria-live="polite">
        {!dialogue.length && <div className="wb-empty"><h2>{node ? '从这个节点开始交流' : '从一个问题开始'}</h2>
          <p>{node ? '这里保留本次对话的历史；已有教材、练习和学习记录仍可在学习内容中查看。' : '普通交流不绑定图谱。需要建立知识图谱时，请使用创建目标入口。'}</p></div>}
        {dialogue.map(run => <article className="turn" key={run.run_id}>
          <div className="user-message"><strong>你</strong><SafeMarkdown>{run.user_text}</SafeMarkdown></div>
          <div className="assistant-message"><strong>学习助手</strong><SafeMarkdown>{run.final_text || run.partial_text || (run.error ? '这次请求未完成，可查询状态或显式重试。' : '正在准备回答…')}</SafeMarkdown>
            {goal && node && <RunCitations run={run} goalId={goal} nodeId={node}/>}</div>
        </article>)}
      </div>
    </div>
    {goal && node && <div className="wb-learning-content lesson-panel" id={`content-panel-${session}`} role="tabpanel" tabIndex={0} aria-labelledby={`content-tab-${session}`} hidden={tab !== 'content'}>
      <p className="wb-content-note">这些内容属于当前节点，可在不同会话中继续使用；其他会话的聊天历史不会自动带入。</p>
      <LessonPanel goalId={goal} nodeId={node} conversationId={session} refreshKey={revision} onChanged={refresh}/>
      <section className="wb-exercises" aria-label="节点已有练习"><h2>节点练习</h2>
        {context && <div className="progress-card"><span className="tag">{{ unknown: '未开始', learning: '学习中', needs_review: '需要复习', proficient: '已达练习熟练标准' }[context.node.mastery] || context.node.mastery}</span>
          <p><strong>{context.node.sample_count}</strong> 个有效样本 · 正确率 {Math.round(context.node.accuracy * 100)}%</p><p className="small muted">掌握度依据作答证据计算，重复答题不重复计分。</p></div>}
        <button className="secondary" disabled={tasks.busy || !context} onClick={() => { void tasks.execute({
          path: `/goals/${goal}/nodes/${node}/exercises`, body: { session_id: session, request_id: crypto.randomUUID(), count: 1, purpose: 'practice' },
        }); }}>生成练习</button>
        {!exercises.length && <p className="muted">尚无练习。可在对话中请助手出题，或在这里生成。</p>}
        {exercises.map((exercise, i) => <QuizCard key={exercise.id} goalId={goal} exercise={exercise} feedback={feedback[exercise.id]} title={`练习 ${i + 1}`} onChanged={refresh}/>)}
        {next && <section className="recommendation" aria-label="下一步建议"><h3>下一步建议</h3><p>{next.reason_text}</p><p className="small muted">预计 {next.estimated_minutes} 分钟；依据前置关系与正式作答表现，不是能力认证。</p>
          {next.node_id && <button className="secondary" onClick={() => onBrowse(next.node_id!)}>查看推荐节点</button>}</section>}
      </section>
    </div>}
    <RunStatus run={latest} stop={tasks.stop} retry={tasks.retry} readOnly={!!tasks.pending}/>
    <MessageComposer id={`question-${session}`} label={node ? '向当前节点提问' : '发送消息'} value={text} onChange={edit}
      onSubmit={() => { show('chat'); void send(); }} submitLabel="发送问题" disabled={tasks.busy || historyUnavailable || !text.trim() || (!!node && !context)} maxLength={16000}
      placeholder={node ? '说说哪里还没理解，或继续追问…' : '输入问题，或点击创建目标建立图谱…'}
      stop={tasks.active ? { label: '停止回答', onClick: () => { void tasks.stop(); } } : undefined}
      note={tab === 'content' ? '解释按钮会关联具体章节或步骤；自由提问仍发送到本条对话。' : undefined}>
      <span>{node ? '当前节点对话' : '普通对话'}</span>
      {!tasks.pending && <button type="button" className="quiet wb-query-run icon-button" aria-label="查询运行状态" title="查询运行状态" disabled={tasks.sending} onClick={() => { void tasks.refresh(); void refresh(); }}><Icon name="refresh"/></button>}
    </MessageComposer>
  </section>;
}
