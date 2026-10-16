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
  return <><a className="skip" href="#main">跳到主要内容</a><header className="topbar"><a className="brand" href={learning}><span className="logo">L</span>LearnGraph <small>LITE</small></a><nav><a href={learning}>我的学习</a><a href={workbenchHref({ tool: 'documents', mode: undefined, document: undefined, chunk: undefined })}>我的资料</a><span className={`model-badge ${model?.mode === 'real' ? 'real' : ''}`}>{model ? model.mode === 'fixture' ? 'Fixture · 示例模式' : model.configured ? 'Real · 模型已配置' : 'Real · 未配置' : '正在检查模型'}</span></nav></header>
    <main id="main"><ErrorBox error={error}/>{location.pathname === '/' ? <Workbench/> : <p>页面不存在。<a href="/">返回工作台</a></p>}</main></>;
}
createRoot(document.getElementById('root')!).render(<App/>);
