import { useEffect, useRef, useState } from 'react';
import { navigateWorkbench } from '../workbench/navigation';
import { chunkLink, documentError, documentRequest } from './http';
import { DocumentError } from './shared';
import type { CitationMap, LocatedSource } from './types';
import './documents.css';

export interface CitationsProps {
  citationMap: CitationMap;
  unverifiedIds?: string[];
  /** Artifact-specific URL, e.g. /api/runs/<run>/citations/{citationId}.
   * A base URL ending in /citations or an ID-to-URL function is also supported.
   * Graph citations must include the saved planning version in their URL. */
  endpoint: string | ((citationId: string) => string);
  goalId?: string;
  nodeId?: string;
}
export function Citations({ citationMap, unverifiedIds = [], endpoint, goalId, nodeId }: CitationsProps) {
  const [checking, setChecking] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const request = useRef<AbortController | undefined>(undefined);
  useEffect(() => {
    setErrors({}); setChecking('');
    return () => request.current?.abort();
  }, [citationMap, endpoint, goalId, nodeId]);
  const ids = [...new Set([...Object.keys(citationMap), ...unverifiedIds])];
  if (!ids.length) return null;
  async function locate(id: string) {
    if (!citationMap[id] || citationMap[id].status !== 'valid' || unverifiedIds.includes(id) || checking) return;
    const controller = new AbortController(); request.current = controller; setChecking(id);
    setErrors(current => ({ ...current, [id]: '' }));
    try {
      let url: string;
      if (typeof endpoint === 'function') url = endpoint(id);
      else if (endpoint.includes('{citationId}')) url = endpoint.replace('{citationId}', encodeURIComponent(id));
      else {
        const [path, query] = endpoint.split('?');
        url = `${path.replace(/\/$/, '')}/${encodeURIComponent(id)}${query ? `?${query}` : ''}`;
      }
      const located = await documentRequest<LocatedSource>(url, { signal: controller.signal });
      if (controller.signal.aborted) return;
      // Never resolve a C-number globally or navigate using the completed snapshot.
      const source = located.source;
      if (source.status !== 'valid' || !source.document_id || !source.chunk_id) {
        setErrors(current => ({ ...current, [id]: '409 · 来源已过期或不可用，不能定位原文。' })); return;
      }
      navigateWorkbench(chunkLink(source.document_id, source.chunk_id, goalId, nodeId));
    } catch (e) { if (!controller.signal.aborted) setErrors(current => ({ ...current, [id]: documentError(e) })); }
    finally { if (!controller.signal.aborted) setChecking(''); }
  }
  return <section className="documents-scope doc-citations" role="region" aria-label="资料引用"><h3>资料引用</h3>
    <p className="doc-muted">编号仅属于这份产物；点击会向服务器重新校验来源。引用校验不证明回答被原文语义支持。</p>
    <ul>{ids.map(id => {
      const source = citationMap[id];
      const unverified = unverifiedIds.includes(id);
      const unavailable = source && source.status !== 'valid';
      return <li key={id}><strong>[{id}]</strong>{source ? <>
        <span>{source.heading || '原文片段'}{source.page_number !== null && ` · 第 ${source.page_number} 页`} · 资料版本 {source.document_version}</span>
        {source.quote && <blockquote className="doc-plain">{source.quote}</blockquote>}
        {unavailable ? <p className="doc-warning">409 · {source.status === 'stale' ? '来源已过期（stale）' : '来源不可用（unavailable）'}，原文定位已降级。请刷新产物与绑定。</p>
          : unverified ? <p className="doc-warning">未验证引用，原文定位不可用。</p>
          : <button type="button" className="quiet" disabled={!!checking} onClick={() => { void locate(id); }}>{checking === id ? `${id} · 校验中…` : `${id} · 查看原文`}</button>}
      </> : <p className="doc-warning">未知引用 [{id}]，未验证且不可点击。</p>}
        <DocumentError error={errors[id] || ''}/>
      </li>;
    })}</ul>
  </section>;
}
