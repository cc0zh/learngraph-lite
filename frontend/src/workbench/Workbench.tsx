import { useCallback, useEffect, useRef, useState } from 'react';
import { api, HttpError } from '../api';
import { ErrorBox, GraphCanvas, Icon } from '../components';
import { MessageComposer } from '../MessageComposer';
import { AgentPlanning } from '../pages/AgentPlanning';
import { Documents, DocumentDetail, DocumentBindings } from '../documents';
import type { Conversation, Plan, Run } from '../types';
import type { Command } from '../useRuns';
import { WorkbenchConversation } from './Conversation';
import { GraphManagement } from './GraphManagement';
import { navigateWorkbench, workbenchHref, workbenchHistoryIndex } from './navigation';
import './workbench.css';

interface Location { goal?: string; session?: string; creating: boolean; tool?: string; document?: string; sourceGoal?: string; sourceNode?: string; node?: string; query?: string }
interface Creation { kind: 'goal' | 'learning' | 'general'; id: string; title: string; prompt?: string; goal?: string; node?: string; request: string }
const creationKey = 'learngraph:workbench:creation';
const goalDraftKey = 'learngraph:workbench:goal-draft';
function locationState(): Location {
  const params = new URLSearchParams(window.location.search);
  return { goal: params.get('goal') || undefined, session: params.get('session') || undefined, creating: params.get('mode') === 'goal',
    tool: params.get('tool') || undefined, document: params.get('document') || undefined,
    sourceGoal: params.has('source_goal') ? params.get('source_goal')! : undefined, sourceNode: params.has('source_node') ? params.get('source_node')! : undefined,
    node: params.get('node') || undefined, query: window.location.search };
}
function readCreation(): Creation | undefined {
  try { return JSON.parse(localStorage.getItem(creationKey) || 'null') || undefined; } catch { return undefined; }
}
function createdLabel(value: Conversation) { return new Date(value.created_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }); }

export function Workbench() {
  const [route, setRoute] = useState(locationState);
  const [plans, setPlans] = useState<Plan[]>();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState(readCreation);
  const [draft, setDraft] = useState(() => localStorage.getItem(goalDraftKey) || '');
  const [plainText, setPlainText] = useState(() => localStorage.getItem('learngraph:workbench:plain-draft') || '');
  const [browsed, setBrowsed] = useState('');
  const [mobilePanel, setMobilePanel] = useState('main');
  const [railHidden, setRailHidden] = useState(false);
  const [sidebarTarget, setSidebarTarget] = useState<HTMLDivElement | null>(null);
  const [documentsVersion, setDocumentsVersion] = useState(0);
  const documentsChanged = useCallback(() => setDocumentsVersion(value => value + 1), []);
  const query = useRef(0);
  const navigation = useRef(0);
  const creationLock = useRef(false);
  const toolDirty = useRef(false);
  const currentURL = useRef(window.location.href);
  const historyPosition = useRef(workbenchHistoryIndex());
  const restoringHistory = useRef(false);
  const authorizedNavigation = useRef(false);
  const refresh = useCallback(async () => {
    const version = ++query.current;
    try {
      const [goals, sessions] = await Promise.all([api<Plan[]>('/goals'), api<Conversation[]>('/conversations')]);
      if (version !== query.current) return;
      setPlans(previous => goals.map(goal => {
        const existing = previous?.find(item => item.goal_id === goal.goal_id);
        return existing && existing.version > goal.version ? existing : goal;
      }));
      setConversations(sessions); setLoading(false); setError('');
    } catch (e) { if (version === query.current) { setError(`读取学习空间失败：${String(e)}`); setLoading(false); } }
  }, []);
  useEffect(() => { void refresh(); return () => { ++query.current; }; }, [refresh]);
  useEffect(() => {
    const question = '图谱管理中有未保存输入，离开将放弃这些本地修改。是否继续？';
    const restore = () => {
      if (restoringHistory.current) { restoringHistory.current = false; return; }
      if (toolDirty.current && !authorizedNavigation.current && !window.confirm(question)) {
        const targetIndex = window.history.state?.learngraphIndex;
        const delta = typeof targetIndex === 'number' ? historyPosition.current - targetIndex : 0;
        if (delta) { restoringHistory.current = true; window.history.go(delta); }
        else window.history.replaceState({ learngraphIndex: historyPosition.current }, '', currentURL.current);
        return;
      }
      authorizedNavigation.current = false; currentURL.current = window.location.href; historyPosition.current = workbenchHistoryIndex();
      ++navigation.current; setRoute(locationState()); setMobilePanel('main');
    };
    const guard = (event: Event) => {
      if (toolDirty.current && !window.confirm(question)) event.preventDefault();
      else authorizedNavigation.current = true;
    };
    const unload = (event: BeforeUnloadEvent) => { if (toolDirty.current) event.preventDefault(); };
    window.addEventListener('popstate', restore); window.addEventListener('learngraph:before-navigate', guard); window.addEventListener('beforeunload', unload);
    return () => { window.removeEventListener('popstate', restore); window.removeEventListener('learngraph:before-navigate', guard); window.removeEventListener('beforeunload', unload); };
  }, []);
  function navigate(next: Location) {
    const params = new URLSearchParams();
    if (next.goal) params.set('goal', next.goal);
    if (next.session) params.set('session', next.session);
    if (next.creating) params.set('mode', 'goal');
    if (navigateWorkbench(`/${params.size ? `?${params}` : ''}`)) { setMobilePanel('main'); setNotice(''); }
  }
  function openTool(tool?: string, node?: string) {
    navigateWorkbench(workbenchHref({ tool, document: undefined, chunk: undefined, mode: undefined,
      source_goal: tool === 'documents' ? goalId : undefined, source_node: tool === 'documents' ? node : undefined }));
  }
  const active = conversations.find(item => item.session_id === route.session);
  // The saved conversation, not a second URL parameter or a browsed node, owns scope.
  const goalId = active ? active.goal_id || undefined : route.goal;
  const scopeMismatch = !!active && !!route.goal && route.goal !== active.goal_id;
  const creationBlocked = !!pending && ((pending.kind === 'goal' && goalId === pending.id) || active?.session_id === pending.id);
  const plan = plans?.find(item => item.goal_id === goalId);
  const planning = !route.creating && !!goalId && (active?.kind === 'planning' || route.session === `planning:${goalId}`);
  const currentNode = active?.node_id ? plan?.graph?.nodes.find(item => item.id === active.node_id) : undefined;
  const viewedNode = plan?.graph?.nodes.find(item => item.id === browsed);
  useEffect(() => { setBrowsed(route.node || active?.node_id || ''); }, [goalId, active?.session_id, active?.node_id, route.node]);
  const onPlanChange = useCallback((value: Plan) => {
    setPlans(previous => {
      const current = previous?.find(item => item.goal_id === value.goal_id);
      if (current && current.version > value.version) return previous;
      return current ? previous!.map(item => item.goal_id === value.goal_id ? value : item) : [...(previous || []), value];
    });
  }, []);
  const previousPublished = useRef<string | undefined>(undefined);
  useEffect(() => {
    const published = plan?.graph?.status === 'published' ? plan.goal_id : undefined;
    if (published && previousPublished.current !== published) void refresh();
    previousPublished.current = published;
  }, [plan?.graph?.status, plan?.goal_id, refresh]);

  async function initialRun(session: string, command: Command) {
    const key = `learngraph:command:${session}`;
    localStorage.setItem(`${key}:pending`, JSON.stringify(command));
    localStorage.removeItem(creationKey); setPending(undefined);
    try {
      const run = await api<Run>(command.path, command.body);
      localStorage.setItem(`${key}:${run.run_id}`, JSON.stringify(command));
      localStorage.removeItem(`${key}:pending`);
      return { accepted: true, notice: '' };
    } catch (e) {
      if (e instanceof HttpError && e.status >= 400 && e.status < 500) {
        if (e.status !== 429) localStorage.removeItem(`${key}:pending`);
        return { accepted: false, notice: `首次请求被拒绝：${e.message}。会话与完整输入已保存，请检查后显式恢复或重新提问。` };
      }
      // Uncertain writes retain their original request identity for explicit recovery.
      return { accepted: false, notice: '' };
    }
  }
  async function create(command: Creation) {
    if (creationLock.current) return;
    creationLock.current = true; setCreating(true); setError(''); setNotice('');
    const origin = navigation.current;
    setPending(command); localStorage.setItem(creationKey, JSON.stringify(command));
    try {
      let session: string;
      let outcome: { accepted: boolean; notice: string };
      if (command.kind === 'goal') {
        const value = await api<Plan>('/workbench/goals', { goal_id: command.id, title: command.title });
        onPlanChange(value); session = `planning:${command.id}`;
        outcome = await initialRun(session, { path: `/goals/${command.id}/planning-runs`, body: {
          request_id: command.request, expected_version: 0, user_text: command.title,
        } });
        if (outcome.accepted && localStorage.getItem(goalDraftKey)?.trim() === command.title) {
          localStorage.removeItem(goalDraftKey); setDraft(value => value.trim() === command.title ? '' : value);
        }
      } else {
        const value = await api<Conversation>('/conversations', {
          session_id: command.id, title: command.title.slice(0, 100), goal_id: command.goal || null, node_id: command.node || null,
        });
        setConversations(items => [...items.filter(item => item.session_id !== value.session_id), value]); session = value.session_id;
        const sessionDraft = `learngraph:workbench:text:${session}`;
        const input = command.prompt || command.title;
        if (!localStorage.getItem(sessionDraft)) localStorage.setItem(sessionDraft, input);
        outcome = await initialRun(session, { path: `/sessions/${session}/runs`, body: {
          request_id: command.request, user_text: command.prompt || command.title,
          ...(command.kind === 'learning' ? { goal_id: command.goal, node_id: command.node, mode: 'teaching' } : { mode: 'runner' }),
        } });
        if (outcome.accepted && localStorage.getItem(sessionDraft) === input) localStorage.removeItem(sessionDraft);
        if (outcome.accepted && command.kind === 'general' && localStorage.getItem('learngraph:workbench:plain-draft')?.trim() === command.title) {
          localStorage.removeItem('learngraph:workbench:plain-draft'); setPlainText(value => value.trim() === command.title ? '' : value);
        }
      }
      await refresh();
      if (origin === navigation.current) { navigate({ goal: command.kind === 'goal' ? command.id : command.goal, session, creating: false }); setNotice(outcome.notice); }
    } catch (e) {
      if (e instanceof HttpError && e.status >= 400 && e.status < 500) { localStorage.removeItem(creationKey); setPending(undefined); }
      setError(`创建尚未完成：${String(e)}。输入已保留，不会自动重试。`);
    } finally { creationLock.current = false; setCreating(false); }
  }
  function startLearning(nodeId: string) {
    const node = plan?.graph?.nodes.find(item => item.id === nodeId);
    if (!node || !goalId || pending || creating) return;
    void create({ kind: 'learning', id: crypto.randomUUID(), goal: goalId, node: node.id,
      title: `${node.title} · 第 ${conversations.filter(value => value.kind === 'learning' && value.goal_id === goalId && value.node_id === node.id).length + 1} 次学习`, prompt: `请围绕「${node.title}」开始本次学习，先介绍核心概念并用一个具体例子讲解。`, request: crypto.randomUUID() });
  }
  function openConversation(value: Conversation) { navigate({ goal: value.goal_id || undefined, session: value.session_id, creating: false }); }
  function goalMode() { navigate({ ...route, creating: true }); }
  function emptyComposer() {
    const isGoal = route.creating;
    const value = isGoal ? draft : plainText;
    return <section className="wb-start" aria-label={isGoal ? '创建目标' : '工作台起点'}>
      <div className="wb-empty">
        <h1>{isGoal ? '从你的学习想法开始' : '想探索什么知识？'}</h1>
        <p>{isGoal ? '描述想了解的主题。Agent 会按需澄清并提出图谱草稿，确认仍由你决定。' : '选择左侧图谱继续学习，或切换到创建目标模式建立一张新图谱。'}</p>
      </div>
      <MessageComposer id="workbench-initial-input" label={isGoal ? '描述学习目标' : '发送消息'} value={value} onSubmit={() => { if (!value.trim() || pending) return;
        void create({ kind: isGoal ? 'goal' : 'general', id: crypto.randomUUID(), title: value.trim(), request: crypto.randomUUID() });
      }} maxLength={isGoal ? 2000 : 16000} onChange={next => {
        if (isGoal) { setDraft(next); localStorage.setItem(goalDraftKey, next); }
        else { setPlainText(next); localStorage.setItem('learngraph:workbench:plain-draft', next); }
      }} placeholder={isGoal ? '例如：想系统了解 RAG，我会 Python…' : '输入问题，或点击下方创建目标…'}
        disabled={creating || !!pending || !value.trim()} submitLabel={creating ? '正在创建…' : isGoal ? '发送并创建目标' : '发送消息'}
        note="切换模式不创建目标；发送后才调用模型。刷新不会重复生成。">
        <button type="button" className={isGoal ? 'selected composer-mode' : 'quiet composer-mode'} aria-pressed={isGoal} onClick={() => isGoal ? navigate({ ...route, creating: false }) : goalMode()}><Icon name="plus"/>{isGoal ? '退出创建模式' : '创建目标'}</button>
      </MessageComposer>
    </section>;
  }
  const documentGoal = route.sourceGoal ?? goalId;
  const documentNode = route.sourceNode ?? (route.sourceGoal !== undefined ? undefined : active?.node_id || undefined);
  return <div className={`workbench ${railHidden ? 'wb-rail-hidden' : ''} ${route.tool ? 'wb-tool-open' : ''}`}>
    <header className="wb-context" aria-label="当前对话范围"><div>
      <h1 title={route.creating ? '新目标' : plan?.goal.title || active?.title || '我的学习空间'}>{route.creating ? '新目标' : plan?.goal.title || active?.title || '我的学习空间'}</h1>
      <p className="wb-scope"><span>{route.creating ? '创建目标模式' : planning ? plan?.graph?.status === 'published' ? '目标创建记录' : '目标创建模式' : active?.kind === 'learning' ? '节点学习' : '学习工作台'}</span><span>{route.creating ? '当前输入用于创建新目标，不会修改已有图谱。' : active?.kind === 'learning' ? `本条对话 · 节点：${currentNode?.title || active.node_id}` : planning ? '目标澄清、图谱生成与审核' : active ? '普通对话 · 未绑定图谱' : plan ? '浏览图谱 · 尚未进入学习对话' : '尚未绑定图谱或节点'}</span></p>
      {!route.creating && active?.kind === 'learning' && <p className="small">会话：{active.title} · {createdLabel(active)}</p>}</div>
      <div className="actions">{!route.creating && (active || plan) && <button className="quiet" onClick={goalMode}>创建目标</button>}
        {plan && !route.creating && <button className="quiet" onClick={() => openTool('graph')}>图谱管理</button>}
        {goalId && !route.creating && <button className="quiet" onClick={() => openTool('documents', active?.node_id || undefined)}>{active?.node_id ? '当前节点资料' : '目标资料'}</button>}
        {!route.tool && <button className="quiet wb-rail-toggle" aria-expanded={!railHidden} onClick={() => setRailHidden(value => !value)}>{railHidden ? '展开图谱' : '收起图谱'}</button>}</div>
    </header>
    <nav className="wb-mobile-nav" aria-label="工作台区域">{[['spaces', '学习空间'], ['main', '对话与内容'], ['graph', '图谱与节点']].map(([id, title]) => <button key={id} aria-pressed={mobilePanel === id} onClick={() => {
      if (id === 'graph' && route.tool && !navigateWorkbench(workbenchHref({ tool: undefined, document: undefined, chunk: undefined }))) return;
      setMobilePanel(id); if (id === 'graph') setRailHidden(false);
    }}>{title}</button>)}</nav>
    <aside className={`wb-spaces wb-mobile-${mobilePanel === 'spaces' ? 'show' : 'hide'}`} aria-label="学习空间">
      <div className="section-title"><h2>学习空间</h2><button className="quiet icon-button" aria-label="刷新" title="刷新学习空间" onClick={() => { void refresh(); }}><Icon name="refresh"/></button></div>
      <button className="wb-new-chat quiet" onClick={() => navigate({ creating: false })}><Icon name="plus"/>新对话</button>
      {loading && <p role="status">正在读取图谱与会话…</p>}
      {!loading && !plans?.length && <p className="muted small">还没有图谱，点击创建目标开始。</p>}
      {(['published', 'draft'] as const).map(status => {
        const group = plans?.filter(item => (item.graph?.status === 'published') === (status === 'published')) || [];
        return !!group.length && <section className="wb-space-group" key={status}><h3>{status === 'published' ? '我的图谱' : '待完成目标'}</h3>
          {group.map(item => <details key={item.goal_id} open={goalId === item.goal_id || undefined}>
            <summary title={item.goal.title} onKeyDown={event => { if (event.key === ' ') event.stopPropagation(); }}><Icon name="chevron"/><Icon name="folder"/><span>{item.goal.title}</span></summary>
            <div className="wb-goal-items">
            <button className="quiet wb-space-open" aria-current={goalId === item.goal_id && !route.session ? 'page' : undefined} onClick={() => navigate({ goal: item.goal_id, creating: false })}>{item.graph ? '查看图谱' : '查看目标'}</button>
            {conversations.filter(value => value.goal_id === item.goal_id).map(value => <button key={value.session_id} className={`wb-session ${route.session === value.session_id && !route.creating ? 'selected' : 'quiet'}`} aria-current={route.session === value.session_id && !route.creating ? 'page' : undefined}
              onClick={() => openConversation(value)}><Icon name="chat"/><span className="wb-session-content"><span className="wb-session-title" title={value.kind === 'planning' ? '目标创建对话' : value.title}>{value.kind === 'planning' ? '目标创建对话' : value.title}</span>
              <small>{value.kind === 'learning' ? `节点：${item.graph?.nodes.find(node => node.id === value.node_id)?.title || value.node_id}` : value.kind === 'planning' ? item.graph?.status === 'published' ? '已完成 · 只读' : '继续创建' : '普通对话'}</small></span>{value.kind === 'learning' && <time dateTime={value.created_at} title={createdLabel(value)}>{new Date(value.created_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })}</time>}</button>)}
            </div>
          </details>)}
        </section>;
      })}
      {!!conversations.filter(value => value.kind === 'general').length && <section className="wb-space-group"><h3>其他对话</h3>{conversations.filter(value => value.kind === 'general').map(value => <button key={value.session_id} className={route.session === value.session_id ? 'wb-session selected' : 'wb-session quiet'} aria-current={route.session === value.session_id ? 'page' : undefined} onClick={() => openConversation(value)}><Icon name="chat"/><span className="wb-session-content"><span className="wb-session-title" title={value.title}>{value.title}</span></span></button>)}</section>}
    </aside>
    <section className={`wb-main wb-mobile-${mobilePanel === 'main' ? 'show' : 'hide'}`} aria-label="对话与学习内容">
      <ErrorBox error={error || (scopeMismatch ? '链接中的图谱与会话范围不一致。请从左侧重新打开这条对话。' : '')}/>{notice && <p className="hint" role="status">{notice}</p>}
      {route.tool && <div className="wb-tool-heading"><p className="scope-label">工作台 · {route.tool === 'graph' ? '图谱管理' : '学习资料'}</p><button className="quiet" onClick={() => openTool()}>返回对话与学习</button></div>}
      {pending && <section className="hint" aria-label="创建恢复"><strong>有一项创建尚未确认</strong><p>{pending.title}</p><p>刷新只读取状态。继续会复用原创建标识和请求，不重复创建。</p>
        <button disabled={creating} onClick={() => { void create(pending); }}>继续本次创建</button><button className="quiet" onClick={() => { void refresh(); }}>查询学习空间</button></section>}
      {scopeMismatch ? null : route.tool === 'document' && route.document ? <DocumentDetail key={`${route.document}:${route.query}`} documentId={route.document} query={route.query}/>
        : route.tool === 'documents' ? <section aria-label="工作台资料管理">{documentGoal && <div className="wb-bindings"><DocumentBindings key={`goal:${documentGoal}`} goalId={documentGoal} refreshToken={documentsVersion} onChanged={documentsChanged}/>{documentNode && <DocumentBindings key={`node:${documentGoal}:${documentNode}`} goalId={documentGoal} nodeId={documentNode} refreshToken={documentsVersion} onChanged={documentsChanged}/>}</div>}<Documents onChanged={documentsChanged}/></section>
          : route.tool === 'graph' ? goalId ? <GraphManagement key={goalId} goalId={goalId} onPlanChange={onPlanChange} onDirtyChange={value => { toolDirty.current = value; }}/>
            : <p className="hint">请先选择一个目标，再管理图谱。</p>
          : route.tool ? <p className="hint">未知工具，请返回对话与学习。</p>
        : route.creating ? emptyComposer() : creationBlocked ? <p className="hint">请先通过上方“继续本次创建”恢复原请求；恢复前不会从这里发起替代的首轮。</p> : planning && goalId ? <AgentPlanning key={goalId} goalId={goalId} sidebarTarget={sidebarTarget} onPlanChange={onPlanChange}/>
        : active ? <WorkbenchConversation key={active.session_id} conversation={active} onChanged={refresh} onBrowse={nodeId => { setBrowsed(nodeId); setRailHidden(false); setMobilePanel('graph'); }}/>
          : route.session && !loading ? <div className="wb-empty"><h2>未找到这条会话</h2><p>请刷新学习空间，或从左侧选择已保存对话；不会自动创建替代会话。</p></div>
            : plan ? <div className="wb-empty"><h2>{plan.graph?.status === 'published' ? '选择主题，开始学习' : '继续完善目标与图谱'}</h2><p>查看右侧节点不会改变任何会话。准备好后，点击开始学习，或恢复已有对话。</p>
              <button className="quiet" onClick={() => navigate({ goal: plan.goal_id, session: `planning:${plan.goal_id}`, creating: false })}>查看目标创建对话</button></div> : goalId && !loading ? <div className="wb-empty"><h2>未找到这张图谱</h2><p>请从左侧选择已保存的学习空间，不会自动创建新目标。</p></div> : !loading && emptyComposer()}
    </section>
    <aside className={`wb-graph-rail wb-mobile-${mobilePanel === 'graph' ? 'show' : 'hide'}`} aria-label="图谱与节点">
      <h2>{route.creating ? '新目标预览' : '当前图谱'}</h2>
      {!route.creating && plan?.graph ? <><p className="small muted">{plan.graph.status === 'published' ? '已发布' : '草稿 · 待审核'} · {plan.graph.nodes.length} 个节点</p>
        <GraphCanvas graph={plan.graph} selected={viewedNode?.id} onSelect={setBrowsed} compact/>
        <div className="wb-node-list" role="region" aria-label="浏览图谱节点">{plan.graph.nodes.map(node => <button key={node.id} className={browsed === node.id ? 'selected' : 'quiet'} aria-pressed={browsed === node.id} onClick={() => setBrowsed(node.id)}>{node.title}{currentNode?.id === node.id && <small>对话焦点</small>}</button>)}</div>
        {viewedNode ? <section className="wb-node-detail" aria-label="所查看节点"><h3>{viewedNode.title}</h3><p className="scope-label">正在浏览 · 不改变对话范围</p><p>{viewedNode.explanation}</p>
          {viewedNode.learning_outcome && <p className="small muted">学习参考：{viewedNode.learning_outcome}</p>}
          {plan.graph.status === 'published' ? <><button disabled={creating || !!pending} onClick={() => startLearning(viewedNode.id)}>开始学习此节点</button><p className="small muted">新建独立对话，并调用模型开始讲解。</p>
            <div className="wb-node-history"><h4>继续已有对话</h4>{conversations.filter(value => value.kind === 'learning' && value.goal_id === goalId && value.node_id === viewedNode.id).map(value => <button key={value.session_id} className="quiet" onClick={() => openConversation(value)}>{value.title}</button>)}
              {!conversations.some(value => value.kind === 'learning' && value.goal_id === goalId && value.node_id === viewedNode.id) && <p className="muted small">这个节点还没有学习对话。</p>}</div></> : <p className="hint">图谱审核发布后，才可从节点开始学习。</p>}
        </section> : <p className="muted small">选择节点查看详情，不会自动创建对话。</p>}
      </> : <p className="muted">{route.creating ? '发送学习想法后，目标与图谱会在这里逐步呈现。' : plan ? '尚未生成图谱，请在目标创建对话中继续。' : '选择左侧图谱，或创建一个学习目标。'}</p>}
      <div ref={setSidebarTarget} hidden={!planning || route.creating}/>
    </aside>
  </div>;
}
