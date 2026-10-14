import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api } from './api';
import { ErrorBox } from './components';
import { Home } from './pages/Home';
import { Planning } from './pages/Planning';
import { Learning } from './pages/Learning';
import { Documents, DocumentDetail } from './documents';
import './styles.css';

function App() {
  const [model, setModel] = useState<{mode: string; configured: boolean}>();
  const [error, setError] = useState('');
  useEffect(() => { api<{mode: string; configured: boolean}>('/model/status').then(setModel).catch(e => setError(String(e))); }, []);
  const route = location.pathname.match(/^\/goals\/([^/]+)\/(plan|learn)\/?$/);
  const documentRoute = location.pathname.match(/^\/documents\/([^/]+)\/?$/);
  return <><a className="skip" href="#main">跳到主要内容</a><header className="topbar"><a className="brand" href="/"><span className="logo">L</span>LearnGraph <small>LITE</small></a><nav><a href="/">我的学习</a><a href="/documents">我的资料</a><span className={`model-badge ${model?.mode === 'real' ? 'real' : ''}`}>{model ? model.mode === 'fixture' ? 'Fixture · 示例模式' : model.configured ? 'Real · 模型已配置' : 'Real · 未配置' : '正在检查模型'}</span></nav></header>
    <main id="main"><ErrorBox error={error}/>{route ? route[2] === 'plan' ? <Planning goalId={decodeURIComponent(route[1])}/> : <Learning goalId={decodeURIComponent(route[1])}/> : documentRoute ? <DocumentDetail documentId={decodeURIComponent(documentRoute[1])}/> : location.pathname === '/documents' ? <Documents/> : location.pathname === '/' ? <Home/> : <p>页面不存在。<a href="/">返回首页</a></p>}</main><footer>LearnGraph Lite · 用路线组织学习，用练习留下证据</footer></>;
}
createRoot(document.getElementById('root')!).render(<App/>);
