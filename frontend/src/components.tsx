import Markdown from 'react-markdown';
import { useEffect, useState } from 'react';
import dagre from '@dagrejs/dagre';
import { Background, Controls, ReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { Graph, Run } from './types';
import { terminal } from './api';
import type { Command } from './useRuns';
import { Citations } from './documents';

const statusLabels: Record<string, string> = { queued: '排队中', running: '执行中', completed: '已完成', failed: '失败', cancelled: '已停止', interrupted: '已中断', budget_exceeded: '已达预算上限' };
const planningToolLabels: Record<string, string> = { read_planning_context: '读取当前目标与路线', request_clarification: '整理需要澄清的问题', propose_goal_draft: '提炼目标摘要', generate_route_draft: '整理学习路线草稿' };
export function ErrorBox({ error }: { error: string }) { return error ? <p className="error" role="alert">{error}</p> : null; }
export function SafeMarkdown({ children }: { children: string }) { return <Markdown skipHtml disallowedElements={['img']}>{children}</Markdown>; }
export function RunCitations({ run, goalId, nodeId }: { run: Run; goalId: string; nodeId?: string }) {
  return <Citations citationMap={run.output?.citation_map || {}} unverifiedIds={run.output?.unverified_citation_ids}
    endpoint={`/api/runs/${encodeURIComponent(run.run_id)}/citations/{citationId}`} goalId={goalId} nodeId={nodeId}/>;
}
export function PendingRequest({ command, checked, sending, query, resend, readOnly = false }: { command?: Command; checked: boolean; sending: boolean; query: () => void; resend: () => void; readOnly?: boolean }) {
  if (!command) return null;
  return <div className="hint" role="region" aria-label="未确认请求恢复"><strong>请求尚未确认</strong>
    <p>{typeof command.body.user_text === 'string' ? command.body.user_text : typeof command.body.feedback === 'string' && command.body.feedback ? command.body.feedback : command.path}</p>
    <p className="small">请求 ID：{String(command.body.request_id)}</p>
    <p>输入已保存在本浏览器。先查询运行状态，再显式重发同一请求；如果任务已存在，只恢复该任务，不重复执行。</p>
    <div className="actions"><button type="button" className="quiet" disabled={sending} onClick={query}>查询运行状态</button>
      <button type="button" className="secondary" disabled={sending || !checked || readOnly} onClick={resend}>重发未确认请求</button></div>
  </div>;
}
export function GraphCanvas({ graph, selected, onSelect, compact = false }: { graph: Graph; selected?: string; onSelect: (id: string) => void; compact?: boolean }) {
  const height = compact ? 54 : 65;
  const layout = new dagre.graphlib.Graph().setGraph({ rankdir: compact ? 'TB' : 'LR', nodesep: compact ? 20 : 35, ranksep: compact ? 24 : 60 }).setDefaultEdgeLabel(() => ({}));
  for (const n of graph.nodes) layout.setNode(n.id, { width: 160, height });
  for (const e of graph.edges) layout.setEdge(e.source, e.target);
  dagre.layout(layout);
  const nodes = graph.nodes.map(n => {
    const position = layout.node(n.id);
    return { id: n.id, data: { label: compact ? n.title : `${n.title} · ${n.estimated_minutes} 分钟` }, position: { x: position.x - 80, y: position.y - height / 2 }, selected: selected === n.id,
      ...(compact ? { style: { width: 160, height, display: 'grid', placeItems: 'center', fontSize: 14 } } : {}) };
  });
  return <div className="graph-canvas" aria-label={compact ? '知识图谱' : '学习路线图'}><ReactFlow nodes={nodes} edges={graph.edges.map((e, i) => ({ id: String(i), source: e.source, target: e.target }))}
    onNodeClick={(_, n) => onSelect(n.id)} fitView nodesDraggable={false} nodesConnectable={false} minZoom={0.2}><Background/><Controls showInteractive={false}/></ReactFlow></div>;
}
export function RunStatus({ run, stop, retry, readOnly = false }: { run?: Run; stop: () => void; retry: () => void; readOnly?: boolean }) {
  const [now, setNow] = useState(Date.now());
  const live = run && !terminal(run.status);
  useEffect(() => { if (!live) return; const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, [live]);
  if (!run) return null;
  return <div className="run-status" role="status"><span className={!terminal(run.status) ? 'pulse' : ''}/><strong>{statusLabels[run.status] || run.status}</strong>
    <span>{{ planning: '讨论目标与路线', graph: '生成路线', clarify: '澄清目标', exercise: '生成练习', lesson: '生成学习包', explanation: '组件解释', proposal: '生成路线调整提案', teaching: '节点对话' }[run.mode] || '任务'}</span>
    {live && <span>{Math.max(0, Math.floor((now - Date.parse(run.created_at)) / 1000))} 秒</span>}
    {!readOnly && (!terminal(run.status) ? <button className="quiet" onClick={stop}>停止</button> : run.status !== 'completed' ? <button className="quiet" onClick={() => retry()}>重试</button> : null)}
    {run.error && <p className="error">{run.error}</p>}
    {Object.values(run.tool_activity || {}).map(t => <div className="tool" key={t.call_id}>{run.mode === 'planning' ? planningToolLabels[t.name] || '处理规划信息' : t.name} · {statusLabels[t.status] || t.status}{t.elapsed_ms !== undefined && ` · ${t.elapsed_ms} ms`}</div>)}
    {run.status === 'cancelled' && <small>停止不会撤销已经保存的业务结果。</small>}
  </div>;
}
