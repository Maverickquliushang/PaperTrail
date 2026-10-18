export type Source = 'arxiv' | 'openalex' | 'huggingface' | 'conferences' | 'openreview';
export const sourceNames: Record<Source, string> = { arxiv: 'arXiv', openalex: 'OpenAlex', huggingface: 'Hugging Face', conferences: '顶会索引', openreview: 'OpenReview' };
export const conferences = ['NeurIPS', 'ICML', 'ICLR', 'CVPR', 'ICCV', 'ECCV', 'ACL', 'EMNLP', 'AAAI', 'IJCAI', 'KDD'];
export const sourceDescriptions: Record<Source, string> = {
  arxiv: '预印本 · 首次提交日期',
  openalex: '学术索引 · 发表日期',
  huggingface: '社区论文 · 候选内日期筛选',
  conferences: 'OpenAlex 会议论文集 · 覆盖有限',
  openreview: 'ICLR / ICML / NeurIPS · 已录用主会',
};
export interface SearchRequest {
  query: string;
  sources: Source[];
  start_date: string | null;
  end_date: string | null;
  limit: number;
  sort: 'relevance' | 'date';
  conferences: string[];
}
export interface Evidence {
  source: Source;
  source_id: string;
  title: string;
  abstract: string | null;
  doi: string | null;
  arxiv_id: string | null;
  url: string;
  pdf_url: string | null;
  venue: string | null;
  conference?: string | null;
  publication_date: string | null;
  submitted_date: string | null;
  updated_date: string | null;
  listed_date: string | null;
  retrieved_at: string;
  cached: boolean;
}
export interface Paper {
  score?: number;
  id: string;
  title: string;
  authors: string[];
  abstract: string | null;
  abstract_source: Source | null;
  date: string | null;
  date_kind: string;
  date_source: Source;
  doi: string | null;
  arxiv_id: string | null;
  sources: Source[];
  evidence: Evidence[];
}
export interface SourceStatus {
  source: Source;
  state: 'pending' | 'running' | 'success' | 'limited' | 'error' | 'cancelled';
  count: number;
  total: number | null;
  scanned: number;
  note: string;
  error_code: string | null;
  cached_at: string | null;
  retrieved_at: string | null;
}
export interface Snapshot {
  id: string;
  request: SearchRequest;
  started_at: string;
  done: boolean;
  sources: SourceStatus[];
  papers: Paper[];
  raw_count: number;
  merged_count: number;
}
