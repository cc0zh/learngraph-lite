import { GraphCanvas, Icon } from '../components';
import type { Conversation, Plan } from '../types';

export function KnowledgeOverview({ plan, selected, conversations, disabled, onSelect, onStart, onContinue, onBrowse, onPlanning }: {
  plan: Plan; selected: string; conversations: Conversation[]; disabled: boolean;
  onSelect: (id: string) => void; onStart: (id: string) => void; onContinue: (conversation: Conversation) => void;
  onBrowse: (id: string) => void; onPlanning: () => void;
}) {
  const graph = plan.graph;
  const node = graph?.nodes.find(item => item.id === selected)
    || graph?.nodes.find(item => !graph.edges.some(edge => edge.target === item.id)) || graph?.nodes[0];
  const previous = conversations.filter(item => item.kind === 'learning' && item.goal_id === plan.goal_id && item.node_id === node?.id)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  return <section className="knowledge-overview" aria-label="知识图谱全景">
    <div className="overview-intro"><h2>{graph?.status === 'published' ? '知识全景' : '图谱还在生长'}</h2>
      <p>{graph?.status === 'published' ? '先看见知识之间的联系，再从一个节点深入。' : '和学习助手一起明确范围，审核后再开启节点学习。'}</p>
    </div>
    {graph ? <>
      <div className="overview-facts"><span><strong>{graph.nodes.length}</strong> 个知识节点</span><span><strong>{graph.edges.length}</strong> 条前置关系</span><span className="overview-state">{graph.status === 'published' ? '已发布，可开始学习' : '草稿，等待你的审核'}</span></div>
      {graph.status === 'published' && node && <section className="overview-entry" aria-label="进入节点学习">
        <div><h3>{previous ? '接着上次的探索' : '从一个节点开始'}</h3><p>不必先配资料或做练习，选择一个想弄懂的知识点就可以开始。</p></div>
        <label htmlFor={`overview-node-${plan.goal_id}`}>学习节点</label><select id={`overview-node-${plan.goal_id}`} value={node.id} onChange={event => onSelect(event.target.value)}>{graph.nodes.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select>
        <p className="small muted">{node.explanation}</p>
        <div className="actions">{previous ? <><button type="button" onClick={() => onContinue(previous)}>继续节点对话<Icon name="chat"/></button><button type="button" className="quiet" disabled={disabled} onClick={() => onStart(node.id)}>新建节点对话</button></>
          : <button type="button" disabled={disabled} onClick={() => onStart(node.id)}>开始节点学习<Icon name="chat"/></button>}</div>
        <p className="small muted">{previous ? '继续仅打开已保存对话，不会自动调用模型；新建则开始一次独立讲解。' : '点击开始会新建独立对话，并调用模型讲解。教材和练习可以稍后按需使用。'}</p>
      </section>}
      <GraphCanvas graph={graph} selected={selected} onSelect={onBrowse} compact/>
      <div className="overview-footer"><p>点击节点查看内容。浏览不会改变当前对话。</p><button type="button" className="quiet" onClick={onPlanning}>查看目标创建对话<Icon name="chat"/></button></div>
    </> : <div className="overview-awaiting"><Icon name="folder"/><p>目标已保存，下一步是把它梳理成知识图谱。</p><button type="button" onClick={onPlanning}>查看目标创建对话</button></div>}
  </section>;
}
