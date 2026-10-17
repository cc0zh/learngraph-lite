import Markdown from 'react-markdown';
import { useEffect, useState } from 'react';
import dagre from '@dagrejs/dagre';
import { Controls, ReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { Graph, Run } from './types';
import { terminal } from './api';
import type { Command } from './useRuns';
import { Citations } from './documents';

const statusLabels: Record<string, string> = { queued: '排队中', running: '执行中', completed: '已完成', failed: '失败', cancelled: '已停止', interrupted: '已中断', budget_exceeded: '已达预算上限' };
const toolLabels: Record<string, string> = {
  read_planning_context: '读取当前目标与路线', request_clarification: '整理需要澄清的问题',
  propose_goal_draft: '提炼目标摘要', generate_route_draft: '整理学习路线草稿',
  get_learning_context: '读取当前学习状态', get_next_action: '查询下一步建议',
  search_documents: '检索学习资料', read_document_chunk: '读取资料原文',
  create_exercise: '生成练习', create_lesson: '生成学习包',
  propose_graph_change: '提出图谱调整建议', read_skill: '读取学习指南',
};
const iconPaths = {
  plus: 'M12 5v14M5 12h14',
  chat: 'M20 11.5a8 8 0 0 1-8 8H5l-3 2V11.5a9 9 0 0 1 18 0Z',
  folder: 'M3 7V5h6l2 2h10v12H3V7Z',
  refresh: 'M20 8V3l-3 3a8 8 0 1 0 3 9M20 3h-5',
  arrowUp: 'M12 19V5M6 11l6-6 6 6',
  stop: 'M6 6h12v12H6Z',
  chevron: 'm8 5 7 7-7 7',
  check: 'm5 12 4 4L19 6',
  warning: 'M12 8v5m0 3h.01M12 3 2 21h20L12 3Z',
  book: 'M12 5v15M3 4h5l4 2 4-2h5v15h-5l-4 2-4-2H3V4Z',
};
export function Icon({ name }: { name: keyof typeof iconPaths }) {
  return <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={iconPaths[name]}/></svg>;
}
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
    return { id: n.id, width: 160, height, data: { label: compact ? n.title : `${n.title} · ${n.estimated_minutes} 分钟` }, position: { x: position.x - 80, y: position.y - height / 2 }, selected: selected === n.id,
      ...(compact ? { style: { width: 160, height, display: 'grid', placeItems: 'center', fontSize: 14 } } : {}) };
  });
  return <div className="graph-canvas" data-ui aria-label={compact ? '知识图谱' : '学习路线图'}><ReactFlow nodes={nodes} edges={graph.edges.map((e, i) => ({ id: String(i), source: e.source, target: e.target }))}
    onNodeClick={(_, n) => onSelect(n.id)} fitView nodesDraggable={false} nodesConnectable={false} minZoom={0.2}><Controls showInteractive={false}/></ReactFlow></div>;
}
export function RunStatus({ run, stop, retry, readOnly = false }: { run?: Run; stop: () => void; retry: () => void; readOnly?: boolean }) {
  const [now, setNow] = useState(Date.now());
  const live = run && !terminal(run.status);
  useEffect(() => { if (!live) return; const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, [live]);
  if (!run) return null;
  const tools = Object.values(run.tool_activity || {});
  const failedTools = tools.filter(tool => tool.status === 'failed').length;
  return <div className="run-status" role="status"><span className={!terminal(run.status) ? 'pulse' : ''}/><strong>{statusLabels[run.status] || run.status}</strong>
    <span>{{ planning: '讨论目标与路线', graph: '生成路线', clarify: '澄清目标', exercise: '生成练习', lesson: '生成学习包', explanation: '组件解释', proposal: '生成路线调整提案', teaching: '节点对话' }[run.mode] || '任务'}</span>
    {live && <span>{Math.max(0, Math.floor((now - Date.parse(run.created_at)) / 1000))} 秒</span>}
    {!readOnly && (!terminal(run.status) ? <button className="quiet" onClick={stop}>停止</button> : run.status !== 'completed' ? <button className="quiet" onClick={() => retry()}>重试</button> : null)}
    {run.error && <p className="error">{run.error}</p>}
    {/* ReactFlow listens on window; keep native summary Space activation local. */}
    {!!tools.length && <details className="run-tools" key={run.run_id}><summary onKeyDown={event => { if (event.key === ' ') event.stopPropagation(); }}><Icon name="chevron"/><span>处理步骤</span><span className={failedTools ? 'run-tool-failures' : 'run-tool-count'}>{tools.length} 项{failedTools ? ` · ${failedTools} 项失败` : ''}</span></summary>
      <ul className="run-tool-list">{tools.map(t => <li className="tool" data-tool-name={t.name} data-state={t.status} key={t.call_id}>
        <Icon name={t.status === 'completed' ? 'check' : t.status === 'failed' ? 'warning' : 'chevron'}/><span className="run-tool-name">{toolLabels[t.name] || '处理学习操作'}</span><span className="run-tool-result">{statusLabels[t.status] || t.status}{t.elapsed_ms !== undefined && ` · ${t.elapsed_ms} ms`}</span>
      </li>)}</ul>
    </details>}
    {run.status === 'cancelled' && <small>停止不会撤销已经保存的业务结果。</small>}
  </div>;
}
