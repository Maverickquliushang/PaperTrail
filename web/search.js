export const sourceNames = { arxiv: 'arXiv', openalex: 'OpenAlex', huggingface: 'Hugging Face', conferences: '顶会索引', openreview: 'OpenReview' };

export function translateQuery(raw, terms) {
  let query = raw.trim();
  if (!Object.hasOwn(terms, query)) query = query.replace(/^(?:请)?(?:帮我|给我)?(?:检索|搜索|查找|搜|找|查)(?:一下)?[\s：:]*/, '');
  query = query.replace(/[，。！？?!]+$/, '').replace(/^(?:关于|有关)/, '').replace(/(?:的)?(?:相关的论文|相关论文|相关研究|方面的论文|方面的研究|论文|研究)$/, '');
  const keys = Object.keys(terms).sort((a, b) => b.length - a.length);
  if (keys.length) query = query.replace(new RegExp(keys.join('|'), 'g'), term => ` ${terms[term]} `);
  query = query.replace(/(?<=[A-Za-z0-9])\s*(?:的|和|与|以及)\s*(?=[A-Za-z0-9])/g, ' ');
  if (/[\u3400-\u9fff]/.test(query)) throw new Error('还有无法转换的中文限定，请换用英文表达；没有忽略这些条件。');
  return query.replace(/\s+/g, ' ').trim();
}

export function tokens(text) {
  return (text.toLowerCase().match(/[a-z0-9]+/g) || []).flatMap(word => {
    if (word === 'llm' || word === 'llms') return ['large', 'language', 'model'];
    if (word === 'svd') return ['singular', 'value', 'decomposition'];
    return [word.length > 3 && word.endsWith('s') && !word.endsWith('ss') ? word.slice(0, -1) : word];
  });
}

// Okapi BM25 over title + abstract; every query token is required to avoid a
// generic 'model' hit being mistaken for 'large language model low rank'.
export function search(papers, query, {source = 'all', start = '', end = '', sort = 'date_desc'} = {}) {
  const words = [...new Set(tokens(query))];
  const docs = papers.map(p => tokens(`${p.title} ${p.abstract || ''}`));
  const average = docs.reduce((n, d) => n + d.length, 0) / (docs.length || 1) || 1;
  const frequency = new Map(words.map(w => [w, docs.filter(d => d.includes(w)).length]));
  const results = papers.flatMap((paper, i) => {
    if (source !== 'all' && !paper.sources.includes(source)) return [];
    if (start && (!paper.date || paper.date < start) || end && (!paper.date || paper.date > end)) return [];
    if (!words.every(w => docs[i].includes(w))) return [];
    const score = words.reduce((sum, w) => {
      const tf = docs[i].filter(t => t === w).length, df = frequency.get(w);
      return sum + Math.log(1 + (papers.length - df + .5) / (df + .5)) * tf * 2.2 / (tf + 1.2 * (.25 + .75 * docs[i].length / average));
    }, 0);
    return [{...paper, bm25: score}];
  });
  return sortPapers(results, sort);
}

export function sortPapers(papers, sort) {
  return [...papers].sort((a, b) => {
    if (sort === 'title') return a.title.localeCompare(b.title);
    if (sort === 'relevance') return (b.bm25 || 0) - (a.bm25 || 0) || (b.date || '').localeCompare(a.date || '');
    if (!a.date || !b.date) return Number(!a.date) - Number(!b.date);
    return sort === 'date_asc' ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date);
  });
}

export function safeLink(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username ? url.href : null; }
  catch { return null; }
}
