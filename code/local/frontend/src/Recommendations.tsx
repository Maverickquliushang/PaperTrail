import { useEffect, useRef, useState } from 'react';
import { conferences, sourceNames, type Paper, type Source, type SourceStatus } from './types';
import { PaperSort, sortPapers, type PaperOrder } from './PaperSort';

interface Settings {
  topics: string[]; enabled: boolean; time: string; timezone: string; count: number;
  exclude_keywords?: string[];
  lookback_days: number; dedup_days: number; sources: Source[]; conferences: string[];
}
interface Recommendation extends Paper { reasons: string[]; recommendation_score: number; topics: string[] }
interface Run {
  id: string; date: string; started_at: string; status: string; note: string; trigger: string;
  settings: Settings; paper_count: number; papers?: Recommendation[]; excluded_count: number;
  keyword_excluded_count?: number;
  source_results: { topic: string; sources: SourceStatus[]; error?: string }[];
}
interface Overview { settings: Settings; runs: Run[]; running: boolean; next_run: string | null; storage_error: string | null }
const names: Record<string, string> = { running: '生成中', success: '已完成', partial: '部分来源失败', empty: '暂无新推荐', failed: '生成失败', interrupted: '已中断' };

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : '参数无效或请求失败，请检查输入和本地服务。');
  }
  return response.json();
}

export function Recommendations({ openPaper, source = null }: { openPaper: (paper: Paper) => void; source?: Source | null }) {
  const endpoint = (path: string) => source ? `${path}?source=${source}` : path;
  const [overview, setOverview] = useState<Overview | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [topics, setTopics] = useState('');
  const [exclusions, setExclusions] = useState('');
  const [dirty, setDirty] = useState(false);
  const [selected, setSelected] = useState('');
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [working, setWorking] = useState(false);
  const [reload, setReload] = useState(0);
  const [order, setOrder] = useState<PaperOrder>('rank');
  const editing = useRef(false);
  editing.current = dirty || working;

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const data = await api<Overview>(endpoint('/api/recommendations'));
        if (!active) return;
        setOverview(data);
        if (!editing.current) {
          setSettings(data.settings);
          setTopics(data.settings.topics.join('\n'));
          setExclusions((data.settings.exclude_keywords || []).join('\n'));
        }
        const id = selected || data.runs[0]?.id;
        if (id) {
          const detail = await api<Run>(endpoint(`/api/recommendations/runs/${id}`));
          if (active) setRun(detail);
        } else setRun(null);
        if (active) setError('');
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : '无法加载推荐');
      } finally {
        if (active) timer = setTimeout(refresh, 4000);
      }
    }
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [selected, reload, source]);

  function update(changes: Partial<Settings>) {
    setSettings(current => current && { ...current, ...changes }); setDirty(true); setNotice('');
  }

  async function save() {
    if (!settings) return;
    setWorking(true); setError('');
    try {
      const saved = await api<Settings>(endpoint('/api/recommendations/settings'), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...settings, sources: source ? [source] : settings.sources, topics: topics.split('\n').map(t => t.trim()).filter(Boolean), exclude_keywords: exclusions.split('\n').map(t => t.trim()).filter(Boolean) }),
      });
      setSettings(saved); setTopics(saved.topics.join('\n')); setDirty(false);
      setNotice(saved.enabled ? '设置已保存，已开启每日自动生成。' : '设置已保存，可点击“立即生成”。');
      setReload(n => n + 1);
    } catch (err) { setError(err instanceof Error ? err.message : '保存失败'); }
    finally { setWorking(false); }
  }

  async function generate() {
    setWorking(true); setError('');
    try {
      const created = await api<Run>(endpoint('/api/recommendations/runs'), { method: 'POST' });
      setSelected(created.id); setRun(created); setReload(n => n + 1); setNotice('正在生成，结果会自动更新。');
    } catch (err) { setError(err instanceof Error ? err.message : '无法生成'); }
    finally { setWorking(false); }
  }

  const papers = sortPapers(run?.papers ?? [], order, true);
  return <section className="recommendations" aria-label="每日推荐">
    <div className="section-heading"><div><span className="eyebrow">DAILY READING</span><h1>{source ? `${sourceNames[source]} 每日推荐` : '每日推荐'}</h1><p>{source ? '本专区的推荐设置、阅读清单和去重历史独立保存。' : '围绕你的主题，留下一份可以回看的阅读清单。'}</p></div><span className="tag">规则推荐 · 无需模型</span></div>
    {error && <div className="alert error-alert" role="alert">{error}</div>}
    {overview?.storage_error && <div className="alert error-alert" role="alert">{overview.storage_error}</div>}
    {notice && <div className="alert" role="status">{notice}</div>}
    {!settings ? <p>正在加载本地推荐设置…</p> : <div className="recommendation-settings search-panel">
      <label className="topic-field"><span className="field-label">研究主题（每行一个，最多 5 个）</span><textarea aria-label="推荐研究主题" rows={3} placeholder={'例如：multimodal retrieval\ndiffusion models'} value={topics} disabled={working} onChange={e => { setTopics(e.target.value); setDirty(true); setNotice(''); }} /></label>
      <p className="muted">每个主题独立检索。建议使用英文关键词；先保存，再生成推荐。</p>
      <label className="topic-field"><span className="field-label">排除词或短语（可选，每行一个）</span><textarea aria-label="推荐排除词" rows={2} value={exclusions} placeholder="标题或摘要含这些词时不推荐" disabled={working} onChange={e => { setExclusions(e.target.value); setDirty(true); setNotice(''); }} /></label>
      <div className="daily-fields">
        <label>每日时间（北京时间）<input type="time" value={settings.time} onChange={e => update({ time: e.target.value })} /></label>
        <label>推荐篇数（0 = 全部符合条件）<input type="number" min={0} max={50} value={settings.count} onChange={e => update({ count: Number(e.target.value) })} /></label>
        <label>回溯天数<input type="number" min={1} max={365} value={settings.lookback_days} onChange={e => update({ lookback_days: Number(e.target.value) })} /></label>
        <label>历史去重天数<input type="number" min={1} max={365} value={settings.dedup_days} onChange={e => update({ dedup_days: Number(e.target.value) })} /></label>
      </div>
      {source ? <p className="scope-source-lock"><span className={`source-dot ${source}`} /><strong>{sourceNames[source]}</strong><span>此专区只推荐这个来源，不影响综合推荐或其他专区。</span></p> : <fieldset className="choice-field"><legend>推荐论文来源</legend><div className="source-checkboxes">{(Object.keys(sourceNames) as Source[]).map(s => <label key={s}><input type="checkbox" checked={settings.sources.includes(s)} onChange={e => update({ sources: e.target.checked ? [...settings.sources, s] : settings.sources.filter(x => x !== s) })} />{sourceNames[s]}</label>)}</div></fieldset>}
      {(settings.sources.includes('conferences') || settings.sources.includes('openreview')) && <fieldset className="choice-field"><legend>关注会议（用于顶会索引和 OpenReview）</legend><div className="conference-options">{conferences.map(c => <label key={c}><input type="checkbox" checked={settings.conferences.includes(c)} onChange={e => update({ conferences: e.target.checked ? [...settings.conferences, c] : settings.conferences.filter(x => x !== c) })} />{c}</label>)}</div></fieldset>}
      <label className="enable-daily"><input type="checkbox" checked={settings.enabled} onChange={e => update({ enabled: e.target.checked })} />每天自动生成到本地网页</label>
      <p className="muted">电脑和后台程序运行时执行。错过时间仅补当天一次，不补历史日期；当天已有手动或自动运行则不再自动重复，失败可手动重试。关闭网页不影响后台生成。</p>
      <div className="daily-actions"><button className="search-button" onClick={save} disabled={working || !!overview?.storage_error}>保存设置</button><button className="secondary-button" onClick={generate} disabled={working || dirty || overview?.running || !settings.topics.length || !!overview?.storage_error}>{overview?.running ? '正在生成…' : '立即生成'}</button><span className="muted">{dirty ? '有未保存的设置' : overview?.next_run ? `下次检查：${new Date(overview.next_run).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}` : '自动生成未开启'}</span></div>
    </div>}
    <div className="recommendation-results">
      <aside className="run-history"><h2>推荐历史</h2>{!overview?.runs.length && <p className="muted">保存主题并生成后，阅读清单会留在这里。</p>}{overview?.runs.map(r => <button key={r.id} className={run?.id === r.id ? 'active' : ''} onClick={() => { setSelected(r.id); setRun(null); }}><strong>{r.date}</strong><span>{names[r.status]} · {r.paper_count} 篇</span><small>{new Date(r.started_at).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })} · {r.trigger === 'manual' ? '手动' : '自动'}</small></button>)}</aside>
      <div className="daily-papers">{run ? <>
        <div className="section-heading"><h2>{run.date} 阅读清单</h2><span className="tag">{names[run.status]}</span></div><p className="muted">{run.note}</p><p className="muted">主题：{run.settings.topics.join(' / ')} · 回溯 {run.settings.lookback_days} 天 · 已排除 {run.excluded_count} 篇历史推荐 · 排除词过滤 {run.keyword_excluded_count || 0} 篇</p>
        <details className="run-source-details"><summary>查看本次来源状态与覆盖限制</summary>{run.source_results.map((result, i) => <div key={i}><h3>{result.topic}</h3>{result.error && <p>{result.error}</p>}{result.sources.map(s => <p key={s.source}><strong>{sourceNames[s.source]} · {s.state === 'error' ? '失败' : s.state === 'limited' ? '覆盖受限' : s.state === 'success' ? '成功' : s.state}</strong>：{s.note}</p>)}</div>)}</details>
        <PaperSort value={order} onChange={setOrder} recommended />
        <div className="paper-list">{papers.map((paper, i) => <article className="paper-card" key={paper.id}><div className="paper-index">{String(i + 1).padStart(2, '0')}</div><div className="paper-content"><div className="tags">{paper.sources.map(s => <span className={`tag ${s}`} key={s}>{sourceNames[s]}</span>)}<span className="tag">规则排序 {paper.recommendation_score}</span></div><button className="paper-title" onClick={() => openPaper(paper)}>{paper.title}</button><p className="authors">{paper.authors.slice(0, 5).join(' · ')} · {paper.date || '日期未提供'}</p><p className="abstract-preview">{paper.abstract || '来源未提供摘要，可通过论文详情查看原文。'}</p><ul className="recommendation-reasons">{paper.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul><button className="detail-button" onClick={() => openPaper(paper)}>摘要、原文与来源 →</button></div></article>)}</div>
        {run.status !== 'running' && !run.papers?.length && <div className="empty-result"><h3>{run.status === 'failed' || run.status === 'interrupted' ? '本次未完成推荐' : '本次没有可推荐的新论文'}</h3><p>{run.note}</p></div>}
      </> : <div className="empty-result"><h3>{overview?.runs.length ? '正在加载推荐记录…' : '你的下一份阅读清单，从一个主题开始'}</h3><p>推荐会保存在本机，重启后仍可查看。默认回溯 30 天，每日最多 10 篇。</p></div>}</div>
    </div>
  </section>;
}
