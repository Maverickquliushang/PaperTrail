import {selectShards} from './browse.js';

export const paperCacheKey = id => `papertrail:paper:${id}`;
export function paperHref(paper, shard = '') {
  const params = new URLSearchParams({id:paper.id});
  if (shard) params.set('shard',shard);
  if (paper.sources?.[0]) params.set('source',paper.sources[0]);
  if (paper.date) params.set('date',paper.date);
  if (paper.year) params.set('year',paper.year);
  return `./paper.html?${params}`;
}

// A stale content-addressed hint is safe to ignore: scan the current manifest.
// Never fetch arbitrary paths supplied in the URL. Stop as soon as the ID is found.
export async function findPaper(catalog, params, load, progress = () => {}) {
  const id=params.get('id');
  const inline=(catalog.papers || []).find(p=>p.id===id);
  if (inline) return inline;
  const shards=catalog.paper_shards || [];
  const hint=shards.find(s=>s.file===params.get('shard'));
  const preferred=selectShards(catalog,{source:params.get('source') || 'all',date:params.get('date') || '',year:params.get('year') || ''});
  const ordered=[...new Map([...(hint?[hint]:[]),...preferred,...shards].map(s=>[s.file,s])).values()];
  let failed=false;
  for (let i=0;i<ordered.length;i++) {
    progress(i+1,ordered.length);
    try {
      const rows=await load([ordered[i]]);
      const paper=rows.find(p=>p.id===id);
      if (paper) return paper;
    } catch { failed=true; }
  }
  if (failed) throw new Error('部分论文数据未能加载，暂时无法确认这篇论文。请重试。');
  return null;
}
