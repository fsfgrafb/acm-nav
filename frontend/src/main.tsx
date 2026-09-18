import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { createLowlight } from 'lowlight';
import cpp from 'highlight.js/lib/languages/cpp';
import c from 'highlight.js/lib/languages/c';
import python from 'highlight.js/lib/languages/python';
import bash from 'highlight.js/lib/languages/bash';
import javascript from 'highlight.js/lib/languages/javascript';
import typescript from 'highlight.js/lib/languages/typescript';
import json from 'highlight.js/lib/languages/json';
import css from 'highlight.js/lib/languages/css';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';
import ini from 'highlight.js/lib/languages/ini';

const encodedPath = name => name.split('/').map(encodeURIComponent).join('/');
const iconUrl = (name, revision) => `/static/icons/${encodedPath(name)}?v=${revision}`;
const siteAssets = {
  logo: 'site/logo.svg', favicon: 'site/favicon.svg', light: 'site/sun.svg', dark: 'site/moon.svg', fallback: 'services/link.svg',
};
// 操作和状态提示由前端统一维护，配置只负责站点展示内容。
const text = {
  theme_light: '切换为深色模式',
  theme_dark: '切换为浅色模式',
  close: '×',
  close_label: '关闭',
  copy: '复制',
  copied: '已复制',
  copy_failed: '复制失败，请手动选择',
  loading: '正在加载…',
  offline: '连接暂时中断，正在重连…',
  unavailable: '站点配置暂不可用，修正后将自动恢复。',
};
const RevisionContext = React.createContext('0');
const highlighter = createLowlight({ c, cpp, python, bash, javascript, typescript, json, css, xml, yaml, ini });

function renderTokens(nodes) {
  return nodes.map((node, index) => node.type === 'text' ? node.value :
    <span key={index} className={node.properties?.className?.join(' ')}>{renderTokens(node.children)}</span>);
}

function HighlightedCode({ className, children }) {
  const source = String(children ?? '');
  const language = /language-([^\s]+)/.exec(className || '')?.[1]?.toLowerCase();
  const tokens = React.useMemo(() => !language || !highlighter.registered(language)
    ? source : renderTokens(highlighter.highlight(language, source).children), [language, source]);
  return <code className={className}>{tokens}</code>;
}

function MarkdownImage({ src, ...props }) {
  const revision = React.useContext(RevisionContext);
  if (src) {
    try {
      const url = new URL(src, location.origin);
      if (url.origin === location.origin && url.pathname.startsWith('/static/icons/')) {
        url.searchParams.set('v', revision);
        src = url.pathname + url.search + url.hash;
      }
    } catch {} // 无效图片地址不应中断整张公告。
  }
  return <img {...props} src={src} />;
}

function CodeBlock({ children }) {
  const pre = useRef(null);
  const resetTimer = useRef(null);
  const [message, setMessage] = useState('copy');
  useEffect(() => {
    setMessage('copy');
    return () => clearTimeout(resetTimer.current);
  }, [children]);
  async function copy() {
    const source = pre.current.textContent;
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(source);
      else {
        const area = document.createElement('textarea');
        area.value = source;
        area.style.cssText = 'position:fixed;opacity:0';
        pre.current.closest('dialog').append(area);
        const focused = document.activeElement;
        area.select();
        const ok = document.execCommand('copy');
        area.remove();
        focused?.focus();
        if (!ok) throw new Error('copy failed');
      }
      setMessage('copied');
      clearTimeout(resetTimer.current);
      resetTimer.current = setTimeout(() => setMessage('copy'), 800);
    } catch {
      clearTimeout(resetTimer.current);
      setMessage('copy_failed');
    }
  }
  return <div className="code-block"><pre ref={pre}>{children}</pre>
    <button className="code-copy" onClick={copy} aria-live="polite">{text[message]}</button></div>;
}

function Markdown({ content, revision }) {
  return <RevisionContext.Provider value={revision}><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    pre: CodeBlock, code: HighlightedCode, img: MarkdownImage,
    a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  }}>{content}</ReactMarkdown></RevisionContext.Provider>;
}

function Icon({ name, revision, fallback }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [name, revision]);
  const filename = failed || !name ? fallback : name;
  return filename ? <img src={iconUrl(filename, revision)} alt="" onError={() => setFailed(true)} decoding="async" /> : null;
}

function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [offline, setOffline] = useState(false);
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('navigator-theme') === 'dark' ? 'dark' : 'light'; }
    catch { return 'light'; }
  });
  const [selected, setSelected] = useState(null);
  const dialog = useRef(null);
  const closing = useRef(false);
  const closeTimer = useRef(null);
  const trigger = useRef(null);
  const build = useRef(null);
  const site = snapshot?.site;
  const appearance = site?.appearance;
  const revision = snapshot?.revision || '0';
  const active = site?.sections.find(section => section.title === selected?.section)?.items[selected?.item];
  const infoOpen = active?.type === 'info';

  useEffect(() => {
    const events = new EventSource('/api/events');
    events.onmessage = event => {
      const next = JSON.parse(event.data);
      if (build.current !== null && build.current !== next.build) location.reload();
      build.current = next.build;
      setSnapshot(next);
      setOffline(false);
    };
    events.onerror = () => setOffline(true);
    return () => events.close();
  }, []);

  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    if (!appearance) return;
    document.title = appearance.title;
    document.querySelector('meta[name="description"]').content = appearance.description;
    document.querySelector('link[rel="icon"]').href = iconUrl(siteAssets.favicon, revision);
  }, [revision]);

  useEffect(() => {
    if (infoOpen) {
      if (!dialog.current.open) dialog.current.showModal();
      document.body.classList.add('modal-open');
    } else {
      clearTimeout(closeTimer.current);
      closing.current = false;
      dialog.current.classList.remove('is-closing');
      dialog.current.close();
      document.body.classList.remove('modal-open');
    }
    return () => {
      clearTimeout(closeTimer.current);
      document.body.classList.remove('modal-open');
    };
  }, [infoOpen]);

  function finishClose() {
    clearTimeout(closeTimer.current);
    dialog.current.close();
    dialog.current.classList.remove('is-closing');
    closing.current = false;
    setSelected(null);
    trigger.current?.focus();
  }

  function close() {
    if (!dialog.current.open || closing.current) return;
    closing.current = true;
    // 退场动画结束前保留内容、遮罩和焦点约束。
    dialog.current.classList.add('is-closing');
    const duration = parseFloat(getComputedStyle(dialog.current).animationDuration) || 0;
    // 自定义样式取消动画时，也能可靠关闭。
    closeTimer.current = setTimeout(finishClose, duration * 1000 + 50);
  }

  function card(item, index, section) {
    const info = item.type === 'info';
    const issue = item.error || '';
    const description = item.error || item.description;
    const Tag = info ? 'button' : 'a';
    return <Tag key={index} style={{ '--card-delay': `${Math.min(index, 6) * 45}ms` }} className={`nav-card accent-${index % 5 + 1} ${description ? 'has-description' : ''}`}
      {...(Tag === 'a' ? {
        href: item.url, target: '_blank', rel: 'noopener noreferrer',
      } : { type: 'button' })}
      aria-label={issue ? `${item.name} (${issue})` : item.name} aria-haspopup={info ? 'dialog' : undefined}
      onClick={info ? event => { trigger.current = event.currentTarget; setSelected({ section: section.title, item: index }); } : undefined}>
      <span className="card-icon"><Icon name={`services/${item.icon}`} revision={revision} fallback={siteAssets.fallback} /></span>
      <span className="card-text"><span className="card-name">{item.name}{issue && ` · ${issue}`}</span>
        <span className="card-description">{description}</span></span>
    </Tag>;
  }

  function sectionView(section, index) {
    const headingId = `section-${index}`;
    return <section key={section.title} className="service-section" style={{ '--width': section.width, '--columns': section.columns, '--enter-delay': `${Math.min(index, 6) * 70}ms` }} aria-labelledby={headingId}>
      <div className="section-heading"><h2 id={headingId}>{section.title}</h2></div>
      <div className="card-list">{section.items.map((item, index) => card(item, index, section))}</div>
    </section>;
  }

  return <>
    <div className="ambient ambient-one" aria-hidden="true" /><div className="ambient ambient-two" aria-hidden="true" />
    {site && <>
      <header className="site-header page-shell">
        <div className="brand">
          <span className="brand-mark"><Icon name={siteAssets.logo} revision={revision} fallback={siteAssets.fallback} /></span>
          <div className="brand-copy"><span className="brand-kicker">{appearance.kicker}</span><h1>{appearance.title}</h1>
            {snapshot.current_ip && <span className="current-ip">{snapshot.current_ip}</span>}
          </div>
        </div>
        <button className="theme-toggle" aria-label={text[`theme_${theme}`]} title={text[`theme_${theme}`]}
          onClick={() => { const next = theme === 'light' ? 'dark' : 'light'; setTheme(next); try { localStorage.setItem('navigator-theme', next); } catch {} }}>
          <Icon name={siteAssets[theme]} revision={revision} fallback={siteAssets.fallback} />
        </button>
      </header>
      <main className="page-shell">
        <div className="section-grid">{site.sections.filter(section => section.visibility === 'public').map(sectionView)}</div>
        {site.sections.some(section => section.visibility === 'admin') && <div className="section-grid admin-sections">
          {site.sections.filter(section => section.visibility === 'admin').map(sectionView)}
        </div>}
      </main>
    </>}
    {(!site || offline) && <p className="connection-note" role="status">{offline ? text.offline : snapshot?.stale ? text.unavailable : text.loading}</p>}
    {/* 原生 dialog 保留焦点约束，内容区可滚动但不显示滚动条。 */}
    <dialog ref={dialog} className="modal-panel" aria-labelledby="modal-title" onCancel={event => { event.preventDefault(); close(); }}
      onAnimationEnd={event => { if (event.target === dialog.current && event.animationName === 'dialog-out' && closing.current) finishClose(); }}
      onClick={event => { if (event.target === dialog.current) { const r = dialog.current.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) close(); } }}>
      <div className="modal-header"><h2 id="modal-title">{active?.name}</h2>
        <button className="modal-close" type="button" onClick={close} aria-label={text.close_label}>{text.close}</button></div>
      <div className="modal-content" tabIndex={0}><Markdown key={`${selected?.section}-${selected?.item}`} content={active?.content || ''} revision={revision} /></div>
    </dialog>
  </>;
}

createRoot(document.getElementById('root')).render(<App />);
