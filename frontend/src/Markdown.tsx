import React, { useEffect, useRef, useState } from 'react';
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

const text = { copy: '复制', copied: '已复制', copy_failed: '复制失败，请手动选择' };
const RevisionContext = React.createContext('0');
const CodeBlockContext = React.createContext(false);
const highlighter = createLowlight({ c, cpp, python, bash, javascript, typescript, json, css, xml, yaml, ini });

function flattenTokens(nodes, classes = []) {
  return nodes.flatMap(node => {
    if (node.type === 'text') return [{ value: node.value, classes }];
    return flattenTokens(node.children, [...classes, ...(node.properties?.className || [])]);
  });
}

function highlightedLines(source, language) {
  const tokens = !language || !highlighter.registered(language)
    ? [{ value: source, classes: [] }]
    : flattenTokens(highlighter.highlight(language, source).children);
  const lines = [[]];
  tokens.forEach(({ value, classes }) => value.split(/(\r?\n)/).forEach(part => {
    if (/^\r?\n$/.test(part)) lines.push([]);
    else if (part) lines[lines.length - 1].push({ value: part, classes });
  }));
  return lines;
}

function renderTokens(nodes) {
  return nodes.map((node, index) => node.type === 'text' ? node.value :
    <span key={index} className={node.properties?.className?.join(' ')}>{renderTokens(node.children)}</span>);
}

function HighlightedCode({ className, children }) {
  const isBlock = React.useContext(CodeBlockContext);
  const source = String(children ?? '');
  const language = /language-([^\s]+)/.exec(className || '')?.[1]?.toLowerCase();
  const tokens = React.useMemo(() => !language || !highlighter.registered(language)
    ? source : renderTokens(highlighter.highlight(language, source).children), [language, source]);
  const lines = React.useMemo(() => isBlock ? highlightedLines(source, language) : null, [isBlock, language, source]);
  if (lines) return <code className={className}>{lines.map((line, lineIndex) =>
    <span className="code-line" key={lineIndex}><span className="code-line-content">{line.map(({ value, classes }, tokenIndex) =>
      classes.length ? <span key={tokenIndex} className={classes.join(' ')}>{value}</span> : value)}</span></span>)}</code>;
  return <code className={className}>{tokens}</code>;
}

function MarkdownImage({ src, ...props }) {
  const revision = React.useContext(RevisionContext);
  if (src) {
    try {
      // 公告内的 ./assets/ 路径对应 static/resources/assets/。
      if (src.startsWith('./assets/')) src = `/resources/assets/${src.slice('./assets/'.length)}`;
      const url = new URL(src, location.origin);
      const zoom = url.searchParams.get('_acmZoom');
      if (zoom) {
        url.searchParams.delete('_acmZoom');
        src = url.pathname + url.search + url.hash;
        props.style = { ...props.style, zoom };
      }
      if (url.origin === location.origin && url.pathname.startsWith('/icons/')) {
        url.searchParams.set('v', revision);
        src = url.pathname + url.search + url.hash;
      }
    } catch {} // 无效图片地址不应中断整张公告。
  }
  return <img {...props} src={src} />;
}

function MarkdownLink({ href, ...props }) {
  // 公告文件的相对链接以 static/resources/ 为基准。
  if (href?.startsWith('./')) href = `/resources/${href.slice('./'.length)}`;
  return <a {...props} href={href} target="_blank" rel="noopener noreferrer" />;
}

function normalizeAnnouncementImages(content) {
  // 仅转换公告中约定的 <img src="./assets/..."> 写法，避免启用整段原始 HTML。
  return content.replace(/<img\s+([^>]*?)\s*\/?\s*>/gi, (tag, attributes) => {
    const read = name => new RegExp(`\\b${name}\\s*=\\s*(["'])(.*?)\\1`, 'i').exec(attributes)?.[2];
    const src = read('src');
    if (!src?.startsWith('./assets/')) return tag;
    const alt = read('alt') || '';
    const zoom = /(?:^|;)\s*zoom\s*:\s*([^;]+)/i.exec(read('style') || '')?.[1]?.trim();
    const target = zoom ? `${src}${src.includes('?') ? '&' : '?'}_acmZoom=${encodeURIComponent(zoom)}` : src;
    return `![${alt.replace(/[\[\]\\]/g, '\\$&')}](${target.replace(/[()\\]/g, '\\$&')})`;
  });
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
  return <div className="code-block"><pre ref={pre}><CodeBlockContext.Provider value>{children}</CodeBlockContext.Provider></pre>
    <button type="button" className={`code-copy ${message === 'copied' ? 'is-copied' : ''}`} onClick={copy}
      aria-label={text[message]} title={text[message]}><span className="copy-icon" aria-hidden="true" /></button>
    <span className="sr-only" role="status">{message === 'copy' ? '' : text[message]}</span></div>;
}

function preserveCodeEscapes(content) {
  // TOML 的基本字符串会将 '\\n' 解析为换行；在围栏代码的单、双引号中将其还原为转义字符。
  return content.replace(/(^|\r?\n)((`{3,}|~{3,})[^\r\n]*\r?\n)([\s\S]*?)\r?\n\3(?=\r?\n|$)/g,
    (_, boundary, opening, fence, body) => `${boundary}${opening}${body.replace(/(['"])\r?\n\1/g, '$1\\n$1')}\n${fence}`);
}

export default function Markdown({ content, revision }) {
  return <RevisionContext.Provider value={revision}><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    pre: CodeBlock, code: HighlightedCode, img: MarkdownImage,
    a: MarkdownLink,
  }}>{normalizeAnnouncementImages(preserveCodeEscapes(content))}</ReactMarkdown></RevisionContext.Provider>;
}

