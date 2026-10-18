import type { Paper } from './types';

export type PaperOrder = 'rank' | 'date_desc' | 'date_asc' | 'title';
type RankedPaper = Paper & { recommendation_score?: number };
const titles = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });

export function sortPapers<T extends RankedPaper>(papers: T[], order: PaperOrder, recommended = false): T[] {
  const date = (paper: T) => paper.date && Number.isFinite(Date.parse(paper.date)) ? paper.date.slice(0, 10) : paper.year ? `${paper.year}-00-00` : null;
  const score = (paper: T) => {
    const value = recommended ? paper.recommendation_score : paper.score;
    return typeof value === 'number' && Number.isFinite(value) ? value : -Infinity;
  };
  // Copy before sorting: preserve the saved recommendation and the server snapshot.
  return [...papers].sort((a, b) => {
    if (order === 'title') return titles.compare(a.title, b.title);
    if (order === 'rank') return score(a) === score(b) ? 0 : score(a) > score(b) ? -1 : 1;
    const left = date(a), right = date(b);
    if (left === right) return 0;
    if (!left) return 1;
    if (!right) return -1;
    return (left < right ? -1 : 1) * (order === 'date_desc' ? -1 : 1);
  });
}

export function PaperSort({ value, onChange, recommended = false }: {
  value: PaperOrder; onChange: (value: PaperOrder) => void; recommended?: boolean;
}) {
  return <div className="paper-sort-toolbar">
    <label>列表排序<select aria-label={recommended ? '推荐列表排序' : '检索结果排序'} value={value} onChange={e => onChange(e.target.value as PaperOrder)}>
      <option value="rank">{recommended ? '推荐分：从高到低' : '综合相关性：从高到低'}</option>
      <option value="date_desc">日期：从新到旧</option>
      <option value="date_asc">日期：从旧到新</option>
      <option value="title">标题：字母顺序</option>
    </select></label>
    <span>{value.startsWith('date') ? '按卡片展示日期排序，仅年份按年份排序，日期和年份均缺失时排在最后；日期含义见来源详情。' : '切换后立即重排当前列表。'}{recommended ? '不重新生成推荐。' : '不重新请求论文来源。'}</span>
  </div>;
}
