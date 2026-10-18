import {dailyArchive} from './daily.js';
import {scopeKey, dateChoices, selectShards, createShardLoader} from './browse.js';
import {sourceNames, translateQuery, search, sortPapers, safeLink, conferenceNames, reviewNames, dblpStreams, scopedPapers, conferenceYear} from './search.js';
const $ = id => document.getElementById(id);
const descriptions = {all:'浏览全部已采集来源',arxiv:'追踪各学科的预印本研究',openalex:'OpenAlex 学术索引 · 支持具体日期',huggingface:'社区收录的机器学习论文',conferences:'DBLP 与会议官网 · 按会议、年份浏览',openreview:'已录用论文与公开投稿分开浏览'};
let routeVersion = 0, loading = false;
const loadShards = createShardLoader();
let preview = false, preloadTimer;
let daily = {days: new Map(), all: []};
let catalog, terms, page = 1, source = 'all', mode = 'search', conference = 'all', review = 'accepted';
function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function link(text, href) { const node = element('a', text); const safe = safeLink(href); if (safe) { node.href = safe; node.target = '_blank'; node.rel = 'noopener noreferrer'; } return node; }
function formatted(value) { return value ? new Date(value).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) : '尚无成功更新'; }
const today = () => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const currentIndex = () => catalog.browse_index?.[scopeKey(source,conference,review)];
function prepareYears() {
  const initialized = $('year').options.length > 0;
  const previous = $('year').value;
  const counts = currentIndex()?.years || {};
  const years = Object.keys(counts).sort().reverse();
  const all = element('option','全部年份'); all.value = '';
  $('year').replaceChildren(all,...years.map(year => {const o=element('option',`${year} 年 · ${counts[year]} 篇`);o.value=year;return o;}));
  $('year').value = previous && years.includes(previous) ? previous : !initialized && mode === 'daily' ? years[0] || '' : '';
}
function prefetchTarget(target, meeting = 'all', version = routeVersion) {
  if (!catalog || navigator.connection?.saveData) return;
  const index = catalog.browse_index?.[scopeKey(target,meeting)];
  const date = mode === 'daily' && target !== 'conferences' ? ($('history').value === 'all' ? '' : $('history').value || Object.keys(index?.dates || {}).sort().at(-1) || '') : '';
  const year = target === 'conferences' ? $('year').value : '';
  loadShards(selectShards(catalog,{source:target,conference:meeting,date,year,datedOnly:mode === 'daily' && target !== 'conferences'}).slice(0,2),{concurrency:1,active:()=>version===routeVersion}).catch(()=>{});
}
async function setRoute() {
  if (!catalog) return;
  const version = ++routeVersion;
  const parts = location.hash.slice(2).split('/');
  source = Object.hasOwn(sourceNames, parts[0]) ? parts[0] : 'all'; mode = parts[1] === 'daily' ? 'daily' : 'search'; page = 1;
  conference = source === 'conferences' && conferenceNames.includes(parts[2]) ? parts[2] : 'all';
  review = source === 'openreview' && parts[2] === 'public' ? 'public' : 'accepted';
  const suffix = source === 'conferences' ? `/${conference}` : source === 'openreview' ? `/${review}` : '';
  preview = false;
  $('workspace-title').textContent = (sourceNames[source] || '综合工作台') + (source === 'conferences' && conference !== 'all' ? ` · ${conference}` : source === 'openreview' ? ` · ${review === 'public' ? '公开投稿' : '已录用'}` : '');
  for (const node of $('sources').children) { node.href = `#/${node.dataset.source}/${mode}`; node.classList.toggle('active', node.dataset.source === source); node.setAttribute('aria-current', node.dataset.source === source ? 'page' : 'false'); }
  for (const node of $('modes').children) { node.href = `#/${source}/${node.dataset.mode}${suffix}`; node.classList.toggle('active', node.dataset.mode === mode); }
  $('modes').querySelector('[data-mode=daily]').textContent = source === 'conferences' ? '按年浏览' : '每日推荐';
  $('search-form').hidden = mode !== 'search'; $('start-wrap').hidden = mode !== 'search' || source === 'conferences'; $('end-wrap').hidden = mode !== 'search' || source === 'conferences'; $('history-wrap').hidden = mode !== 'daily' || source === 'conferences';
  $('year-wrap').hidden = source !== 'conferences';
  if (source === 'conferences') prepareYears();
  if (mode === 'daily' && source !== 'conferences' && currentIndex()) updateHistoryLabels();
  renderDirectory();
  loading = true;
  $('results').replaceChildren(element('p','正在加载已收录论文…'));
  $('result-summary').textContent = '';
  $('load-status').textContent = '正在准备论文…'; $('retry-load').hidden = true; $('results').setAttribute('aria-busy','true');
  try {
    const date = mode === 'daily' && source !== 'conferences' && $('history').value !== 'all' ? $('history').value : '';
    const shards = selectShards(catalog,{source,conference,date,year:source === 'conferences' ? $('year').value : '',datedOnly:mode === 'daily' && source !== 'conferences'});
    let lastPreview = 0;
    const loaded = await loadShards(shards,{active:()=>version===routeVersion,progress:(rows,done,total)=>{
      if (version !== routeVersion) return;
      $('load-status').textContent = `正在加载 ${done}/${total} 个数据分片；已加载内容可先浏览。`;
      if (mode === 'search' && (!lastPreview || performance.now()-lastPreview>2000)) {
        lastPreview=performance.now();catalog.papers=rows;preview=true;loading=false;render();loading=true;
      }
    }});
    if (version !== routeVersion) return;
    catalog.papers = [...(catalog.inline_papers || []),...loaded];
    if (mode === 'daily' && source !== 'conferences') {
      daily = dailyArchive(catalog.papers,catalog.history,source,conference,review,today());
      updateHistoryLabels();
    }
    loading = false; preview = false;
    $('load-status').textContent = ''; $('results').setAttribute('aria-busy','false');
    render();
    clearTimeout(preloadTimer);
    const thisVersion=version;
    preloadTimer=setTimeout(()=>{if(thisVersion===routeVersion)for(const key of Object.keys(sourceNames))if(key!==source)prefetchTarget(key,'all',thisVersion);},1200);
  } catch (error) {
    if (version !== routeVersion) return;
    loading = false;
    $('load-status').textContent = error.message; $('retry-load').hidden = false; $('results').setAttribute('aria-busy','false');
    $('results').replaceChildren(element('p',error.message,'error'));
  }
}
function visibleReports(status) {
  return (status?.queries || []).filter(r =>
    (source !== 'conferences' || conference === 'all' || !r.conference || r.conference === conference) &&
    (source !== 'openreview' || !r.view || r.view === review));
}
function renderDirectory() {
  $('subdirectory').hidden = !['conferences','openreview'].includes(source);
  $('subnav').replaceChildren(); $('directory-links').replaceChildren(); $('collection-progress').replaceChildren();
  if (source === 'conferences') {
    for (const name of ['all',...conferenceNames]) {
      const count = (name === 'all' ? catalog.conference_catalog?.total : catalog.conference_catalog?.counts?.[name]) ?? scopedPapers(catalog.inline_papers || catalog.papers,'conferences',name).length;
      const a = element('a',name === 'all' ? '全部会议' : name); a.href = `#/conferences/${mode}/${name}`;
      a.dataset.conference = name; a.classList.toggle('active',name === conference); a.setAttribute('aria-current',name === conference ? 'page' : 'false');
      a.append(element('small',`${count} 篇`)); $('subnav').append(a);
    }
    $('scope-note').textContent = 'DBLP 历史索引与会议官网公开清单分别采集，包含尚未正式出版的官网论文。按会议年份筛选；不限制收录篇数。DBLP 遍历完成不代表官网或会议论文已收齐，以下分别列出覆盖状态。';
    for (const name of conference === 'all' ? conferenceNames : [conference]) {
      const row = element('a',undefined,'collection-row');
      row.href = `#/conferences/${mode}/${name}`; row.dataset.conferenceCard=name;
      row.addEventListener('pointerenter',()=>prefetchTarget('conferences',name));
      row.addEventListener('focus',()=>prefetchTarget('conferences',name));
      row.append(element('strong',`${name} · 本站已收录 ${catalog.conference_catalog?.counts?.[name] ?? 0} 篇`));
      for (const index of ['DBLP']) {
        const entry = catalog.conference_sync?.[index+':'+name], h = entry?.history;
        const status = entry?.error ? '访问受限 / 等待重试' : h?.complete ? '本轮历史索引已遍历' : h ? '历史补采中' : '等待开始补采';
        row.append(element('p',`${index}：${status}${h ? ` · 已检查 ${h.scanned} / ${h.total ?? '未知'} 条索引记录（${h.pages} 页）` : ''}`));
        if (h?.total > 0) { const bar = element('progress');bar.max=h.total;bar.value=Math.min(h.scanned,h.total);bar.setAttribute('aria-label',`${name} ${index} 历史分页进度`);row.append(bar); }
        if (entry?.recent) row.append(element('small',`新增检查：${entry.recent.start} 至 ${entry.recent.end} · ${entry.recent.complete ? '已完成' : '分页进行中'}，已检查 ${entry.recent.scanned} 条。`));
        if (entry?.error) row.append(element('small',entry.error));
      }
      const official=(catalog.source_status.conferences?.queries || []).find(r=>r.conference===name && r.index==='Official');
      row.append(element('p',official ? `官网：${official.state==='success'?'该入口已读取':official.state==='partial'?'部分覆盖':'本轮未完成'} · ${official.count} 条候选` : '官网：等待检查'));
      if(official)row.append(element('small',official.note));
      $('collection-progress').append(row);
      row.append(element('small',`查看 ${name} 论文 →`));
    }
    for (const name of conference === 'all' ? conferenceNames : [conference]) $('directory-links').append(link(`${name} · DBLP 历年目录 ↗`,`https://dblp.org/db/conf/${dblpStreams[name]}/index.html`));
    for(const report of visibleReports(catalog.source_status.conferences).filter(r=>r.index==='Official' && r.url))$('directory-links').append(link(`${report.label} ↗`,report.url));
  } else if (source === 'openreview') {
    for (const [key,label] of [['accepted','已录用'],['public','公开投稿']]) {
      const a = element('a',label); a.href = `#/openreview/${mode}/${key}`; a.dataset.review = key;
      a.classList.toggle('active',key === review); a.setAttribute('aria-current',key === review ? 'page' : 'false'); $('subnav').append(a);
    }
    $('scope-note').textContent = review === 'accepted'
      ? '默认只看 ICLR / ICML / NeurIPS 已录用主会论文。不设 30 天限制；每日推荐单独筛日期。'
      : '仅显示无需登录可读取的公开投稿，可能包括在审、已录用、未录用或已撤稿。状态以来源为准，未知不等于在审。非已录用记录使用投稿创建日期，不代表首次公开日期或录用日期。';
    $('directory-links').append(link('打开 OpenReview ↗','https://openreview.net/'));
  }
}
function paperCard(paper, index) {
  const node = element('article', undefined, 'paper');
  const meta = element('div', undefined, 'meta'); meta.append(element('span', `${index}. ${paper.date || (paper.year ? `${paper.year}（仅年份）` : '日期未知')}`), element('span', paper.sources.map(s => sourceNames[s]).join(' / ')),element('span', paper.date_kind || '公开日期')); node.append(meta);
  if (paper.review_status) meta.append(element('span',reviewNames[paper.review_status] || reviewNames.unknown,'review-badge'));
  const meetings = [...new Set((paper.evidence || []).map(e => e.conference).filter(Boolean))];
  if (meetings.length) meta.append(element('span',meetings.join(' / ')));
  const title = element('h3'); title.append(link(paper.title, paper.evidence?.[0]?.url)); node.append(title);
  if (paper.authors?.length) node.append(element('p', paper.authors.slice(0,6).join(', ') + (paper.authors.length > 6 ? ' 等' : ''), 'muted'));
  const detail = element('details'); detail.append(element('summary', '摘要与来源详情'), element('p', paper.abstract || '该来源未提供摘要。', 'abstract'));
  for (const item of paper.evidence || []) { const row = element('p', `${item.index_provider || (item.source === 'conferences' ? 'OpenAlex 顶会索引' : sourceNames[item.source])} · ${item.conference || item.venue || '未提供会议信息'} · `); row.append(link('来源原文 ↗', item.url)); detail.append(row); }
  node.append(detail);
  const actions = element('div', undefined, 'links'); actions.append(link('查看原文 ↗', paper.evidence?.[0]?.url)); const pdf = paper.evidence?.find(e => safeLink(e.pdf_url)); if (pdf) actions.append(link('PDF ↗', pdf.pdf_url)); node.append(actions);
  return node;
}
function renderStatus() {
  $('status').replaceChildren();
  for (const key of Object.keys(sourceNames).filter(s => source === 'all' || s === source)) {
    const status = catalog.source_status[key], node = element('div');
    const reports = visibleReports(status);
    const state = reports.length ? (reports.every(r => r.state === 'error') ? 'error' : reports.some(r => ['error','partial','limited'].includes(r.state)) ? 'partial' : 'success') : status?.state;
    const updated = reports.length ? reports.map(r => r.updated_at).filter(Boolean).sort().at(-1) : status?.updated_at;
    const label = {success:'本轮采集成功',partial:'尚未完整采集',error:'本轮采集失败'}[state] || '尚未采集';
    node.append(element('strong',`${sourceNames[key]} · ${label}`),element('p',`最近成功更新：${formatted(updated)}`));
    for (const report of reports) node.append(element('p', `${report.label}：${report.state === 'error' ? '失败' : `${report.count} 篇候选`}。${report.note}`));
    $('status').append(node);
  }
}
function emptyMessage() {
  if (!$('error').hidden) return '筛选条件无效，请按上方提示调整后重试。';
  const keys = Object.keys(sourceNames).filter(key => source === 'all' || key === source);
  if (mode === 'daily') {
    return '所选日期暂无已收录论文。可选择其他日期或“全部日期”；没有结果不代表来源当天没有论文。只有年份的记录请在“论文检索”中查看。';
  }
  const available = scopedPapers(catalog.papers, source, conference, review);
  if (available.length) return '已收录论文中没有匹配当前关键词或日期的结果。可清空关键词或放宽筛选日期；筛选不会向来源实时取数。';
  const failed = keys.filter(key => visibleReports(catalog.source_status[key]).some(r => ['error','partial','limited'].includes(r.state)) || catalog.source_status[key]?.state === 'error');
  if (failed.length) return `${failed.map(key => sourceNames[key]).join('、')}最近一轮采集未完成，当前没有可用论文。这不表示来源没有论文，请展开“来源状态与覆盖范围”查看原因。`;
  if (!catalog.updated_at) return '论文库尚未生成。首次部署后运行仓库中的 Update papers and deploy 工作流。';
  const scope = source === 'all' ? '当前论文库' : sourceNames[source];
  const window = '当前已采集的索引范围内（不设统一起始日期）';
  return `${scope}在${window}尚未收录论文。这不代表该来源没有论文；页面日期留空也只浏览已采集数据，不会扩大采集范围。` +
    (source === 'conferences' ? ' 顶会专区按 DBLP 会议索引收录；可用上方 DBLP 目录查看其他年份，收录不保证完整。' : '') +
    ' 可切换“全部来源”浏览其他已收录论文。';
}
function updateHistoryLabels() {
  const selected = $('history').value;
  const index=currentIndex(), counts=index?.dates || Object.fromEntries([...daily.days].map(([date,rows])=>[date,rows.length]));
  const all = element('option',`全部日期 · 已收录 ${index?.dated_total ?? daily.all.length} 篇`); all.value = 'all';
  const options=dateChoices(counts,today(),selected).map(date=>{const count=counts[date] || 0;const o=element('option',`${date} · ${count} 篇${count ? '' : '（暂无收录）'}`);o.value=date;return o;});
  $('history').replaceChildren(all,...options);
  $('history').value = selected || Object.keys(counts).filter(d=>d<=today()).sort().at(-1) || today();
}
function render() {
  if (!catalog || loading) return;
  $('error').hidden = true; let papers = [];
  try {
    if (mode === 'search') {
      if (source !== 'conferences' && $('start').value && $('end').value && $('start').value > $('end').value) throw new Error('开始日期不能晚于结束日期。');
      const query = translateQuery($('query').value, terms);
      let scoped=scopedPapers(catalog.papers, source, conference, review);
      if(source==='conferences')scoped=conferenceYear(scoped,$('year').value,conference);
      papers = search(scoped, query, {source, start:source==='conferences'?'':$('start').value,end:source==='conferences'?'':$('end').value,sort:$('sort').value});
      $('query-note').textContent = query ? `实际关键词：${query}。在已收录标题与摘要中匹配全部关键词；可选 BM25 排序。` : '正在浏览累计收录的论文，不设统一起始日期。可自行筛选日期；只有年份的记录不参与精确日期筛选。搜索不会向来源实时取数。';
    } else if (source === 'conferences') {
      papers=sortPapers(conferenceYear(scopedPapers(catalog.papers,source,conference,review),$('year').value,conference),$('sort').value);
      $('query-note').textContent='按会议年份浏览全部已收录论文，包含官网已经公开的论文。年份不等于正式出版日期；没有具体月日时不伪造日期。';
    } else {
      const selected = $('history').value;
      papers = sortPapers(selected === 'all' ? daily.all : daily.days.get(selected) || [], $('sort').value);
      $('query-note').textContent = (selected === 'all'
        ? '全部日期：展示当前专区所有有明确日期的已收录论文，跨日期按论文标识去重。'
        : `日期 ${selected}：展示来源标注为该日的全部已收录论文。`)
        + ' 日期连续列出，0 篇表示本站暂无收录，不代表官网当天无论文；可能尚未公开、索引延迟或采集未完成。数量不代表来源当日总量。'
        + (source === 'openreview' && review === 'public' ? ' 公开投稿不代表已录用。' : '');
    }
  } catch (error) { $('error').textContent = error.message; $('error').hidden = false; }
  const pages = Math.max(1, Math.ceil(papers.length / 10)); page = Math.min(page, pages);
  const start = (page - 1) * 10;
  $('result-summary').textContent = `${preview ? '加载中 · 暂有' : '共'} ${papers.length} 篇 · ${papers.length ? `正在显示第 ${start + 1}–${Math.min(start + 10, papers.length)} 篇` : '当前没有可显示论文'}${preview ? '（完整数量和排序将在加载完成后更新）' : ''}`;
  $('results').replaceChildren(...papers.slice(start, start + 10).map((p,i) => paperCard(p,start+i+1)));
  if (!papers.length) $('results').append(element('div', emptyMessage(), 'empty'));
  $('page-label').textContent = `第 ${page} / ${pages} 页`; $('previous').disabled = page === 1; $('next').disabled = page === pages;
  renderStatus();
}
for (const [key, name] of Object.entries({all:'全部来源',...sourceNames})) {
  const card = element('a',undefined,'source-card'); card.href = `#/${key}/search`; card.dataset.source = key;
  card.append(element('span','↗','arrow'),element('strong',name),element('small',descriptions[key]));
  card.addEventListener('pointermove', event => { const rect = card.getBoundingClientRect(); card.style.setProperty('--mx', `${event.clientX-rect.left}px`); card.style.setProperty('--my', `${event.clientY-rect.top}px`); });
  card.addEventListener('pointerenter',()=>prefetchTarget(key));
  card.addEventListener('focus',()=>prefetchTarget(key));
  $('sources').append(card);
}
$('search-form').addEventListener('submit', event => { event.preventDefault(); page = 1; render(); });
for (const key of ['start','end','sort']) $(key).addEventListener('change', () => { page = 1; render(); });
for (const key of ['history','year']) $(key).addEventListener('change',setRoute);
$('retry-load').addEventListener('click',setRoute);
for (const [key, delta] of [['previous',-1],['next',1]]) $(key).addEventListener('click', () => {page += delta; render(); $('result-summary').scrollIntoView({block:'start'});});
window.addEventListener('hashchange',setRoute);
try {
  [catalog, terms] = await Promise.all(['catalog','terms'].map(async name => { const response = await fetch(`./data/${name}.json`,{cache:'no-cache'}); if (!response.ok) throw new Error(`数据读取失败（${response.status}）`); return response.json(); }));
  if (catalog.schema !== 2 || catalog.mode !== 'ai_latest' || !Array.isArray(catalog.papers)) throw new Error('论文库格式不正确。');
  const failed = Object.values(catalog.source_status).filter(s => s.state !== 'success').length;
  $('update').textContent = `论文库更新：${formatted(catalog.updated_at)}（北京时间） · ${catalog.paper_count ?? catalog.papers.length} 篇` + (failed ? ` · ${failed} 个来源未完整更新，详情见来源状态。` : '') + (catalog.notice ? ` · ${catalog.notice}` : '');
  catalog.inline_papers = catalog.papers;
  $('query').value = '';
  setRoute();
} catch (error) { $('update').textContent = `无法加载论文库：${error.message} 请刷新重试。`; $('error').hidden = false; $('error').textContent = '需通过 HTTP 网页访问，不能直接双击 index.html；可使用 GitHub Pages 或本地预览服务器。'; }

if (location.pathname.startsWith('/library')) {
  $('local-controls').hidden = false;
  document.querySelector('.intro > p.muted').textContent = '本地累计论文库：本机分页采集与保存，会议目录、每日数量和补采进度与网页版同步。';
  let wasRunning = false;
  const checkLocal = async () => {
    try {
      const response = await fetch('/api/library');
      if (!response.ok) throw new Error();
      const state = await response.json();
      $('sync-library').disabled = state.running;
      $('sync-status').textContent = state.running ? '正在分页采集，本轮完成后自动刷新…' : state.error || '本地论文库 · 每天 09:00 更新，运行期间自动续接历史';
      if (wasRunning && !state.running && !state.error) location.reload();
      wasRunning = state.running;
    } catch { $('sync-status').textContent = '本地服务状态读取失败，请刷新重试。'; }
  };
  $('sync-library').addEventListener('click',async () => {
    const response = await fetch('/api/library/sync',{method:'POST'});
    if (!response.ok) { $('sync-status').textContent = '未能启动更新，请重试。'; return; }
    await checkLocal();
  });
  checkLocal(); setInterval(checkLocal,10000);
}
