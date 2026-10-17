import { GraphCanvas, Icon } from '../components';
import type { Plan } from '../types';

export function KnowledgeOverview({ plan, selected, onBrowse, onPlanning }: { plan: Plan; selected: string; onBrowse: (id: string) => void; onPlanning: () => void }) {
  const graph = plan.graph;
  return <section className="knowledge-overview" aria-label="知识图谱全景">
    <div className="overview-intro"><h2>{graph?.status === 'published' ? '知识全景' : '图谱还在生长'}</h2>
      <p>{graph?.status === 'published' ? '先看见知识之间的联系，再从一个节点深入。' : '和学习助手一起明确范围，审核后再开启节点学习。'}</p>
    </div>
    {graph ? <>
      <div className="overview-facts"><span><strong>{graph.nodes.length}</strong> 个知识节点</span><span><strong>{graph.edges.length}</strong> 条前置关系</span><span className="overview-state">{graph.status === 'published' ? '已发布，可开始学习' : '草稿，等待你的审核'}</span></div>
      <GraphCanvas graph={graph} selected={selected} onSelect={onBrowse} compact/>
      <div className="overview-footer"><p>点击节点查看内容。浏览不会改变当前对话。</p><button type="button" className="quiet" onClick={onPlanning}>查看目标创建对话<Icon name="chat"/></button></div>
    </> : <div className="overview-awaiting"><Icon name="folder"/><p>目标已保存，下一步是把它梳理成知识图谱。</p><button type="button" onClick={onPlanning}>查看目标创建对话</button></div>}
  </section>;
}
