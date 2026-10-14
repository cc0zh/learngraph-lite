export class HttpError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await fetch(`/api${path}`, body === undefined ? {} : {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => undefined);
    throw new HttpError(data?.error?.message || `请求失败（${response.status}）`, response.status);
  }
  return await response.json() as T;
}

export function sessionFor(scope: string, legacyId?: string) {
  const key = `learngraph:session:${scope}`;
  let id = localStorage.getItem(key);
  if (!id) { id = legacyId || crypto.randomUUID(); localStorage.setItem(key, id); }
  return id;
}
export const terminal = (status: string) => !['queued', 'running'].includes(status);
