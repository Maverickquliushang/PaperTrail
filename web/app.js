import {sourceNames, translateQuery, search, sortPapers, safeLink} from './search.js';
const $ = id => document.getElementById(id);
const descriptions = {all:'浏览全部已采集来源',arxiv:'追踪各学科的预印本研究',openalex:'学术文献索引与发表信息',huggingface:'社区收录的机器学习论文',conferences:'11 个会议的论文集索引',openreview:'ICLR / ICML / NeurIPS 已录用主会'};
let catalog, terms, page = 1, source = 'all', mode = 'search';
function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function link(text, href) { const node = element('a', text); const safe = safeLink(href); if (safe) { node.href = safe; node.target = '_blank'; node.rel = 'noopener noreferrer'; } return node; }
function formatted(value) { return value ? new Date(value).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) : '尚无成功更新'; }
function setRoute() {
  const parts = location.hash.slice(2).split('/');
  source = Object.hasOwn(sourceNames, parts[0]) ? parts[0] : 'all'; mode = parts[1] === 'daily' ? 'daily' : 'search'; page = 1;
  $('workspace-title').textContent = sourceNames[source] || '综合工作台';
  for (const node of $('sources').children) { node.classList.toggle('active', node.dataset.source === source); node.setAttribute('aria-current', node.dataset.source === source ? 'page' : 'false'); }
  for (const node of $('modes').children) { node.href = `#/${source}/${node.dataset.mode}`; node.classList.toggle('active', node.dataset.mode === mode); }
  $('search-form').hidden = mode !== 'search'; $('start-wrap').hidden = mode !== 'search'; $('end-wrap').hidden = mode !== 'search'; $('history-wrap').hidden = mode !== 'daily';
  render();
}
function paperCard(paper, index) {
  const node = element('article', undefined, 'paper');
  const meta = element('div', undefined, 'meta'); meta.append(element('span', `${index}. ${paper.date || '日期未知'}`), element('span', paper.sources.map(s => sourceNames[s]).join(' / ')),element('span', paper.date_kind || '公开日期')); node.append(meta);
  const title = element('h3'); title.append(link(paper.title, paper.evidence?.[0]?.url)); node.append(title);
  if (paper.authors?.length) node.append(element('p', paper.authors.slice(0,6).join(', ') + (paper.authors.length > 6 ? ' 等' : ''), 'muted'));
  const detail = element('details'); detail.append(element('summary', '摘要与来源详情'), element('p', paper.abstract || '该来源未提供摘要。', 'abstract'));
  for (const item of paper.evidence || []) { const row = element('p', `${sourceNames[item.source]} · ${item.conference || item.venue || '未提供会议信息'} · `); row.append(link('来源原文 ↗', item.url)); detail.append(row); }
  node.append(detail);
  const actions = element('div', undefined, 'links'); actions.append(link('查看原文 ↗', paper.evidence?.[0]?.url)); const pdf = paper.evidence?.find(e => safeLink(e.pdf_url)); if (pdf) actions.append(link('PDF ↗', pdf.pdf_url)); node.append(actions);
  return node;
}
function renderStatus() {
  $('status').replaceChildren();
  for (const key of Object.keys(sourceNames).filter(s => source === 'all' || s === source)) {
    const status = catalog.source_status[key], node = element('div');
    const label = {success:'本轮采集成功',partial:'部分查询失败',error:'本轮采集失败'}[status?.state] || '尚未采集';
    node.append(element('strong',`${sourceNames[key]} · ${label}`),element('p',`最近成功更新：${formatted(status?.updated_at)}`));
    for (const report of status?.queries || []) node.append(element('p', `${report.label}：${report.state === 'error' ? '失败' : `${report.count} 篇候选`}。${report.note}`));
    $('status').append(node);
  }
}
function emptyMessage() {
  if (!$('error').hidden) return '筛选条件无效，请按上方提示调整后重试。';
  const keys = Object.keys(sourceNames).filter(key => source === 'all' || key === source);
  if (mode === 'daily') {
    const day = catalog.history.find(h => h.date === $('history').value);
    if (!day) return '暂无已生成的每日推荐记录。请查看来源状态和最近更新时间。';
    const failed = keys.filter(key => ['error','partial'].includes(day.recommendations?.[key]?.state));
    return failed.length
      ? `所选日期暂无可显示推荐；${failed.map(key => sourceNames[key]).join('、')}采集未完成，不能据此判断当天没有论文。可切换“论文检索”查看已收录内容。`
      : '所选日期未收录符合当日日期条件的论文，不用旧论文补足。可切换“论文检索”浏览近期论文。';
  }
  const available = catalog.papers.filter(p => source === 'all' || p.sources.includes(source));
  if (available.length) return '已收录论文中没有匹配当前关键词或日期的结果。可清空关键词或放宽筛选日期；筛选不会向来源实时取数。';
  const failed = keys.filter(key => ['error','partial'].includes(catalog.source_status[key]?.state));
  if (failed.length) return `${failed.map(key => sourceNames[key]).join('、')}最近一轮采集未完成，当前没有可用论文。这不表示来源没有论文，请展开“来源状态与覆盖范围”查看原因。`;
  if (!catalog.updated_at) return '论文库尚未生成。首次部署后运行仓库中的 Update papers and deploy 工作流。';
  const scope = source === 'all' ? '当前论文库' : sourceNames[source];
  const window = catalog.lookback_days ? `最近 ${catalog.lookback_days} 天的采集窗口内` : '当前采集范围内';
  return `${scope}在${window}尚未收录论文。这不代表该来源没有论文；页面日期留空也只浏览已采集数据，不会扩大采集范围。` +
    (source === 'conferences' ? ' 顶会专区依赖 OpenAlex 的会议论文集索引，未覆盖各会议官网全集。' : '') +
    ' 可切换“全部来源”浏览其他已收录论文。';
}
function render() {
  if (!catalog) return;
  $('error').hidden = true; let papers = [];
  try {
    if (mode === 'search') {
      if ($('start').value && $('end').value && $('start').value > $('end').value) throw new Error('开始日期不能晚于结束日期。');
      const query = translateQuery($('query').value, terms);
      papers = search(catalog.papers, query, {source, start:$('start').value,end:$('end').value,sort:$('sort').value});
      $('query-note').textContent = query ? `实际关键词：${query}。在已收录标题与摘要中匹配全部关键词；可选 BM25 排序。` : `正在浏览已收录论文（采集窗口：最近 ${catalog.lookback_days || '—'} 天）。日期留空也只浏览已收录数据；不会向论文来源发起实时请求。`;
    } else {
      const day = catalog.history.find(h => h.date === $('history').value);
      const entries = Object.entries(day?.recommendations || {}).filter(([key]) => source === 'all' || key === source);
      papers = sortPapers([...new Map(entries.flatMap(([, item]) => item.papers).map(p => [p.id,p])).values()], $('sort').value);
      const failures = entries.filter(([,item]) => item.state !== 'success').map(([key]) => sourceNames[key]);
      $('query-note').textContent = `AI 当日论文：仅选来源标注日期为 ${$('history').value} 的论文，每来源最多 10 篇，综合视图合并去重。` + (failures.length ? ` 该日未完整采集：${failures.join('、')}。已有内容请结合日期查看。` : '');
    }
  } catch (error) { $('error').textContent = error.message; $('error').hidden = false; }
  const pages = Math.max(1, Math.ceil(papers.length / 10)); page = Math.min(page, pages);
  const start = (page - 1) * 10;
  $('result-summary').textContent = `共 ${papers.length} 篇 · ${papers.length ? `正在显示第 ${start + 1}–${Math.min(start + 10, papers.length)} 篇` : '当前没有可显示论文'}`;
  $('results').replaceChildren(...papers.slice(start, start + 10).map((p,i) => paperCard(p,start+i+1)));
  if (!papers.length) $('results').append(element('div', emptyMessage(), 'empty'));
  $('page-label').textContent = `第 ${page} / ${pages} 页`; $('previous').disabled = page === 1; $('next').disabled = page === pages;
  renderStatus();
}
for (const [key, name] of Object.entries({all:'全部来源',...sourceNames})) {
  const card = element('a',undefined,'source-card'); card.href = `#/${key}/search`; card.dataset.source = key;
  card.append(element('span','↗','arrow'),element('strong',name),element('small',descriptions[key]));
  card.addEventListener('pointermove', event => { const rect = card.getBoundingClientRect(); card.style.setProperty('--mx', `${event.clientX-rect.left}px`); card.style.setProperty('--my', `${event.clientY-rect.top}px`); });
  $('sources').append(card);
}
$('search-form').addEventListener('submit', event => { event.preventDefault(); page = 1; render(); });
for (const key of ['start','end','sort','history']) $(key).addEventListener('change', () => { page = 1; render(); });
for (const [key, delta] of [['previous',-1],['next',1]]) $(key).addEventListener('click', () => {page += delta; render(); $('result-summary').scrollIntoView({block:'start'});});
window.addEventListener('hashchange',setRoute);
try {
  [catalog, terms] = await Promise.all(['catalog','terms'].map(async name => { const response = await fetch(`./data/${name}.json`,{cache:'no-cache'}); if (!response.ok) throw new Error(`数据读取失败（${response.status}）`); return response.json(); }));
  if (catalog.schema !== 2 || catalog.mode !== 'ai_latest' || !Array.isArray(catalog.papers)) throw new Error('论文库格式不正确。');
  const failed = Object.values(catalog.source_status).filter(s => s.state !== 'success').length;
  $('update').textContent = `论文库更新：${formatted(catalog.updated_at)}（北京时间） · ${catalog.papers.length} 篇` + (failed ? ` · ${failed} 个来源未完整更新，详情见来源状态。` : '') + (catalog.notice ? ` · ${catalog.notice}` : '');
  for (const entry of [...catalog.history].reverse()) { const option = element('option',entry.date); option.value = entry.date; $('history').append(option); }
  $('query').value = '';
  setRoute();
} catch (error) { $('update').textContent = `无法加载论文库：${error.message} 请刷新重试。`; $('error').hidden = false; $('error').textContent = '需通过 HTTP 网页访问，不能直接双击 index.html；可使用 GitHub Pages 或本地预览服务器。'; }
