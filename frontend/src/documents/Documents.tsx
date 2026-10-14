import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { documentError, documentPath, documentRequest } from './http';
import { DocumentError, DocumentStatus, PAGE_SIZE, Pagination, parsing } from './shared';
import type { DocumentPage, PublicDocument } from './types';
import './documents.css';

export function Documents() {
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
  return <div className="page documents-scope"><header className="doc-heading"><div><p className="eyebrow">你的资料，保留可校验的原文</p><h1>我的资料</h1></div><a href="/">返回我的学习</a></header>
    <section className="doc-panel"><h2>上传学习资料</h2><p className="doc-muted">支持 UTF-8 TXT / Markdown 和含文本的 PDF；每个文件最多 10 MB、20 万字符，PDF 最多 100 页。不自动 OCR，不执行原文 HTML。</p>
      <form onSubmit={upload}><label>选择资料文件<input ref={input} type="file" accept=".txt,.md,.markdown,.pdf" disabled={busy} onChange={e => setFile(e.target.files?.[0])}/></label>
        <div className="doc-actions"><button disabled={!file || busy}>{busy ? '正在上传…' : '上传资料'}</button><button type="button" className="quiet" disabled={loading || busy} onClick={() => setRefresh(n => n + 1)}>刷新资料列表</button></div></form>
      {uploaded && <p role="status">已保存到服务器：<a href={documentPath(uploaded.document_id)}>{uploaded.filename}</a>。可进入原文页查看解析与绑定。</p>}
    </section>
    <DocumentError error={error}/>
    <section className="doc-list" aria-label="资料列表" aria-busy={loading}>
      {loading && <p role="status">正在读取资料…</p>}
      {!loading && !error && page?.total === 0 && <div className="doc-empty"><h2>还没有资料</h2><p>上传后显式绑定到学习目标，再为需要的节点单独绑定。</p></div>}
      {page?.documents.map(document => <article className="doc-panel" key={document.document_id}>
        <h2><a href={documentPath(document.document_id)}>{document.filename}</a></h2><DocumentStatus document={document}/>
        <p className="doc-muted">{(document.size_bytes / 1024).toFixed(1)} KB · 版本 {document.revision} · {document.kind || '未知格式'}</p>
        <a href={documentPath(document.document_id)}>查看原文与绑定 →</a>
      </article>)}
    </section>
    {page && <Pagination offset={offset} total={page.total} label="资料" busy={loading || busy} onChange={setOffset}/>}
  </div>;
}
