import {sourceNames,reviewNames,safeLink} from './search.js';
import {createShardLoader} from './browse.js';
import {paperCacheKey,findPaper} from './paper-data.js';

const $=id=>document.getElementById(id), params=new URLSearchParams(location.search);
const local=params.has('local') && location.pathname.startsWith('/library/');
const id=params.get(local?'local':'id');
function el(tag,text,className) {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;}
function external(text,url) {const safe=safeLink(url);if(!safe)return null;const a=el('a',text);a.href=safe;a.target='_blank';a.rel='noopener noreferrer';return a;}
function links(evidence) {
  const row=el('div',undefined,'links');
  const seen=new Set();
  for(const e of evidence) for(const [label,url] of [['查看原文 ↗',e.url],['PDF ↗',e.pdf_url]]) {
    const a=external(label,url);if(a && !seen.has(a.href)){row.append(a);seen.add(a.href);}
  }
  return row;
}
function render(paper) {
  document.title=`${paper.title} · PaperTrail`;
  const article=$('paper-detail');article.replaceChildren();article.hidden=false;
  article.append(el('p',(paper.sources || []).map(s=>sourceNames[s] || s).join(' / '),'muted'),el('h1',paper.title),el('p',(paper.authors || []).join(' · ') || '作者未提供','authors'));
  article.append(el('p',`${paper.date || (paper.year?`${paper.year}（仅年份）`:'日期未提供')} · ${paper.date_kind || '来源日期'}`,'muted'));
  if(paper.review_status)article.append(el('p',reviewNames[paper.review_status] || '状态未确认','review-badge'));
  article.append(links((paper.evidence || []).slice(0,1)));
  const abstract=el('section',undefined,'paper-section');abstract.append(el('h2','摘要'),el('p',paper.abstract || '该来源未提供摘要，请通过原文链接查看。','abstract'));article.append(abstract);
  const identifiers=[paper.doi && `DOI: ${paper.doi}`,paper.arxiv_id && `arXiv: ${paper.arxiv_id}`].filter(Boolean);
  if(identifiers.length)article.append(el('p',identifiers.join(' · '),'identifiers'));
  const sources=el('section',undefined,'paper-section');sources.append(el('h2','来源与时间记录'),el('p','各来源的日期含义不同；公开投稿不等于已录用。未提供的信息不会补造。','muted'));
  for(const e of paper.evidence || []) {
    const block=el('section',undefined,'paper-source');block.append(el('h3',e.index_provider || sourceNames[e.source] || e.source));
    const fields=[['来源标题',e.title || paper.title],['会议 / 会刊',e.conference || e.venue],['会议 / 出版年份',e.publication_year],['首次提交',e.submitted_date],['发表 / 公开日期',e.publication_date],['更新日期',e.updated_date],['社区收录',e.listed_date],['来源状态',e.review_status?(reviewNames[e.review_status] || '状态未确认'):null],['采集时间',e.retrieved_at]];
    const dl=el('dl');for(const [label,value] of fields)if(value){dl.append(el('dt',label),el('dd',String(value)));}
    block.append(dl,links([e]));sources.append(block);
  }
  article.append(sources);
}

const from=params.get('from') || '';
const safeFrom=/^#\/[a-zA-Z0-9/_-]*$/.test(from)?from:'';
const fallback=(local?'/':'./')+safeFrom;
$('back-link').href=fallback;
if(document.referrer)try {
  const ref=new URL(document.referrer);
  if(ref.origin===location.origin && ref.pathname!==location.pathname){
    if(!safeFrom)$('back-link').href=ref.href;
    $('back-link').addEventListener('click',event=>{if(!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&event.button===0){event.preventDefault();history.back();}});
  }
} catch {}

async function main() {
  $('paper-retry').hidden=true;
  if(!id){$('paper-status').textContent='缺少论文标识，请返回列表选择论文。';return;}
  if(local) {
    try {
      const saved=JSON.parse(sessionStorage.getItem(paperCacheKey(id)) || 'null');
      if(saved?.id===id){render(saved);$('paper-status').textContent='来自本次本地检索 / 推荐的论文记录。';return;}
    } catch {}
    $('paper-status').textContent='本次检索记录已失效，请返回本地工作台重新检索或打开推荐，再进入论文详情。';return;
  }
  try {
    const response=await fetch('./data/catalog.json',{cache:'no-cache'});
    if(!response.ok)throw new Error('论文库清单加载失败，请重试。');
    const catalog=await response.json();
    if(catalog.schema!==2)throw new Error('论文库格式不正确，请重试。');
    const paper=await findPaper(catalog,params,createShardLoader(),(done,total)=>{$('paper-status').textContent=`正在定位论文 · ${done}/${total} 个候选分片`;});
    if(paper){render(paper);$('paper-status').textContent='本站已收录的论文详情';}
    else $('paper-status').textContent='当前论文库中未找到这篇论文，记录可能已合并或更新，请返回列表重新查找。';
  } catch(error){$('paper-status').textContent=error.message;$('paper-retry').hidden=false;}
}
$('paper-retry').addEventListener('click',main);
main();
