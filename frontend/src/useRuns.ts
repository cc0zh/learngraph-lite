import { useCallback, useEffect, useRef, useState } from 'react';
import { api, HttpError, terminal } from './api';
import type { Run } from './types';

export interface Command { path: string; body: Record<string, unknown> }
export function useRuns(session: string, onComplete: () => void) {
  const key = `learngraph:command:${session}`;
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<Command | undefined>(() => {
    const raw = localStorage.getItem(`${key}:pending`);
    return raw ? JSON.parse(raw) as Command : undefined;
  });
  const [pendingChecked, setPendingChecked] = useState(false);
  const pendingRef = useRef(pending);
  const sendingRef = useRef(false);
  const queryVersion = useRef(0);
  const complete = useRef(onComplete);
  complete.current = onComplete;
  const notified = useRef(new Set<string>());
  const notifyTerminal = useCallback((records: Pick<Run, 'run_id' | 'status'>[]) => {
    const fresh = records.filter(run => terminal(run.status) && !notified.current.has(run.run_id));
    fresh.forEach(run => notified.current.add(run.run_id));
    if (fresh.length) complete.current();
  }, []);
  const active = runs.find(r => !terminal(r.status));
  const refresh = useCallback(async () => {
    const version = ++queryVersion.current;
    setPendingChecked(false);
    try {
      const history = await api<Run[]>(`/sessions/${session}/runs`);
      if (version !== queryVersion.current) return;
      setRuns(history); setError(''); setPendingChecked(!!pendingRef.current);
      notifyTerminal(history);
      // PublicRun has no request_id. Never guess which run acknowledges a pending
      // command from its text; an explicit same-ID POST is the idempotent lookup.
    } catch (e) { if (version === queryVersion.current) setError(String(e)); }
  }, [session, notifyTerminal]);
  useEffect(() => { void refresh(); }, [refresh]);
  const activeId = active?.run_id;
  useEffect(() => {
    if (!activeId) return;
    const source = new EventSource(`/api/runs/${activeId}/events`);
    const update = (patch: Partial<Run>) => setRuns(list => list.map(r => r.run_id === activeId ? { ...r, ...patch } : r));
    const snapshot = (event: MessageEvent) => {
      const run = JSON.parse(event.data).payload as Run;
      if (!pendingRef.current) setError('');
      update(run);
      if (terminal(run.status)) { source.close(); notifyTerminal([run]); }
    };
    source.addEventListener('run.snapshot', snapshot);
    source.addEventListener('message.delta', (event) => {
      const text = JSON.parse((event as MessageEvent).data).payload.text;
      setRuns(list => list.map(r => r.run_id === activeId ? { ...r, partial_text: r.partial_text + text } : r));
    });
    for (const type of ['tool.started', 'tool.finished']) source.addEventListener(type, event => {
      const item = JSON.parse((event as MessageEvent).data).payload;
      setRuns(list => list.map(r => r.run_id === activeId ? { ...r, tool_activity: { ...r.tool_activity,
        [item.call_id]: { ...r.tool_activity[item.call_id], ...item, status: item.status || 'running' } } } : r));
    });
    source.addEventListener('run.started', () => update({ status: 'running' }));
    for (const status of ['completed', 'failed', 'cancelled', 'budget_exceeded', 'interrupted']) source.addEventListener(`run.${status}`, async event => {
      source.close();
      // Terminal SSE already carries saved public text/output/usage. A failed GET
      // must not leave the browser locked in running or omit artifact refresh.
      const payload = JSON.parse((event as MessageEvent).data).payload as Partial<Run>;
      update({ ...payload, status }); notifyTerminal([{ run_id: activeId, status }]);
      try { update(await api<Run>(`/runs/${activeId}`)); }
      catch (e) { setError(`终态已收到，详细结果暂未读取：${String(e)}。可查询运行状态。`); }
    });
    source.onerror = () => { setError('连接暂时中断，正在重连；可查询运行状态。'); };
    return () => source.close();
  }, [activeId]);

  async function submit(command: Command) {
    if (sendingRef.current) return;
    sendingRef.current = true;
    ++queryVersion.current;
    pendingRef.current = command; setPending(command); setPendingChecked(false);
    setSending(true); setError(''); localStorage.setItem(`${key}:pending`, JSON.stringify(command));
    try {
      const run = await api<Run>(command.path, command.body);
      ++queryVersion.current;
      localStorage.setItem(`${key}:${run.run_id}`, JSON.stringify(command));
      localStorage.removeItem(`${key}:pending`); pendingRef.current = undefined; setPending(undefined); setPendingChecked(false);
      setRuns(list => list.some(r => r.run_id === run.run_id) ? list.map(r => r.run_id === run.run_id ? run : r) : [...list, run]);
      if (terminal(run.status)) notifyTerminal([run]);
      return true;
    } catch (e) {
      if (e instanceof HttpError && e.status >= 400 && e.status < 500) {
        localStorage.removeItem(`${key}:pending`); pendingRef.current = undefined; setPending(undefined); setPendingChecked(false);
        await refresh(); setError(`请求被拒绝：${e.message}。请检查输入后重新发起。`);
        return false;
      }
      await refresh(); setError(`请求未确认：${String(e)}。输入已保留，请查询状态后显式重发同一请求。`);
    }
    finally { sendingRef.current = false; setSending(false); }
  }
  async function execute(command: Command) {
    if (pendingRef.current || sendingRef.current) return;
    return await submit(command);
  }
  async function recover() {
    if (!pendingRef.current || !pendingChecked) return;
    return await submit(pendingRef.current);
  }
  async function retry(runId = runs.at(-1)?.run_id) {
    if (pendingRef.current || sendingRef.current) return;
    const run = runs.find(r => r.run_id === runId);
    if (!run || !terminal(run.status) || run.status === 'completed') return;
    const raw = localStorage.getItem(`${key}:${run.run_id}`);
    if (!raw) { setError('本浏览器没有保存该任务输入，请重新发起任务。'); return; }
    const command = JSON.parse(raw) as Command;
    await execute({ ...command, body: { ...command.body, request_id: crypto.randomUUID(), retry_of_run_id: run.run_id } });
  }
  async function stop() {
    if (!active) return;
    try { await api(`/runs/${active.run_id}/cancel`, {}); await refresh(); complete.current(); }
    catch (e) { setError(String(e)); }
  }
  return { runs, error, active, pending, pendingChecked, sending, busy: sending || !!active || !!pending, execute, recover, retry, stop, refresh };
}
