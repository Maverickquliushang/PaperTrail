import {useEffect, useState} from 'react';
import type {Paper} from './types';

// Same-origin, session-only handoff to the shared paper page under /library/.
// No personal search result is written into the public cumulative catalog.
export function PaperTitle({paper}: {paper: Paper}) {
  const [error,setError]=useState('');
  const remember=()=>sessionStorage.setItem(`papertrail:paper:${paper.id}`,JSON.stringify(paper));
  useEffect(()=>{try{remember();}catch{/* The normal click reports storage failure. */}},[paper]);
  return <>
    <a className="paper-title" href={`/library/paper.html?local=${encodeURIComponent(paper.id)}&from=${encodeURIComponent(window.location.hash)}`} onClick={event=>{
      try{remember();setError('');}catch{event.preventDefault();setError('浏览器无法保存本次论文详情，请使用“摘要与来源”查看，或允许本站会话存储后重试。');}
    }}>{paper.title}</a>
    {error && <p role="alert" className="muted">{error}</p>}
  </>;
}

export function PaperOriginalLinks({paper}: {paper: Paper}) {
  const url=paper.evidence.find(e=>!e.cached && /^https?:\/\//i.test(e.url))?.url || paper.evidence[0]?.url;
  const pdf=paper.evidence.find(e=>e.pdf_url && /^https?:\/\//i.test(e.pdf_url))?.pdf_url;
  return <div className="paper-original-wrapper"><div className="paper-links">
    {url && /^https?:\/\//i.test(url) && <a href={url} target="_blank" rel="noopener noreferrer">查看原文 <span aria-hidden="true">↗</span></a>}
    {pdf && <a href={pdf} target="_blank" rel="noopener noreferrer">PDF ↗</a>}
  </div>{url && /^https?:\/\//i.test(url) && <p className="original-url"><a href={url} target="_blank" rel="noopener noreferrer">{url}</a></p>}</div>;
}
