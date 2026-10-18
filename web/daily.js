// Date browsing uses the accumulated corpus, not just saved recommendation runs.
export function dailyArchive(papers, history = [], source = 'all', conference = 'all', review = 'accepted', today = '9999-12-31') {
  const saved = history.flatMap(day => [
    ...Object.values(day.recommendations || {}).flatMap(item => item.papers || []),
    ...(day.openreview_public?.papers || []),
  ]);
  const unique = new Map([...saved, ...papers].map(p => [p.id, p]));
  const days = new Map();
  for (const paper of unique.values()) {
    const groups = new Map();
    for (const e of paper.evidence || []) {
      if (source !== 'all' && e.source !== source) continue;
      if (source === 'conferences' && conference !== 'all' && e.conference !== conference) continue;
      if (e.source === 'openreview' && !(source === 'openreview' && review === 'public') && (e.review_status || 'accepted') !== 'accepted') continue;
      const date = e.source === 'arxiv' ? e.submitted_date : e.publication_date;
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date || '') || date > today) continue;
      if (!groups.has(date)) groups.set(date, []);
      groups.get(date).push(e);
    }
    for (const [date, evidence] of groups) {
      const primary = evidence[0];
      const item = {...paper, date, year: null, evidence, sources: [...new Set(evidence.map(e => e.source))],
        review_status: primary.source === 'openreview' ? primary.review_status || 'accepted' : null,
        date_kind: primary.source === 'arxiv' ? '首次提交日期' : primary.source === 'openreview' ? ((primary.review_status || 'accepted') === 'accepted' ? '录用日期' : '投稿创建日期') : '发表日期'};
      if (!days.has(date)) days.set(date, new Map());
      days.get(date).set(item.id, item);
    }
  }
  const ordered = new Map([...days].sort(([a], [b]) => b.localeCompare(a)).map(([date, items]) => [date, [...items.values()]]));
  const all = new Map();
  for (const items of ordered.values()) for (const item of items) if (!all.has(item.id)) all.set(item.id, item);
  return {days: ordered, all: [...all.values()]};
}
