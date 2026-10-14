import { useEffect, useId, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { chunkLink, documentError, documentPath, documentRequest } from './http';
import { DocumentError, PAGE_SIZE, Pagination, parsing } from './shared';
import type { DocumentPage, PublicDocument, SearchResult } from './types';
import './documents.css';

export interface DocumentBindingsProps { goalId: string; nodeId?: string; defaultDocumentId?: string; onChanged?: () => void }
export function DocumentBindings(props: DocumentBindingsProps) {
  return <BindingsScope key={`${props.goalId}:${props.nodeId || ''}:${props.defaultDocumentId || ''}`} {...props}/>;
}
function BindingsScope({ goalId, nodeId, defaultDocumentId, onChanged }: DocumentBindingsProps) {
  const selectId = useId();
  const [page, setPage] = useState<DocumentPage>();
  const [offset, setOffset] = useState(0);
  const [bound, setBound] = useState<{ id: string; document?: PublicDocument }[]>([]);
  const [goalBound, setGoalBound] = useState<string[]>([]);
  const [currentDocument, setCurrentDocument] = useState<PublicDocument>();
  const [selected, setSelected] = useState(defaultDocumentId || '');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult>();
  const [searching, setSearching] = useState(false);
  const alive = useRef(true);
  const searchRequest = useRef<AbortController | undefined>(undefined);
  const base = `/goals/${encodeURIComponent(goalId)}/document-bindings`;
  const scopeQuery = nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : '';
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; searchRequest.current?.abort(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setResults(undefined);
    const read = <T,>(path: string) => documentRequest<T>(path, { signal: controller.signal });
    void (async () => {
      try {
        const [documents, bindings, parents, current] = await Promise.all([
          read<DocumentPage>(`/documents?offset=${offset}&limit=${PAGE_SIZE}`),
          read<{ document_ids: string[] }>(`${base}${scopeQuery}`),
          nodeId ? read<{ document_ids: string[] }>(base) : Promise.resolve(undefined),
          defaultDocumentId ? read<PublicDocument>(documentPath(defaultDocumentId)) : Promise.resolve(undefined),
        ]);
        const records = await Promise.all(bindings.document_ids.map(async id => {
          const existing = documents.documents.find(d => d.document_id === id);
          return { id, document: existing || await read<PublicDocument>(documentPath(id)) };
        }));
        if (controller.signal.aborted) return;
        setPage(documents); setBound(records); setGoalBound(parents?.document_ids || bindings.document_ids); setCurrentDocument(current);
      } catch (e) { if (!controller.signal.aborted) setError(documentError(e)); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    })();
    return () => controller.abort();
  }, [base, scopeQuery, nodeId, defaultDocumentId, offset, refresh]);
  const pending = page?.documents.some(parsing) || (currentDocument && parsing(currentDocument));
  useEffect(() => {
    if (!pending || loading || error || busy || searching) return;
    const timer = setTimeout(() => setRefresh(n => n + 1), 1500);
    return () => clearTimeout(timer);
  }, [pending, loading, error, busy, searching, refresh]);
  async function mutate(documentId: string, remove = false) {
    if (busy || loading) return;
    if (remove && !window.confirm(nodeId ? '确认解绑此节点的资料？旧引用可能变为不可用。' : '确认解绑此目标的资料？该目标下此资料的所有节点关联也会被清除，旧引用可能变为不可用。')) return;
    setBusy(true); setError('');
    try {
      const response = await documentRequest<{ document_ids: string[] }>(base, {
        method: remove ? 'DELETE' : 'POST', body: { document_id: documentId, node_id: nodeId || null },
      });
      if (!alive.current) return;
      // Use the saved server response, then GET fresh metadata/parent bindings.
      setBound(response.document_ids.map(id => ({ id, document: bound.find(item => item.id === id)?.document || candidates.find(d => d.document_id === id) })));
      setResults(undefined); setRefresh(n => n + 1); onChanged?.();
    } catch (e) { if (alive.current) setError(documentError(e)); }
    finally { if (alive.current) setBusy(false); }
  }
  async function search(event: FormEvent) {
    event.preventDefault(); if (!query.trim() || searching || busy || loading) return;
    setSearching(true); setError(''); setResults(undefined);
    const controller = new AbortController(); searchRequest.current = controller;
    try {
      const value = await documentRequest<SearchResult>(`/goals/${encodeURIComponent(goalId)}/document-search`, {
        method: 'POST', body: { query: query.trim(), node_id: nodeId || null, limit: 5 }, signal: controller.signal,
      });
      if (alive.current && !controller.signal.aborted) setResults(value);
    } catch (e) { if (alive.current && !controller.signal.aborted) setError(documentError(e)); }
    finally { if (alive.current) setSearching(false); }
  }
  const candidates = [...(page?.documents || [])];
  if (currentDocument && !candidates.some(d => d.document_id === currentDocument.document_id)) candidates.unshift(currentDocument);
  const allowed = (d: PublicDocument) => d.status === 'ready' && (!nodeId || goalBound.includes(d.document_id));
  const canBind = candidates.some(d => d.document_id === selected && allowed(d)) && !bound.some(b => b.id === selected);
  return <section className="documents-scope doc-panel doc-bindings" role="region" aria-label={nodeId ? '节点资料绑定' : '目标资料绑定'} aria-busy={loading}>
    <h2>{nodeId ? '节点资料' : '目标资料'}</h2><p className="doc-hint">节点资料不是自动继承：先绑定目标，再为每个需要的节点显式绑定。解绑目标会清除此资料在该目标下的所有节点关联。</p>
    <DocumentError error={error}/>{loading && <p role="status">正在读取服务器绑定…</p>}
    <div className="doc-actions"><a href="/documents">管理与上传资料</a><button type="button" className="quiet" disabled={loading || busy || searching} onClick={() => setRefresh(n => n + 1)}>刷新资料绑定</button></div>
    {!loading && !error && !bound.length && <p className="doc-muted">{nodeId ? '此节点尚未显式绑定资料。' : '此目标尚未绑定资料。'}</p>}
    <ul className="doc-bound-list" aria-label="已绑定资料">{bound.map(item => <li key={item.id}>
      <div><a href={`${documentPath(item.id)}?${new URLSearchParams({ goal: goalId, ...(nodeId ? { node: nodeId } : {}) })}`}>{item.document?.filename || item.id}</a>
        {item.document && item.document.status !== 'ready' && <p className="doc-muted">资料未就绪，暂不可用于检索。</p>}</div>
      <button type="button" className="quiet" disabled={busy || loading || searching} onClick={() => { void mutate(item.id, true); }}>解绑资料</button>
    </li>)}</ul>
    <label htmlFor={selectId}>选择要绑定的资料</label><select id={selectId} value={selected} disabled={busy || loading || searching} onChange={e => setSelected(e.target.value)}>
      <option value="">请选择已解析的资料</option>{candidates.map(document => <option key={document.document_id} value={document.document_id} disabled={!allowed(document)}>
        {document.filename}{document.status !== 'ready' ? '（未就绪）' : nodeId && !goalBound.includes(document.document_id) ? '（请先绑定目标）' : ''}
      </option>)}
    </select><div className="doc-actions"><button type="button" disabled={busy || loading || searching || !canBind} onClick={() => { void mutate(selected); }}>绑定所选资料</button></div>
    {nodeId && currentDocument && !goalBound.includes(currentDocument.document_id) && <p className="doc-muted">此资料还未绑定目标，请切换到“目标级”先绑定。</p>}
    {page && page.total > PAGE_SIZE && <Pagination offset={offset} total={page.total} label="可选资料" busy={loading || busy || searching} onChange={setOffset}/>}
    <form className="doc-search" onSubmit={search}><label>检索绑定资料<input value={query} maxLength={500} onChange={e => setQuery(e.target.value)} disabled={busy || loading || searching} placeholder="输入原文关键词"/></label>
      <button disabled={busy || loading || searching || !query.trim() || !bound.length}>{searching ? '正在检索…' : '检索资料'}</button></form>
    {results && <section role="region" aria-label="资料检索结果"><p className="doc-muted">仅搜索当前{nodeId ? '节点显式' : '目标'}绑定资料，最多 5 个片段；排序分值不代表可信度。</p>
      {results.empty && <p>没有匹配的原文片段，请尝试其他关键词。</p>}
      {results.hits.map(hit => <article className="doc-search-hit" key={hit.chunk.id}><h3>{hit.chunk.heading || '原文片段'}{hit.chunk.page_number !== null && ` · 第 ${hit.chunk.page_number} 页`}</h3>
        <p className="doc-plain">{hit.chunk.text}</p><a href={chunkLink(hit.chunk.document_id, hit.chunk.id, goalId, nodeId)}>查看片段原文</a>
      </article>)}
    </section>}
  </section>;
}
