import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import { ErrorBox } from '../components';
import type { Plan } from '../types';

export function Home() {
  const [goals, setGoals] = useState<Plan[]>();
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { api<Plan[]>('/goals').then(setGoals).catch(e => setError(String(e))); }, []);
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const plan = await api<Plan>('/goals', { title }); location.href = `/goals/${plan.goal_id}/plan`; }
    catch (e) { setError(String(e)); setBusy(false); }
  }
  return <div className="home"><section className="hero"><p className="eyebrow">一条路线，一个可验证的目标</p><h1>让想学的，变成学会的。</h1><p className="muted">从你的目标出发，整理学习路径，在每个节点解释、练习与复盘。</p>
    <form className="create-goal" onSubmit={create}><label htmlFor="goal-title">你想学会什么？</label><div className="inline"><input id="goal-title" placeholder="例如：做出一个可核查来源的 RAG 应用" value={title} onChange={e => setTitle(e.target.value)} required maxLength={2000}/><button disabled={busy}>{busy ? '创建中…' : '开始规划 →'}</button></div></form><ErrorBox error={error}/></section>
    <section><div className="section-title"><h2>我的学习路线</h2><span className="muted">{goals?.length || 0} 个目标</span></div>
    {!goals ? <p role="status">正在读取已保存的目标…</p> : !goals.length ? <div className="empty"><span className="empty-icon">↗</span><h3>从一个具体目标开始</h3><p>说明你希望做出的成果，路线会在审核发布后开始。</p></div> : <div className="goal-grid">{goals.map(p => <a className="goal-card" key={p.goal_id} href={`/goals/${p.goal_id}/${p.graph?.status === 'published' ? 'learn' : 'plan'}`}><span className="tag">{p.graph?.status === 'published' ? '学习中' : p.goal.confirmed ? '待审核路线' : '目标草稿'}</span><h3>{p.goal.title}</h3><p>{p.goal.desired_outcome || '补充成果与时间，形成适合你的路线。'}</p><div className="card-foot"><span>{p.graph ? `${p.graph.nodes.length} 个节点` : '尚未生成路线'}</span><strong>继续 →</strong></div></a>)}</div>}
    </section></div>;
}
