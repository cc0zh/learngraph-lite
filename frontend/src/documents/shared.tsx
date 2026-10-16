import type { ReactNode } from 'react';
import { navigateWorkbench } from '../workbench/navigation';
import type { PublicDocument } from './types';

export function DocumentLink({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} onClick={event => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigateWorkbench(href);
  }}>{children}</a>;
}

export const PAGE_SIZE = 50;
export const parsing = (document: PublicDocument) => ['uploaded', 'parsing'].includes(document.status);
const labels: Record<PublicDocument['status'], string> = {
  uploaded: '已上传，等待解析', parsing: '正在解析', ready: '解析完成', failed: '解析失败', unsupported: '不支持的资料',
};
const reasons: Record<string, string> = {
  unsupported_format: '文件格式不支持，请改用 TXT、Markdown 或含文本的 PDF。',
  invalid_utf8: '文本不是 UTF-8 编码，请转换编码后重新上传。',
  needs_ocr: 'PDF 中没有可提取文字。扫描件需要先在本地完成 OCR。',
  encrypted_pdf: '加密 PDF 无法解析，请上传已解密的文件。',
  invalid_pdf: 'PDF 文件无法读取，请检查文件是否完整。',
  empty_document: '文件中没有可读取的文字。',
  unreadable_text: '文件包含无法读取的文本，请转换为 UTF-8 纯文本。',
  text_limit_exceeded: '提取文本超过 20 万字符，请拆分文件。',
  page_limit_exceeded: 'PDF 超过 100 页，请拆分文件。',
  parse_timeout: '解析超过时间限制，请缩小文件后重试。',
  interrupted: '上次解析被中断。可显式重新解析。',
  parse_failed: '解析失败，请检查文件后重试。',
};
export function DocumentStatus({ document }: { document: PublicDocument }) {
  return <div className="doc-status" role="status"><span className={`doc-badge doc-${document.status}`}>{labels[document.status]}</span>
    {document.reason && <p>{reasons[document.reason] || '解析未完成，请检查文件后显式重试。'} <small>原因：{document.reason}</small></p>}
  </div>;
}
export function DocumentError({ error }: { error: string }) { return error ? <p className="doc-error" role="alert">{error}</p> : null; }
export function Pagination({ offset, total, label, busy, onChange }: {
  offset: number; total: number; label: string; busy?: boolean; onChange: (offset: number) => void;
}) {
  return <nav className="doc-actions doc-pagination" aria-label={`${label}分页`}>
    <button type="button" className="quiet" disabled={busy || offset === 0} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}>上一页{label}</button>
    <span>{total ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} / ${total}` : '0 条'}</span>
    <button type="button" className="quiet" disabled={busy || offset + PAGE_SIZE >= total} onClick={() => onChange(offset + PAGE_SIZE)}>下一页{label}</button>
  </nav>;
}
