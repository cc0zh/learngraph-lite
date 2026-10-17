import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api } from './api';
import { ErrorBox } from './components';
import { Workbench } from './workbench/Workbench';
import { canonicalWorkbenchURL, navigateWorkbench, workbenchHref } from './workbench/navigation';
import './styles.css';

const canonical = canonicalWorkbenchURL();
if (canonical) window.history.replaceState({}, '', canonical);

function App() {
  const [model, setModel] = useState<{mode: string; configured: boolean}>();
  const [error, setError] = useState('');
  const [, setLocation] = useState(0);
  useEffect(() => { api<{mode: string; configured: boolean}>('/model/status').then(setModel).catch(e => setError(String(e))); }, []);
  useEffect(() => {
    const update = () => setLocation(value => value + 1);
    const links = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const link = (event.target as Element).closest<HTMLAnchorElement>('a[href]');
      if (!link || link.target || link.hasAttribute('download') || link.getAttribute('href')?.startsWith('#')) return;
      const url = new URL(link.href);
      if (url.origin === location.origin && url.pathname === '/') { event.preventDefault(); navigateWorkbench(url.href); }
    };
    window.addEventListener('popstate', update); document.addEventListener('click', links);
    return () => { window.removeEventListener('popstate', update); document.removeEventListener('click', links); };
  }, []);
  const learning = workbenchHref({ tool: undefined, document: undefined, chunk: undefined, source_goal: undefined, source_node: undefined });
  const documentTool = ['documents', 'document'].includes(new URLSearchParams(location.search).get('tool') || '');
  const modelLabel = model ? model.mode === 'fixture' ? 'Fixture' : 'Real' : '检查中';
  const modelDetail = model ? model.mode === 'fixture' ? '示例模式' : model.configured ? '模型已配置' : '未配置' : '正在检查模型';
  return <><a className="skip" href="#main">跳到主要内容</a><header className="topbar">
    <a className="brand" href={learning} aria-label="LearnGraph Lite · 我的学习">
      <svg className="brand-mark" viewBox="0 0 36 36" fill="none" aria-hidden="true" focusable="false">
        <path d="m8 26 10-16 11 13" stroke="currentColor" strokeWidth="2"/>
        <circle cx="8" cy="26" r="4" fill="currentColor"/>
        <circle cx="18" cy="10" r="6" fill="currentColor"/>
        <circle cx="29" cy="23" r="5" className="brand-node"/>
      </svg>
      <span className="brand-name">LearnGraph</span><small>Lite</small>
    </a>
    <nav aria-label="主要导航">
      <a href={learning} aria-current={!documentTool ? 'page' : undefined}>我的学习</a>
      <a href={workbenchHref({ tool: 'documents', mode: undefined, document: undefined, chunk: undefined })} aria-current={documentTool ? 'page' : undefined}>我的资料</a>
      <span className={`model-badge ${model?.mode === 'real' ? 'real' : ''}`} role="status" aria-label={`${modelLabel} · ${modelDetail}`} title={`${modelLabel} · ${modelDetail}`}>
        <span className="model-label">{modelLabel}</span><span className="model-detail"> · {modelDetail}</span>
      </span>
    </nav>
  </header>
    <main id="main"><ErrorBox error={error}/>{location.pathname === '/' ? <Workbench/> : <p>页面不存在。<a href="/">返回工作台</a></p>}</main></>;
}
createRoot(document.getElementById('root')!).render(<App/>);
