import { useCallback, useEffect, useRef, useState } from 'react';
import { api, sessionFor } from '../api';
import { ErrorBox, PendingRequest, RunStatus, SafeMarkdown } from '../components';
import type { Graph, GraphNode, Plan } from '../types';
import { useRuns } from '../useRuns';
import './proposals.css';

type Operation = { kind: 'update_node'; node_id: string; title?: string; explanation?: string; learning_outcome?: string; estimated_minutes?: number; priority?: number }
  | { kind: 'add_node'; node: GraphNode }
  | { kind: 'add_dependency' | 'remove_dependency'; edge: { source: string; target: string } };
interface Proposal { id: string; goal_id: string; base_revision: number; rationale: string; operations: Operation[]; status: string }
const status: Record<string, string> = { pending: '待审核', accepted: '已接受', rejected: '已拒绝', conflicted: '版本冲突' };
const fields: Record<string, string> = { title: '标题', explanation: '说明', learning_outcome: '学习成果', estimated_minutes: '预计分钟', priority: '优先级' };

function Changes({ proposal, graph }: { proposal: Proposal; graph: Graph }) {
  const nodeTitle = (id: string) => graph.nodes.find(node => node.id === id)?.title || id;
  return <ol className="proposal-changes">{proposal.operations.map((operation, index) => <li key={index}>
    {operation.kind === 'update_node' ? <><strong>修改节点 · {nodeTitle(operation.node_id)}</strong>
      {Object.entries(fields).filter(([key]) => key in operation).map(([key, label]) => {
        const previous = graph.nodes.find(node => node.id === operation.node_id)?.[key as keyof GraphNode];
        const next = operation[key as keyof typeof operation];
        return <div className="proposal-diff" key={key}><span>{label}</span>{proposal.status === 'pending' && <del>当前值（非历史基线）：{typeof previous === 'string' || typeof previous === 'number' ? previous : '未设置'}</del>}<ins>建议值：{String(next)}</ins></div>;
      })}</> : operation.kind === 'add_node' ? <><strong>新增节点 · {operation.node.title}</strong><p>{operation.node.explanation}</p><p>成果：{operation.node.learning_outcome} · {operation.node.estimated_minutes} 分钟</p></>
      : <p>{operation.kind === 'add_dependency' ? '添加' : '移除'}前置关系：{nodeTitle(operation.edge.source)} → {nodeTitle(operation.edge.target)}</p>}
  </li>)}</ol>;
}

export function ProposalPanel({ goalId, graph, refreshKey = 0, onAccepted }: {
  goalId: string; graph: Graph; refreshKey?: number; onAccepted: (plan: Plan) => void;
}) {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [purpose, setPurpose] = useState('补充当前路线的验证步骤');
  const [loading, setLoading] = useState(true);
  const [deciding, setDeciding] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const query = useRef(0);
  const decisionLock = useRef(false);
  const graphRef = useRef(graph);
  const accepted = useRef(onAccepted);
  graphRef.current = graph; accepted.current = onAccepted;
  const session = sessionFor(`proposal:${goalId}`);
  const refresh = useCallback(async () => {
    const version = ++query.current;
    try {
      const [value, planning] = await Promise.all([api<{ proposals: Proposal[] }>(`/goals/${goalId}/graph-proposals`), api<Plan>(`/goals/${goalId}`)]);
      if (version === query.current) {
        setProposals(value.proposals); setError(''); setLoading(false);
        if (planning.graph && planning.graph.revision !== graphRef.current.revision) accepted.current(planning);
      }
    } catch (e) { if (version === query.current) { setError(String(e)); setLoading(false); } }
  }, [goalId]);
  const tasks = useRuns(session, () => { void refresh(); });
  useEffect(() => { void refresh(); }, [refresh, refreshKey, graph.revision]);
  async function decide(proposal: Proposal, decision: 'accept' | 'reject') {
    if (decisionLock.current || proposal.status !== 'pending') return;
    if (decision === 'accept' && !window.confirm('接受将发布新路线版本。内容改变会使旧题和旧学习包只读，并按新内容版本重新计算掌握度；历史作答保留。是否接受？')) return;
    decisionLock.current = true; setDeciding(proposal.id); setError(''); setNotice('');
    try {
      const result = await api<{ proposal: Proposal; planning: Plan; learning_reset: boolean }>(`/goals/${goalId}/graph-proposals/${proposal.id}/decision`, { decision, expected_revision: graph.revision });
      if (decision === 'accept') onAccepted(result.planning);
      setNotice(decision === 'reject' ? '已拒绝，路线与成绩未改变。' : result.learning_reset ? '已接受新内容版本。历史作答保留；当前掌握度按新内容重算，旧题和旧学习包只读。' : '已接受计划调整，当前内容版本与作答证据保留。');
      await refresh();
    } catch (e) { await refresh(); setError(`审核响应未确认或被拒绝：${String(e)}。已重新读取服务器结果，请以提案状态和当前路线为准；版本冲突需重新生成提案。`); }
    finally { decisionLock.current = false; setDeciding(''); }
  }
  return <section id="graph-proposals" className="panel proposal-panel" aria-label="路线调整提案"><div className="section-title"><h2>路线调整提案</h2><button className="quiet" onClick={() => { void refresh(); void tasks.refresh(); }}>刷新提案与状态</button></div>
    <p className="muted small">Agent 和教学工具只能提出建议，不直接改路线或成绩。接受/拒绝必须由你明确操作；接受按当前修订校验。</p>
    <label>调整目的<textarea maxLength={2000} value={purpose} onChange={event => setPurpose(event.target.value)}/></label>
    <button className="secondary" disabled={tasks.busy || !!deciding || !purpose.trim()} onClick={() => { void tasks.execute({ path: `/goals/${goalId}/graph-proposals/generate`, body: { session_id: session, request_id: crypto.randomUUID(), purpose } }); }}>让 Agent 生成调整提案</button>
    <ErrorBox error={error || tasks.error}/>{notice && <p className="hint" role="status">{notice}</p>}
    <PendingRequest command={tasks.pending} checked={tasks.pendingChecked} sending={tasks.sending} query={() => { void tasks.refresh(); void refresh(); }} resend={() => { void tasks.recover(); }}/>
    <RunStatus run={tasks.runs.at(-1)} stop={tasks.stop} retry={tasks.retry} readOnly={!!tasks.pending}/>
    {!!tasks.runs.at(-1)?.final_text && <SafeMarkdown>{tasks.runs.at(-1)!.final_text!}</SafeMarkdown>}
    {loading ? <p role="status">正在读取提案…</p> : !proposals.length ? <div className="empty">还没有提案。可在这里生成，或在教学对话中请 Agent 提出路线调整。</div> : <div className="proposal-list">{proposals.map(proposal => <article className="proposal-card" aria-label={`提案 ${proposal.id}`} key={proposal.id}>
      <div className="section-title"><h3>{status[proposal.status] || proposal.status}</h3><span className="tag">基于修订 {proposal.base_revision} · 当前 {graph.revision}</span></div><p>{proposal.rationale}</p><Changes proposal={proposal} graph={graph}/>
      {proposal.status === 'pending' && <>{proposal.base_revision !== graph.revision && <p className="hint">基础版本已过期，接受请求会被服务器标记为冲突，不修改路线。</p>}<div className="actions"><button disabled={!!deciding} onClick={() => { void decide(proposal, 'accept'); }}>{deciding === proposal.id ? '审核中…' : '接受提案并发布'}</button><button className="quiet" disabled={!!deciding} onClick={() => { void decide(proposal, 'reject'); }}>拒绝提案</button></div></>}
    </article>)}</div>}
  </section>;
}
