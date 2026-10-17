import { useRef, useState } from 'react';
import { api, HttpError } from '../api';
import { markSessionDeleted } from '../deletedSessions';
import type { Conversation, Plan } from '../types';

export type Deletion = { kind: 'conversation'; id: string; title: string; goalId?: string }
  | { kind: 'goal'; id: string; title: string; version: number; published: boolean; sessionIds?: string[] };
const receiptKey = 'learngraph:workbench:deletion';

function readReceipt(): Deletion | undefined {
  try { return JSON.parse(localStorage.getItem(receiptKey) || 'null') || undefined; }
  catch { return undefined; }
}
function pathFor(target: Deletion) {
  return `/${target.kind === 'goal' ? 'goals' : 'conversations'}/${encodeURIComponent(target.id)}`;
}
function confirmation(target: Deletion) {
  return target.kind === 'goal'
    ? `${target.published ? '删除图谱' : '放弃目标'}「${target.title}」？\n\n将删除这个主题的图谱、会话、教材、练习、成绩及资料绑定。独立上传的原始资料和其他主题保留。此操作不可撤销；仍有任务执行时不会删除。`
    : `删除会话「${target.title}」？\n\n将删除本条对话及其专属运行记录。节点共享的教材、练习、成绩和原始资料保留。旧版本中未记录归属的独立解释历史仅随整个主题清理。此操作不可撤销；仍有任务执行时不会删除。`;
}

/** A lost DELETE response is resolved by a read, never by an automatic repeat. */
export function useDeletion(onDeleted: (target: Deletion) => void, onRejected: () => void) {
  const [pending, setPending] = useState(readReceipt);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const callbacks = useRef({ onDeleted, onRejected });
  callbacks.current = { onDeleted, onRejected };

  function finish(target: Deletion) {
    localStorage.removeItem(receiptKey);
    setPending(undefined); setChecked(false); setError('');
    callbacks.current.onDeleted(target);
  }
  async function remove(target: Deletion) {
    if (lock.current || (pending && !checked) || !window.confirm(confirmation(target))) return;
    lock.current = true; setBusy(true); setChecked(false); setError('');
    try {
      // Save identity before the destructive request. Mount/refresh only reads it.
      localStorage.setItem(receiptKey, JSON.stringify(target)); setPending(target);
      await api(pathFor(target), target.kind === 'goal' ? { expected_version: target.version } : {}, 'DELETE');
      finish(target);
    } catch (e) {
      if (e instanceof HttpError && e.status === 404) finish(target);
      else if (e instanceof HttpError && e.status >= 400 && e.status < 500) {
        localStorage.removeItem(receiptKey); setPending(undefined);
        setError(`未能删除「${target.title}」：${e.message}。记录已保留；如有任务请先等待退出，或刷新后重新确认当前版本。`);
        callbacks.current.onRejected();
      } else setError(`「${target.title}」的删除结果尚未确认。请查询删除结果；不会自动重发删除或模型请求。`);
    } finally { lock.current = false; setBusy(false); }
  }
  async function query() {
    if (!pending || lock.current) return;
    const target = pending;
    lock.current = true; setBusy(true); setChecked(false); setError('');
    try {
      const value = await api<Plan | Conversation>(pathFor(target));
      const current: Deletion = target.kind === 'goal' ? {
        ...target, title: (value as Plan).goal.title, version: (value as Plan).version,
        published: (value as Plan).graph?.status === 'published',
      } : { ...target, title: (value as Conversation).title };
      localStorage.setItem(receiptKey, JSON.stringify(current)); setPending(current); setChecked(true);
    } catch (e) {
      if (e instanceof HttpError && e.status === 404) finish(target);
      else setError('暂时无法查询删除结果，请稍后再查询。不会根据查询失败猜测已经删除，也不会重新发送删除请求。');
    } finally { lock.current = false; setBusy(false); }
  }
  return { pending, checked, busy, error, remove, query };
}

/** Remove browser commands/drafts only after server deletion is acknowledged. */
export function forgetDeleted(target: Deletion, conversations: Conversation[]) {
  const keys = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i)!).filter(Boolean);
  const sessions = new Set(target.kind === 'goal'
    ? [...(target.sessionIds || []), ...conversations.filter(value => value.goal_id === target.id).map(value => value.session_id), `planning:${target.id}`]
    : [target.id]);
  const scoped = (key: string, id: string) => key.endsWith(`:${id}`) || key.includes(`:${id}:`);
  // Child sessions are random UUIDs. Their saved scope, not a UUID substring,
  // establishes ownership; shared node state must survive a conversation delete.
  for (const key of keys.filter(value => value.startsWith('learngraph:session:'))) {
    const value = localStorage.getItem(key);
    if (value && ((target.kind === 'goal' && scoped(key, target.id))
      || (target.kind === 'conversation' && key.endsWith(`:conversation:${target.id}`)))) sessions.add(value);
  }
  sessions.forEach(markSessionDeleted);
  const packages = new Set<string>();
  for (const key of keys) {
    if (!key.startsWith('learngraph:')) continue;
    let remove = (target.kind === 'goal' && scoped(key, target.id)) || [...sessions].some(id => scoped(key, id));
    if (key.startsWith('learngraph:session:') && sessions.has(localStorage.getItem(key) || '')) remove = true;
    if (remove) {
      if (target.kind === 'goal' && key.startsWith(`learngraph:lesson:${target.id}:`)) packages.add(key.split(':')[3]);
      localStorage.removeItem(key);
    }
  }
  for (const key of keys.filter(value => value.startsWith('learngraph:lesson-event:'))) {
    try {
      if (packages.has(JSON.parse(localStorage.getItem(key) || 'null')?.packageId)) localStorage.removeItem(key);
    } catch { /* Unrelated malformed cache is not part of this deletion. */ }
  }
}
