import {PaperTitle,PaperOriginalLinks} from './PaperTitle';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { conferences, sourceDescriptions, sourceNames, type Evidence, type Paper, type SearchRequest, type Snapshot, type Source, type SourceStatus } from './types';

import { Recommendations } from './Recommendations';
import { PaperSort, sortPapers, type PaperOrder } from './PaperSort';
import { SourceCard } from './SourceCard';
import { Feishu } from './Feishu';

const allSources = Object.keys(sourceNames) as Source[];
const examples = ['multimodal retrieval', 'diffusion models', 'large language models'];
const states: Record<SourceStatus['state'], string> = {
  pending: '等待中', running: '检索中', success: '已完成', limited: '覆盖受限', error: '来源失败', cancelled: '已取消',
};

function Icon({ name, size = 20 }: { name: 'search' | 'book' | 'arrow' | 'sliders' | 'external' | 'close'; size?: number }) {
  const paths = {
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" /></>,
    book: <><path d="M4 4h6c1.2 0 2 .8 2 2v15c0-1.5-1-2-2-2H4zM20 4h-6c-1.2 0-2 .8-2 2v15c0-1.5 1-2 2-2h6z" /></>,
    arrow: <><path d="M5 12h14m-6-6 6 6-6 6" /></>,
    sliders: <><path d="M4 7h16M4 17h16" /><circle cx="8" cy="7" r="2" /><circle cx="16" cy="17" r="2" /></>,
    external: <><path d="M14 4h6v6m0-6L10 14M10 4H4v16h16v-6" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function timestamp(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';
}

function ExternalLink({ href, children, className }: { href?: string | null; children: React.ReactNode; className?: string }) {
  if (!href || !/^https?:\/\//i.test(href)) return null;
  return <a className={className} href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
}

function EvidenceBlock({ evidence }: { evidence: Evidence }) {
  return <section className="evidence-block">
    <div className="evidence-title"><span className={`source-dot ${evidence.source}`} />{sourceNames[evidence.source]}<span className={`tag ${evidence.cached ? 'cached' : ''}`}>{evidence.cached ? '历史缓存' : '本次检索'}</span></div>
    <dl>
      <dt>来源标题</dt><dd>{evidence.title}</dd>
      <dt>首次提交</dt><dd>{evidence.submitted_date ?? '未提供'}</dd>
      <dt>{evidence.source === 'openreview' ? '公开日期' : '发表日期'}</dt><dd>{evidence.publication_date ?? (evidence.publication_year ? `${evidence.publication_year}（仅年份）` : '未提供')}</dd>
      <dt>论文更新</dt><dd>{evidence.updated_date ?? '未提供'}</dd>
      <dt>社区收录</dt><dd>{evidence.listed_date ?? '未提供'}</dd>
      <dt>来源会刊</dt><dd>{evidence.venue ?? '未提供 / 未核验'}</dd>
      <dt>检索时间</dt><dd>{timestamp(evidence.retrieved_at)}</dd>
    </dl>
    <div className="link-row"><ExternalLink href={evidence.url}>来源页面 <Icon name="external" size={13} /></ExternalLink><ExternalLink href={evidence.pdf_url}>PDF <Icon name="external" size={13} /></ExternalLink></div>
  </section>;
}

function Detail({ paper, close }: { paper: Paper; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  return <dialog ref={dialog} className="paper-dialog" onCancel={close} onClick={event => { if (event.target === event.currentTarget) close(); }}>
    <div className="dialog-inner">
      <div className="dialog-top"><span className="eyebrow">PAPER DETAILS / 论文详情</span><button className="icon-button" onClick={close} aria-label="关闭详情"><Icon name="close" /></button></div>
      <h2>{paper.title}</h2><p className="authors">{paper.authors.join(' · ') || '作者未提供'}</p>
      <h3>摘要 <span>{paper.abstract_source ? sourceNames[paper.abstract_source] : ''}</span></h3>
      <p className="full-abstract">{paper.abstract || '此来源未提供摘要，请通过原文链接查看。'}</p>
      <div className="identifiers">{paper.arxiv_id && <span>arXiv: {paper.arxiv_id}</span>}{paper.doi && <span>DOI: {paper.doi}</span>}</div>
      <h3>来源与时间记录</h3><p className="muted">日期按各来源分别保留。检索结果和会刊字段不代表已核验录用状态。</p>
      {paper.evidence.map((evidence, i) => <EvidenceBlock key={`${evidence.source}-${i}`} evidence={evidence} />)}
    </div>
  </dialog>;
}

function StatusCard({ status }: { status: SourceStatus }) {
  return <article className={`status-card ${status.state}`}>
    <div className="status-title"><strong><span className={`source-dot ${status.source}`} />{sourceNames[status.source]}</strong><span className="status-state">{['pending', 'running'].includes(status.state) && <span className="spinner" />}{states[status.state]}</span></div>
    <div className="status-count"><strong>{status.count}</strong><span>篇{status.cached_at ? '缓存结果' : '返回结果'}</span>{status.total !== null && <small> / 匹配 {status.total.toLocaleString()}</small>}</div>
    <p>{status.note || sourceDescriptions[status.source]}</p>
    {(status.cached_at || status.retrieved_at) && <div className="status-time">{status.cached_at ? '缓存于 ' : '检索于 '}{timestamp(status.cached_at || status.retrieved_at)}</div>}
  </article>;
}

type WorkspaceRoute = { source: Source | null; page: 'search' | 'daily' | 'feishu' };
function readRoute(): WorkspaceRoute {
  if (window.location.hash === '#/feishu') return { source: null, page: 'feishu' };
  const match = window.location.hash.match(/^#\/sources\/([^/]+)\/(search|daily)$/);
  if (match && allSources.includes(match[1] as Source)) return { source: match[1] as Source, page: match[2] as 'search' | 'daily' };
  return { source: null, page: window.location.hash === '#/daily' ? 'daily' : 'search' };
}

export default function App() {
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const changed = () => { setRoute(readRoute()); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  return <Workspace key={route.source || 'all'} scope={route.source} page={route.page} />;
}

function Workspace({ scope, page }: { scope: Source | null; page: WorkspaceRoute['page'] }) {
  const setPage = (next: 'search' | 'daily') => { window.location.hash = scope ? `/sources/${scope}/${next}` : `/${next}`; };
  const [chosenConferences, setChosenConferences] = useState([...conferences]);
  const [query, setQuery] = useState('');
  const [sources, setSources] = useState<Source[]>(scope ? [scope] : [...allSources]);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [limit, setLimit] = useState(10);
  const [sort, setSort] = useState<'relevance' | 'date'>('relevance');
  const [resultOrder, setResultOrder] = useState<PaperOrder>('rank');
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [connection, setConnection] = useState('');
  const [filter, setFilter] = useState<Source | 'all'>('all');
  const [selected, setSelected] = useState<Paper | null>(null);
  const stream = useRef<EventSource | null>(null);
  const generation = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const fallback = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopConnection() {
    stream.current?.close();
    stream.current = null;
    if (fallback.current) clearInterval(fallback.current);
    fallback.current = null;
  }
  useEffect(() => () => { generation.current++; stopConnection(); }, []);

  function accept(data: Snapshot, version: number) {
    if (version !== generation.current) return;
    setSnapshot(data);
    if (data.done) { setBusy(false); stopConnection(); setConnection(''); }
  }

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim() || !sources.length) { setError('请输入研究主题，并至少选择一个来源。'); return; }
    if (start && end && start > end) { setError('开始日期不能晚于结束日期。'); return; }
    stopConnection();
    const version = ++generation.current;
    setBusy(true); setError(''); setConnection(''); setSelected(null); setFilter('all'); setSnapshot(null);
    if (!chosenConferences.length) { setError('请至少选择一个会议。'); setBusy(false); return; }
    const payload: SearchRequest = { conferences: chosenConferences, query: query.trim(), sources: scope ? [scope] : sources, start_date: start || null, end_date: end || null, limit, sort };
    setResultOrder(sort === 'date' ? 'date_desc' : 'rank');
    try {
      const response = await fetch(scope ? `/api/searches?source=${scope}` : '/api/searches', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(typeof body.detail === 'string' ? body.detail : '检索参数无效，请检查输入。');
      }
      const data: Snapshot = await response.json();
      if (version !== generation.current) return;
      accept(data, version);
      if (data.done) return;
      const events = new EventSource(`/api/searches/${data.id}/events`);
      stream.current = events;
      events.addEventListener('snapshot', event => accept(JSON.parse(event.data), version));
      events.onerror = () => {
        if (version !== generation.current) return;
        events.close();
        setConnection('进度连接中断，正在通过轮询恢复。');
        let failures = 0;
        let polling = false;
        fallback.current = setInterval(async () => {
          if (polling || version !== generation.current) return;
          polling = true;
          try {
            const result = await fetch(`/api/searches/${data.id}`);
            if (!result.ok) throw new Error('任务不可用');
            accept(await result.json(), version);
            failures = 0;
          } catch {
            if (++failures >= 3 && version === generation.current) {
              stopConnection(); setBusy(false); setError('无法获取任务状态，请检查本地服务。已有结果保留；重新检索会创建新任务。'); setConnection('');
            }
          } finally { polling = false; }
        }, 2000);
      };
    } catch (err) {
      if (version === generation.current) { setBusy(false); setError(err instanceof Error ? err.message : '无法连接本地检索服务。'); }
    }
  }

  async function cancel() {
    if (!snapshot) return;
    try {
      const response = await fetch(`/api/searches/${snapshot.id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error();
      accept(await response.json(), generation.current);
    } catch { setError('未能确认取消状态，请检查本地服务。'); }
  }

  const papers = sortPapers(snapshot?.papers.filter(p => filter === 'all' || p.sources.includes(filter)) ?? [], resultOrder);
  const failures = snapshot?.sources.filter(s => s.state === 'error').length ?? 0;
  const cancelled = snapshot?.sources.some(s => s.state === 'cancelled');
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#/search" aria-label="PaperTrail 首页"><span className="brand-mark"><Icon name="book" size={23} /></span><span>PaperTrail<span className="brand-cn">论文踪迹</span></span></a><div className="top-right"><span className="local-pill"><i />本地工作台</span><span className="version">检索与推荐</span></div></header>
    <main>
      {scope && <section className={`source-workspace-banner ${scope}`} aria-label="当前来源专区"><div><a className="workspace-back" href="#/search">← 返回综合工作台</a><p><span className={`source-dot ${scope}`} /><strong>{sourceNames[scope]} 专区</strong><span>仅使用此来源的论文</span></p></div><nav className="source-workspace-switch" aria-label="切换来源专区">{allSources.map(source => <a key={source} href={`#/sources/${source}/${page}`} aria-current={source === scope ? 'page' : undefined}>{sourceNames[source]}</a>)}</nav></section>}
      <nav className="workspace-nav" aria-label="工作台导航"><button className={page === 'search' ? 'active' : ''} onClick={() => setPage('search')}>论文检索</button><button className={page === 'daily' ? 'active' : ''} onClick={() => setPage('daily')}>每日推荐</button><button className={page === 'feishu' ? 'active' : ''} onClick={() => { window.location.hash = '/feishu'; }}>飞书接入</button></nav>
      {page === 'feishu' && <Feishu />}
      <section className="source-workspace-banner" aria-label="累计论文库"><div><strong>累计论文库 · 历史分页补采</strong><p>按会议浏览历史论文、查看补采进度，或查看不限篇数的当日论文。数据保存在本机，程序运行时每天更新。</p></div><a className="secondary-button" href={`/library/#/${scope || 'all'}/${page === 'daily' ? 'daily' : 'search'}`}>打开本地累计论文库 →</a></section>
      {page === 'daily' && <Recommendations openPaper={setSelected} source={scope} />}
      <div hidden={page !== 'search'}>
      <section className="intro"><div><div className="eyebrow">FOLLOW THE IDEAS</div><h1>{scope ? `${sourceNames[scope]} 论文检索` : <>让研究，从发现开始<span>。</span></>}</h1><p>{scope ? sourceDescriptions[scope] : '一个主题，连接多个论文来源。找到值得读的下一篇。'}</p></div><div className="intro-note"><span>01 / DISCOVER</span><p>实时检索 · 来源可追溯<br />无需模型，即可开始</p></div></section>
      <form className="search-panel" onSubmit={search}>
        <label className="search-label" htmlFor="query">你想探索什么研究主题？</label>
        <div className="search-line"><Icon name="search" size={23} /><input ref={input} id="query" value={query} onChange={e => setQuery(e.target.value)} placeholder="输入主题或关键词，例如 multimodal retrieval" maxLength={250} required autoComplete="off" /><button type="submit" className="search-button" disabled={busy}>{busy ? '正在检索' : '检索论文'}{busy ? <span className="spinner" /> : <Icon name="arrow" size={19} />}</button></div>
        <div className="suggestions"><span>试试这些主题</span>{examples.map(text => <button type="button" key={text} disabled={busy} onClick={() => { setQuery(text); input.current?.focus(); }}>{text}<span>↗</span></button>)}</div>
        <div className="filter-row">{scope ? <div className="scope-source-lock"><span className={`source-dot ${scope}`} /><strong>{sourceNames[scope]}</strong><span>专区来源已固定</span></div> : <div className="source-picker"><span className="field-label">论文来源</span><div className="source-checkboxes">{allSources.map(source => <label key={source} className={sources.includes(source) ? 'checked' : ''}><input type="checkbox" checked={sources.includes(source)} disabled={busy} onChange={e => setSources(e.target.checked ? [...sources, source] : sources.filter(s => s !== source))} /><span className={`source-dot ${source}`} />{sourceNames[source]}</label>)}</div></div>}<div className="date-fields"><label><span className="field-label">开始日期</span><input type="date" aria-label="开始日期" value={start} onChange={e => setStart(e.target.value)} disabled={busy} /></label><span className="date-dash">—</span><label><span className="field-label">结束日期</span><input type="date" aria-label="结束日期" value={end} onChange={e => setEnd(e.target.value)} disabled={busy} /></label></div><label className="limit-field"><span className="field-label">每个来源</span><select value={limit} onChange={e => setLimit(Number(e.target.value))} disabled={busy} aria-label="每个来源结果数">{[5, 10, 20, 50].map(n => <option key={n} value={n}>{n} 篇</option>)}</select></label><label className="sort-field"><span className="field-label">检索取数顺序</span><select value={sort} onChange={e => { const value = e.target.value as 'relevance' | 'date'; setSort(value); setResultOrder(value === 'date' ? 'date_desc' : 'rank'); }} disabled={busy} aria-label="检索取数顺序"><option value="relevance">相关性优先取数</option><option value="date">日期优先取数</option></select></label></div>
        {(sources.includes('conferences') || sources.includes('openreview')) && <fieldset className="choice-field"><legend>关注会议（仅作用于顶会索引 / OpenReview）</legend><div className="conference-options">{conferences.map(c => <label key={c}><input type="checkbox" checked={chosenConferences.includes(c)} disabled={busy} onChange={e => setChosenConferences(e.target.checked ? [...chosenConferences, c] : chosenConferences.filter(x => x !== c))} />{c}</label>)}</div><p className="muted">顶会索引来自 DBLP，历史全库与补采进度可在上方累计论文库查看；OpenReview 直接补充三大机器学习主会已录用论文，每会最多检索 100 条候选。</p></fieldset>}
        <p className="search-hint">日期按各来源的提交 / 发表时间筛选；Hugging Face 仅在前 120 条候选内筛选。综合相关性使用来源排名融合，不是 AI 评分。</p>
      </form>
      {error && <div className="alert error-alert" role="alert">{error}</div>}
      {connection && <div className="alert" role="status">{connection}</div>}
      {snapshot ? <section className="results" aria-label="检索结果">
        <div className="section-heading"><div><span className="eyebrow">SEARCH RESULTS</span><h2>{snapshot.request.query}<span className="result-number">{snapshot.papers.length} 篇</span></h2></div><div className="result-meta"><span aria-live="polite">{busy ? '各来源正在独立返回结果…' : cancelled ? '检索已停止' : failures === snapshot.sources.length ? '所有来源检索失败' : failures ? `${failures} 个来源失败，其余结果已保留` : '本轮检索完成'}</span>{busy && <button className="text-button" onClick={cancel}>取消检索</button>}</div></div>
        <div className="status-grid">{snapshot.sources.map(status => <StatusCard key={status.source} status={status} />)}</div>
        <div className="result-toolbar"><div className="tabs" aria-label="按来源查看"><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>全部论文 <span>{snapshot.papers.length}</span></button>{snapshot.request.sources.map(source => <button key={source} className={filter === source ? 'active' : ''} onClick={() => setFilter(source)}>{sourceNames[source]}</button>)}</div><span className="merge-note">已合并 {snapshot.merged_count} 条重复记录</span></div>
        <PaperSort value={resultOrder} onChange={setResultOrder} />
        <p className="result-caption">{snapshot.request.sort === 'date' ? '本轮按日期优先向来源取数。' : '本轮按相关性优先向来源取数。'} 每个来源最多 {snapshot.request.limit} 篇，合并后共 {snapshot.papers.length} 篇。检索发起于 {timestamp(snapshot.started_at)}</p>
        <div className="paper-list">{papers.map((paper, index) => <article className="paper-card" key={paper.id}>
          <div className="paper-index">{String(index + 1).padStart(2, '0')}</div><div className="paper-content"><div className="paper-topline"><div className="tags">{paper.sources.map(source => <span className={`tag ${source}`} key={source}>{sourceNames[source]}</span>)}{[...new Set(paper.evidence.map(e => e.conference).filter(Boolean))].map(c => <span className="tag" key={c}>{c}</span>)}{paper.evidence.some(e => e.cached) && <span className="tag cached">含历史缓存</span>}</div><span className="paper-date">{paper.date ?? (paper.year ? `${paper.year}（仅年份）` : '日期未提供')} · {paper.date_kind}</span></div><PaperTitle paper={paper} /><p className="authors">{paper.authors.slice(0, 5).join(' · ') || '作者未提供'}{paper.authors.length > 5 ? ` 等 ${paper.authors.length} 位作者` : ''}</p><p className="abstract-preview">{paper.abstract || '来源未提供摘要，可打开原文进一步了解。'}</p><div className="paper-bottom"><PaperOriginalLinks paper={paper} /><button className="detail-button" onClick={() => setSelected(paper)}>摘要与来源 <Icon name="arrow" size={15} /></button></div></div>
        </article>)}</div>
        {!papers.length && <div className="empty-result"><Icon name="search" size={32} /><h3>{busy ? '正在连接论文来源' : failures ? '本次尚无可显示结果' : cancelled ? '本轮检索已取消' : '当前范围内没有返回论文'}</h3><p>{busy ? '结果会随各来源完成而显示，你不必等待所有来源。' : failures ? '请查看上方来源状态；请求失败不代表没有论文。' : '可以尝试缩短关键词、放宽日期或切换来源。Hugging Face 的结果受候选上限限制。'}</p></div>}
      </section> : scope ? <section className="welcome scope-empty"><h2>从 {sourceNames[scope]} 开始探索</h2><p>输入主题后仅请求此来源。你也可以切换到“每日推荐”，为这个专区单独生成和保存阅读清单。</p><button className="secondary-button" onClick={() => setPage('daily')}>查看 {sourceNames[scope]} 每日推荐 →</button></section> : <section className="welcome"><div className="section-heading"><div><span className="eyebrow">YOUR RESEARCH STARTS HERE</span><h2>从一个问题，发现新的线索</h2></div><span className="welcome-label">5 个检索通道 · 11 个会议</span></div><p className="source-card-hint">进入来源专区，使用独立的论文检索、每日推荐和历史记录。</p><div className="welcome-sources">{allSources.map((source, index) => <SourceCard key={source} source={source} index={index} />)}</div><div className="welcome-bottom"><Icon name="sliders" size={19} /><p>检索时实时请求来源接口。数据缺失、访问失败和覆盖限制会分别标注。</p><span>为认真阅读而发现</span></div></section>}
      </div>
    </main>
    <footer><span>PaperTrail <span className="footer-dot">·</span> 论文踪迹</span><span>本地运行，连接开放研究。</span></footer>
    {selected && <Detail paper={selected} close={() => setSelected(null)} />}
  </div>;
}
