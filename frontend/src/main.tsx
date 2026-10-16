import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import dialogPolyfill from 'dialog-polyfill';
import 'dialog-polyfill/dist/dialog-polyfill.css';
import version from './version.txt?raw';

const Markdown = React.lazy(() => import('./Markdown'));

console.log(`ACM Nav ${version.trim()}`);

const encodedPath = name => name.split('/').map(encodeURIComponent).join('/');
const iconUrl = (name, revision) => `${name.startsWith('/icons/') ? encodedPath(name) : `/icons/${encodedPath(name)}`}?v=${revision}`;
const siteAssets = {
  logo: '/icons/site/logo.svg', favicon: '/icons/site/favicon.svg', light: '/icons/site/sun.svg', dark: '/icons/site/moon.svg', fallback: '/icons/services/link.svg',
};
const resourceUrl = url => url?.startsWith('/resources/') || /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(url)
  ? url : `/resources/${url}`;
const serviceIcon = icon => !icon ? '' : icon.startsWith('/icons/') ? icon : `services/${icon}`;
const colorPool = ['#4f96ff', '#9b71ff', '#ff8f5a', '#3dd5a0', '#ef6f9a'];
// 操作和状态提示由前端统一维护，配置只负责站点展示内容。
const text = {
  theme_light: '切换为深色模式',
  theme_dark: '切换为浅色模式',
  close_label: '关闭',
  offline: '连接暂时中断，正在重连…',
  unavailable: '站点配置暂不可用，修正后将自动恢复。',
};
// 公告模块加载或渲染失败时，导航仍然保持可用。
class AnnouncementBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <p role="status">公告渲染失败，请关闭后重新打开。</p> : this.props.children;
  }
}

function Icon({ name, revision, fallback }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [name, revision]);
  const filename = failed || !name ? fallback : name;
  return filename ? <img src={iconUrl(filename, revision)} alt="" onError={() => setFailed(true)} decoding="async" /> : null;
}

function App() {
  const [snapshot, setSnapshot] = useState(() => {
    const initial = document.getElementById('site-snapshot');
    return initial ? JSON.parse(initial.textContent) : null;
  });
  const [offline, setOffline] = useState(false);
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('navigator-theme') === 'dark' ? 'dark' : 'light'; }
    catch { return 'light'; }
  });
  const [selected, setSelected] = useState(null);
  const [infoContent, setInfoContent] = useState('');
  const dialog = useRef(null);
  const closing = useRef(false);
  const closeTimer = useRef(null);
  const trigger = useRef(null);
  const build = useRef(snapshot?.build ?? null);
  const site = snapshot?.site;
  const publicSections = site?.sections.filter(section => section.visibility === 'public') || [];
  const adminSections = site?.sections.filter(section => section.visibility === 'admin') || [];
  const appearance = site?.appearance;
  const revision = snapshot?.revision || '0';
  const active = site?.sections.find(section => section.title === selected?.section)?.items[selected?.item];
  const infoOpen = active?.type === 'info';

  useEffect(() => {
    if (!dialog.current.showModal) dialogPolyfill.registerDialog(dialog.current);
  }, []);

  useEffect(() => {
    const receive = next => {
      if (build.current !== null && build.current !== next.build) location.reload();
      build.current = next.build;
      setSnapshot(next);
      setOffline(false);
    };
    // 部分精简浏览器没有 EventSource，改用轮询保持配置同步。
    if (typeof EventSource === 'undefined') {
      let stopped = false;
      const poll = async () => {
        try {
          const response = await fetch('/api/site');
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const next = await response.json();
          if (!stopped) receive(next);
        } catch { if (!stopped) setOffline(true); }
      };
      poll();
      const timer = setInterval(poll, 10000);
      return () => { stopped = true; clearInterval(timer); };
    }
    const events = new EventSource('/api/events');
    events.onmessage = event => receive(JSON.parse(event.data));
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
      if (dialog.current.open) dialog.current.close();
      document.body.classList.remove('modal-open');
    }
    return () => {
      clearTimeout(closeTimer.current);
      document.body.classList.remove('modal-open');
    };
  }, [infoOpen]);

  useEffect(() => {
    if (!infoOpen) return;
    if (!active?.url) {
      setInfoContent(active?.content || '');
      return;
    }
    let cancelled = false;
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    setInfoContent('');
    fetch(resourceUrl(active.url), controller ? { signal: controller.signal } : {})
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then(content => { if (!cancelled) setInfoContent(content); })
      .catch(error => { if (!cancelled) setInfoContent(`公告加载失败：${error.message}`); });
    return () => { cancelled = true; controller?.abort(); };
  }, [infoOpen, active?.url, active?.content]);

  function finishClose() {
    clearTimeout(closeTimer.current);
    if (dialog.current.open) dialog.current.close();
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

  let colorIndex = 0;
  function card(item, index, section) {
    const accent = colorPool[colorIndex++ % colorPool.length];
    const info = item.type === 'info';
    const description = item.description;
    const Tag = info ? 'button' : 'a';
    return <Tag key={index} style={{ '--card-delay': `${index * 80}ms`, '--accent': accent }} className={`nav-card ${description ? 'has-description' : ''}`}
      {...(info ? { type: 'button' } : {
        href: resourceUrl(item.url),
        ...(item.type === 'resource' ? { download: '' } : { target: '_blank', rel: 'noopener noreferrer' }),
      })}
      aria-label={item.name} aria-haspopup={info ? 'dialog' : undefined}
      onClick={info ? event => { trigger.current = event.currentTarget; setSelected({ section: section.title, item: index }); } : undefined}>
      <span className="card-icon"><Icon name={serviceIcon(item.icon)} revision={revision} fallback={info ? '/icons/services/info.svg' : siteAssets.fallback} /></span>
      <span className="card-text"><span className="card-name">{item.name}</span>
        <span className="card-description">{description}</span></span>
    </Tag>;
  }

  function sectionView(section, index) {
    const headingId = `section-${index}`;
    return <section key={section.title} className="service-section" style={{ '--width': section.width, '--columns': section.columns, '--enter-delay': `${index * 120}ms` }} aria-labelledby={headingId}>
      <div className="section-heading"><h2 id={headingId} title={section.title}>{section.title}</h2></div>
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
            <span className="site-meta">
              <span className="visit-count">访问量：{snapshot.visit_count ?? 0}</span>
              {snapshot.current_ip && <span className="current-ip">{snapshot.current_ip}</span>}
            </span>
          </div>
        </div>
        <button className="theme-toggle" aria-label={text[`theme_${theme}`]} title={text[`theme_${theme}`]}
          onClick={() => { const next = theme === 'light' ? 'dark' : 'light'; setTheme(next); try { localStorage.setItem('navigator-theme', next); } catch {} }}>
          <Icon name={siteAssets[theme]} revision={revision} fallback={siteAssets.fallback} />
        </button>
      </header>
      <main className="page-shell">
        <div className="section-grid">{publicSections.map(sectionView)}</div>
        {adminSections.length > 0 && <div className="section-grid admin-sections">
          {adminSections.map((section, index) => sectionView(section, publicSections.length + index))}
        </div>}
      </main>
    </>}
    {(offline || (!site && snapshot?.stale)) && <p className="connection-note" role="status">{offline ? text.offline : text.unavailable}</p>}
    {/* 原生 dialog 保留焦点约束，内容区可滚动但不显示滚动条。 */}
    <dialog ref={dialog} className="modal-panel" aria-labelledby="modal-title" onCancel={event => { event.preventDefault(); close(); }}
      onAnimationEnd={event => { if (event.target === dialog.current && event.animationName === 'dialog-out' && closing.current) finishClose(); }}
      onClick={event => { if (event.target === dialog.current) { const r = dialog.current.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) close(); } }}>
      <div className="modal-header"><h2 id="modal-title" title={active?.name}>{active?.name}</h2>
        <button className="modal-close" type="button" onClick={close} aria-label={text.close_label} /></div>
      <div className="modal-content" tabIndex={0}><AnnouncementBoundary key={`${selected?.section}-${selected?.item}`}><React.Suspense fallback={<p>正在加载公告…</p>}>{infoOpen && <Markdown key={`${selected?.section}-${selected?.item}-${infoContent}`} content={infoContent} revision={revision} />}</React.Suspense></AnnouncementBoundary></div>
    </dialog>
  </>;
}

createRoot(document.getElementById('root')).render(<App />);
