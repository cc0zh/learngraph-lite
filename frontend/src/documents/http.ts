import { HttpError } from '../api';

// Only the local API is allowed. FormData must retain the browser's multipart boundary.
export async function documentRequest<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const normalized = path.startsWith('/api/') ? path : `/api${path}`;
  if (!normalized.startsWith('/api/') || normalized.includes('://') || normalized.startsWith('//')) throw new Error('资料请求必须使用本地 API。');
  const multipart = options.body instanceof FormData;
  const response = await fetch(normalized, {
    method: options.method || 'GET', signal: options.signal,
    ...(options.body === undefined ? {} : {
      headers: multipart ? undefined : { 'Content-Type': 'application/json' },
      body: multipart ? options.body as FormData : JSON.stringify(options.body),
    }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => undefined);
    throw new HttpError(payload?.error?.message || `请求失败（${response.status}）`, response.status);
  }
  return await response.json() as T;
}

export function documentError(error: unknown): string {
  if (error instanceof HttpError) {
    if (error.status === 413) return '文件超过 10 MB，请缩小文件后重新选择。';
    if (error.status === 409) return '409 · 当前资料、绑定或产物版本已变化，原文校验降级为不可用。请刷新资料与产物后再试。';
    if (error.status === 404) return '资料或来源不存在（404），可能已被删除。';
    if (error.status === 429) return '解析队列已满，请稍后再试。';
    return `请求失败（${error.status}）：${error.message}`;
  }
  return '连接失败，未确认操作结果。请先刷新查询服务器状态，再决定是否重新操作。';
}

export const documentPath = (id: string) => `/documents/${encodeURIComponent(id)}`;
export function chunkLink(documentId: string, chunkId: string, goalId?: string, nodeId?: string) {
  const query = new URLSearchParams({ chunk: chunkId });
  if (goalId) query.set('goal', goalId);
  if (nodeId) query.set('node', nodeId);
  return `${documentPath(documentId)}?${query}`;
}
