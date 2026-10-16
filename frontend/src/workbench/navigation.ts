/** UI locations are independent of API paths. Opening a tool preserves chat scope. */
export function workbenchHref(patch: Record<string, string | undefined>, source = window.location.search): string {
  const params = new URLSearchParams(source.startsWith('/') ? new URL(source, window.location.origin).search : source);
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined || value === '') params.delete(key);
    else params.set(key, value);
  }
  return `/${params.size ? `?${params}` : ''}`;
}

export function workbenchHistoryIndex(): number {
  const index = window.history.state?.learngraphIndex;
  if (typeof index === 'number') return index;
  window.history.replaceState({ ...window.history.state, learngraphIndex: 0 }, '');
  return 0;
}

export function navigateWorkbench(href: string): boolean {
  const target = new URL(href, window.location.origin);
  if (target.origin !== window.location.origin || target.pathname !== '/') throw new Error('工作台导航必须使用本地根路径。');
  if (target.href === window.location.href) return true;
  if (!window.dispatchEvent(new CustomEvent('learngraph:before-navigate', { cancelable: true, detail: target.href }))) return false;
  window.history.pushState({ learngraphIndex: workbenchHistoryIndex() + 1 }, '', target.pathname + target.search + target.hash);
  window.dispatchEvent(new PopStateEvent('popstate'));
  return true;
}

/** Old bookmarks locate saved data only: no session creation or model request. */
export function canonicalWorkbenchURL(): string | undefined {
  const params = new URLSearchParams(window.location.search);
  const path = window.location.pathname;
  const goal = path.match(/^\/goals\/([^/]+)\/(plan|learn)\/?$/);
  const document = path.match(/^\/documents\/([^/]+)\/?$/);
  if (goal) {
    let id: string;
    try { id = decodeURIComponent(goal[1]); } catch { return undefined; }
    const next = new URLSearchParams({ goal: id });
    if (goal[2] === 'plan') {
      next.set('session', `planning:${id}`);
      if (params.get('mode') === 'manual') next.set('tool', 'graph');
    } else {
      let node = params.get('node');
      try { node ||= localStorage.getItem(`learngraph:node:${id}`); } catch { /* Browsing still works without storage. */ }
      if (node) {
        const legacy = `learn:${id}:${node}`;
        let session: string | null = null;
        try { session = localStorage.getItem(`learngraph:session:${legacy}`); } catch { /* Never create a replacement. */ }
        if (session || legacy.length <= 128) next.set('session', session || legacy);
      }
    }
    return `/?${next}`;
  }
  if (path === '/documents' || document) {
    params.set('tool', document ? 'document' : 'documents');
    if (document) {
      try { params.set('document', decodeURIComponent(document[1])); } catch { return undefined; }
    }
    if (params.has('goal')) params.set('source_goal', params.get('goal')!);
    if (params.has('node')) { params.set('source_node', params.get('node')!); params.delete('node'); }
    return `/?${params}`;
  }
  if (path === '/library') return '/';
  if (path === '/' && params.get('mode') === 'manual') return workbenchHref({ mode: 'goal' });
  return undefined;
}
