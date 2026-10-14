import { useEffect, useRef, useState } from 'react';
import { DocumentBindings } from './DocumentBindings';
import { documentError, documentPath, documentRequest } from './http';
import { DocumentError, DocumentStatus, PAGE_SIZE, Pagination, parsing } from './shared';
import type { ChunkPage, DocumentBinding, PublicDocument } from './types';
import './documents.css';

interface GoalScope { goal_id: string; goal: { title: string }; graph: { nodes: { id: string; title: string }[] } | null }
export function DocumentDetail({ documentId }: { documentId: string }) {
  return <DetailScope key={documentId} documentId={documentId}/>;
}
function DetailScope({ documentId }: { documentId: string }) {
  const query = new URLSearchParams(location.search);
  const targetChunk = query.get('chunk') || '';
  const [document, setDocument] = useState<PublicDocument>();
  const [bindings, setBindings] = useState<DocumentBinding[]>([]);
  const [goals, setGoals] = useState<GoalScope[]>([]);
  const [goalId, setGoalId] = useState(query.get('goal') || '');
  const [nodeId, setNodeId] = useState(query.get('node') || '');
  const [offset, setOffset] = useState(0);
  const [chunks, setChunks] = useState<ChunkPage>();
  const [loading, setLoading] = useState(true);
  const [chunkLoading, setChunkLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [scopeError, setScopeError] = useState('');
  const [chunkError, setChunkError] = useState('');
  const [targetError, setTargetError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const located = useRef('');
  const selectedChunk = useRef<HTMLElement | null>(null);
  const path = documentPath(documentId);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    Promise.all([
      documentRequest<PublicDocument>(path, { signal: controller.signal }),
      documentRequest<{ bindings: DocumentBinding[] }>(`${path}/bindings`, { signal: controller.signal }),
    ]).then(([value, links]) => {
      if (!controller.signal.aborted) { setDocument(value); setBindings(links.bindings); }
    }).catch(e => { if (!controller.signal.aborted) setError(documentError(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, refresh]);
  useEffect(() => {
    const controller = new AbortController();
    documentRequest<GoalScope[]>('/goals', { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) { setGoals(value); setScopeError(''); }
    }).catch(e => { if (!controller.signal.aborted) setScopeError(documentError(e)); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!document || !parsing(document) || loading || error || busy) return;
    const timer = setTimeout(() => setRefresh(n => n + 1), 1500);
    return () => clearTimeout(timer);
  }, [document, loading, error, busy]);
  useEffect(() => {
    if (document?.status !== 'ready') { setChunks(undefined); return; }
    const controller = new AbortController();
    setChunkLoading(true); setChunkError('');
    void (async () => {
      try {
        const key = `${documentId}:${targetChunk}`;
        const findTarget = targetChunk && located.current !== key;
        let start = findTarget ? 0 : offset;
        let result = await documentRequest<ChunkPage>(`${path}/chunks?offset=${start}&limit=${PAGE_SIZE}`, { signal: controller.signal });
        // Chunk IDs are opaque: scan bounded pages rather than guessing :cN semantics.
        while (findTarget && !result.chunks.some(chunk => chunk.id === targetChunk) && start + PAGE_SIZE < result.total) {
          start += PAGE_SIZE;
          result = await documentRequest<ChunkPage>(`${path}/chunks?offset=${start}&limit=${PAGE_SIZE}`, { signal: controller.signal });
        }
        if (controller.signal.aborted) return;
        if (findTarget) {
          located.current = key;
          if (!result.chunks.some(chunk => chunk.id === targetChunk)) setTargetError('指定片段不存在，可能资料内容已变化。请返回产物重新校验来源。');
        }
        setChunks(result); if (start !== offset) setOffset(start);
      } catch (e) { if (!controller.signal.aborted) setChunkError(documentError(e)); }
      finally { if (!controller.signal.aborted) setChunkLoading(false); }
    })();
    return () => controller.abort();
  }, [path, documentId, document?.status, offset, targetChunk, refresh]);
  useEffect(() => {
    if (chunkLoading || !selectedChunk.current) return;
    selectedChunk.current.focus({ preventScroll: true }); selectedChunk.current.scrollIntoView({ block: 'nearest' });
  }, [chunks, chunkLoading]);
  function chooseScope(goal: string, node: string) {
    setGoalId(goal); setNodeId(node);
    const parameters = new URLSearchParams(location.search);
    if (goal) parameters.set('goal', goal); else parameters.delete('goal');
    if (node) parameters.set('node', node); else parameters.delete('node');
    history.replaceState(null, '', `${path}${parameters.size ? `?${parameters}` : ''}`);
  }
  async function reparse() {
    if (busy) return; setBusy(true); setError('');
    try { setDocument(await documentRequest<PublicDocument>(`${path}/reparse`, { method: 'POST' })); setRefresh(n => n + 1); }
    catch (e) { setError(documentError(e)); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (busy || !window.confirm('确认删除此资料及所有目标、节点绑定？删除后不能恢复，旧引用会降级为不可用。')) return;
    setBusy(true); setError('');
    try { await documentRequest<{ deleted: boolean }>(path, { method: 'DELETE' }); window.location.assign('/documents'); }
    catch (e) { setError(documentError(e)); }
    finally { setBusy(false); }
  }
  const selectedGoal = goals.find(goal => goal.goal_id === goalId);
  const validScope = !!selectedGoal && (!nodeId || selectedGoal.graph?.nodes.some(node => node.id === nodeId));
  const hasScopeBinding = bindings.some(binding => binding.goal_id === goalId && binding.node_id === (nodeId || null));
  return <div className="page documents-scope"><header className="doc-heading"><div><p className="eyebrow">资料原文</p><h1>{document?.filename || '资料详情'}</h1></div><a href="/documents">返回资料列表</a></header>
    <DocumentError error={error}/>{loading && <p role="status">正在读取资料…</p>}
    {document && <><section className="doc-panel"><DocumentStatus document={document}/>
      <p className="doc-muted">{(document.size_bytes / 1024).toFixed(1)} KB · 资料版本 {document.revision} · {document.kind || '未知格式'}</p>
      <div className="doc-actions"><button type="button" className="quiet" disabled={busy || loading} onClick={() => setRefresh(n => n + 1)}>刷新资料状态</button>
        {['failed', 'unsupported'].includes(document.status) && <button type="button" className="secondary" disabled={busy || loading} onClick={() => { void reparse(); }}>重新解析</button>}
        <button type="button" className="doc-danger" disabled={busy || loading} onClick={() => { void remove(); }}>删除资料</button></div>
      {['failed', 'unsupported'].includes(document.status) && <p className="doc-muted">支持 UTF-8 TXT / Markdown 和含文本的 PDF。扫描 PDF 需要先在本地 OCR；重新解析仍使用已保存的原文件，不会自动修改文件内容。</p>}
    </section>
    <div className="doc-detail-grid"><section className="doc-panel" role="region" aria-label="资料原文" aria-busy={chunkLoading}>
      <h2>原文片段</h2><p className="doc-muted">按服务器保存的片段显示纯文本；HTML、图片与外部资源不会执行或加载。页码、标题与偏移均来自服务器。</p>
      <DocumentError error={targetError || chunkError}/>{chunkLoading && <p role="status">正在定位原文…</p>}
      {document.status !== 'ready' && <p>资料未解析完成，暂不能查看原文或参与检索。</p>}
      {chunks && <><Pagination offset={offset} total={chunks.total} label="原文" busy={chunkLoading} onChange={setOffset}/>
        {!chunks.chunks.length && !chunkLoading && <p>没有可读取的原文片段。</p>}
        {chunks.chunks.map(chunk => <article key={chunk.id} className={`doc-chunk ${chunk.id === targetChunk ? 'doc-chunk-selected' : ''}`}
          ref={chunk.id === targetChunk ? selectedChunk : undefined} tabIndex={-1} data-selected-chunk={chunk.id === targetChunk ? 'true' : undefined}>
          <h3>{chunk.heading || `片段 ${chunk.index + 1}`}{chunk.page_number !== null && ` · 第 ${chunk.page_number} 页`}</h3>
          <p className="doc-muted doc-meta">版本 {chunk.document_version} · 字符偏移 {chunk.start_offset}–{chunk.end_offset}<br/>片段 ID：{chunk.id}<br/>文本摘要：{chunk.text_hash}</p>
          <pre className="doc-plain">{chunk.text}</pre>
        </article>)}</>}
    </section><aside className="doc-sidebar"><section className="doc-panel"><h2>绑定到目标 / 节点</h2><DocumentError error={scopeError}/>
      <label>绑定目标<select value={goalId} onChange={e => chooseScope(e.target.value, '')}><option value="">请选择学习目标</option>{goals.map(goal => <option key={goal.goal_id} value={goal.goal_id}>{goal.goal.title}</option>)}</select></label>
      {selectedGoal && <label>绑定节点<select value={nodeId} onChange={e => chooseScope(goalId, e.target.value)}><option value="">目标级（先绑定目标）</option>{selectedGoal.graph?.nodes.map(node => <option key={node.id} value={node.id}>{node.title}</option>)}</select></label>}
      {goalId && !validScope && <p className="doc-warning">指定目标或节点不存在，请重新选择有效的绑定范围。</p>}
      {validScope && !loading && !hasScopeBinding && <p className="doc-warning">409 · 此资料尚未绑定当前{nodeId ? '节点' : '目标'}，不能作为该范围的有效来源；原文仍可独立浏览。</p>}
    </section>
    {validScope && <DocumentBindings key={`${goalId}:${nodeId}:${document.status}`} goalId={goalId} nodeId={nodeId || undefined} defaultDocumentId={documentId} onChanged={() => setRefresh(n => n + 1)}/>}
    <section className="doc-panel"><h2>服务器保存的关联</h2><p className="doc-muted">此清单从服务器读取，绑定后会重新查询；也可点击“刷新资料状态”。</p>
      {!bindings.length ? <p>尚无关联。</p> : <ul className="doc-associations">{bindings.map(binding => <li key={`${binding.goal_id}:${binding.node_id || ''}`}>
        <a href={`/goals/${encodeURIComponent(binding.goal_id)}/${binding.node_id ? 'learn' : 'plan'}`}>{goals.find(goal => goal.goal_id === binding.goal_id)?.goal.title || binding.goal_id}</a>
        <p>{binding.node_id ? `节点：${goals.find(goal => goal.goal_id === binding.goal_id)?.graph?.nodes.find(node => node.id === binding.node_id)?.title || binding.node_id}` : '目标级绑定（不自动继承到节点）'}</p>
      </li>)}</ul>}
    </section></aside></div></>}
  </div>;
}
