import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { documentError, documentHref, documentPath, documentRequest } from './http';
import { DocumentError, DocumentLink, DocumentStatus, PAGE_SIZE, Pagination, parsing } from './shared';
import type { DocumentPage, PublicDocument } from './types';
import './documents.css';

export function Documents({ onChanged }: { onChanged?: () => void }) {
  const [page, setPage] = useState<DocumentPage>();
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [file, setFile] = useState<File>();
  const [uploaded, setUploaded] = useState<PublicDocument>();
  const input = useRef<HTMLInputElement>(null);
  const pagePending = page?.documents.some(parsing) || (uploaded && parsing(uploaded));
  useEffect(() => { if (uploaded) onChanged?.(); }, [uploaded?.document_id, uploaded?.status, onChanged]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    documentRequest<DocumentPage>(`/documents?offset=${offset}&limit=${PAGE_SIZE}`, { signal: controller.signal })
      .then(async value => {
        if (controller.signal.aborted) return;
        if (value.total > 0 && value.documents.length === 0 && offset > 0) { setOffset(Math.max(0, Math.floor((value.total - 1) / PAGE_SIZE) * PAGE_SIZE)); return; }
        setPage(value);
        const found = value.documents.find(d => d.document_id === uploaded?.document_id);
        if (found) setUploaded(found);
        else if (uploaded && parsing(uploaded)) {
          const saved = await documentRequest<PublicDocument>(documentPath(uploaded.document_id), { signal: controller.signal });
          if (!controller.signal.aborted) setUploaded(saved);
        }
      }).catch(e => { if (!controller.signal.aborted) setError(documentError(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [offset, refresh, uploaded?.document_id]);
  useEffect(() => {
    if (!pagePending || loading || error || busy) return;
    const timer = setTimeout(() => setRefresh(n => n + 1), 1500);
    return () => clearTimeout(timer);
  }, [pagePending, loading, error, busy, refresh]);
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file || busy) return;
    if (file.size > 10 * 1024 * 1024) { setError('文件超过 10 MB，请缩小文件后重新选择。'); return; }
    setBusy(true); setError('');
    const form = new FormData(); form.append('file', file);
    try {
      const value = await documentRequest<PublicDocument>('/documents', { method: 'POST', body: form });
      setUploaded(value); setFile(undefined); if (input.current) input.current.value = '';
      setOffset(0); setRefresh(n => n + 1);
    } catch (e) { setError(documentError(e)); }
    finally { setBusy(false); }
  }
  return <section className="documents-scope documents-tool" aria-label="资料管理"><header className="doc-heading"><div><h1>我的资料</h1><p className="doc-muted">你的资料，保留可校验的原文</p></div></header>
    <section className="doc-panel"><h2>上传学习资料</h2><p className="doc-muted">支持 UTF-8 TXT / Markdown 和含文本的 PDF；每个文件最多 10 MB、20 万字符，PDF 最多 100 页。不自动 OCR，不执行原文 HTML。</p>
      <form onSubmit={upload}><label>选择资料文件<input ref={input} type="file" accept=".txt,.md,.markdown,.pdf" disabled={busy} onChange={e => setFile(e.target.files?.[0])}/></label>
        <div className="doc-actions"><button disabled={!file || busy}>{busy ? '正在上传…' : '上传资料'}</button><button type="button" className="quiet" disabled={loading || busy} onClick={() => setRefresh(n => n + 1)}>刷新资料列表</button></div></form>
      {uploaded && <p role="status">已保存到服务器：<DocumentLink href={documentHref(uploaded.document_id)}>{uploaded.filename}</DocumentLink>。可查看原文、解析与绑定。</p>}
    </section>
    <DocumentError error={error}/>
    <section className="doc-list" aria-label="资料列表" aria-busy={loading}>
      {loading && <p role="status">正在读取资料…</p>}
      {!loading && !error && page?.total === 0 && <div className="doc-empty"><h2>还没有资料</h2><p>上传后显式绑定到学习目标，再为需要的节点单独绑定。</p></div>}
      {page?.documents.map(document => <article className="doc-panel" key={document.document_id}>
        <h2><DocumentLink href={documentHref(document.document_id)}>{document.filename}</DocumentLink></h2><DocumentStatus document={document}/>
        <p className="doc-muted">{(document.size_bytes / 1024).toFixed(1)} KB · 版本 {document.revision} · {document.kind || '未知格式'}</p>
        <DocumentLink href={documentHref(document.document_id)}>查看原文与绑定 →</DocumentLink>
      </article>)}
    </section>
    {page && <Pagination offset={offset} total={page.total} label="资料" busy={loading || busy} onChange={setOffset}/>}
  </section>;
}
