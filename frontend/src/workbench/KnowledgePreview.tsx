import { useState } from 'react';
import { Icon } from '../components';

export const knowledgeExamples = [
  { title: '检索增强生成', short: 'RAG', prompt: '我会 Python，想系统理解 RAG：从文档分块、向量检索到带来源的回答。',
    nodes: [
      { title: '文档分块', text: '把长文档拆成可检索的片段，理解粒度和上下文之间的取舍。' },
      { title: '向量表示', text: '用向量表达文本的含义，让相近的问题与片段能够相遇。' },
      { title: '相似度检索', text: '从资料中找到与问题相关的片段，比较召回与排序的作用。' },
      { title: '上下文组装', text: '把检索到的证据交给模型，并控制上下文的范围。' },
      { title: '来源与评估', text: '检查回答的出处，区分“检索到了”与“证据支持结论”。' },
    ] },
  { title: 'Python 基础', short: 'Python', prompt: '我想学习 Python 基础，重点理解数据类型、控制流、函数与可复用的小程序。',
    nodes: [
      { title: '值与类型', text: '从数字、字符串和布尔值开始，理解程序如何表达信息。' },
      { title: '容器与引用', text: '用列表和字典组织数据，辨别复制、引用与可变性。' },
      { title: '条件与循环', text: '根据条件选择路径，用循环重复处理数据。' },
      { title: '函数与作用域', text: '把逻辑分成可以组合的函数，明确参数、返回值与作用域。' },
      { title: '小程序实践', text: '把输入、处理与输出连起来，用一个小程序检验理解。' },
    ] },
  { title: '概率与统计', short: '统计', prompt: '我想建立概率与统计的知识图谱，从随机事件到分布、抽样与统计推断。',
    nodes: [
      { title: '随机事件', text: '用样本空间和事件描述不确定性，理解概率的含义。' },
      { title: '条件概率', text: '已知一个事件发生时，重新判断另一个事件的可能性。' },
      { title: '概率分布', text: '观察随机变量如何取值，用分布描述整体规律。' },
      { title: '抽样与估计', text: '从有限样本了解总体，同时保留对误差的认识。' },
      { title: '统计推断', text: '结合数据与假设作判断，区分统计证据与确定结论。' },
    ] },
];

export function KnowledgePreview({ example, onUse }: { example: number; onUse: () => void }) {
  const [selected, setSelected] = useState(2);
  const value = knowledgeExamples[example];
  return <section className="knowledge-preview" aria-label="知识图谱交互示例">
    <div className="preview-heading"><h2>知识是这样相连的</h2><span>交互示例</span></div>
    <div className="preview-map" data-ui aria-label={`${value.title}示例图谱`}>
      <div className="preview-orbit" aria-hidden="true"/>
      <svg className="preview-connections" viewBox="0 0 320 326" fill="none" aria-hidden="true">
        <path d="M80 48 C80 98 160 70 160 143 M240 48 C240 98 160 70 160 143 M160 172 C160 230 73 192 73 253 M160 172 C160 230 247 192 247 253"/>
      </svg>
      {value.nodes.map((node, index) => <button key={index} type="button" className={`preview-node preview-node-${index}`} aria-pressed={selected === index} onClick={() => setSelected(index)}>
        <span className="knowledge-dot" aria-hidden="true"/>{node.title}
      </button>)}
    </div>
    <div className="preview-description" aria-live="polite"><h3>{value.nodes[selected].title}</h3><p>{value.nodes[selected].text}</p></div>
    <button type="button" className="preview-use" onClick={onUse}>用此主题起草目标<Icon name="plus"/></button>
    <p className="preview-disclaimer">仅演示知识关系，不是 AI 生成结果。<br/>起草只填入输入框，发送后才创建。</p>
  </section>;
}
