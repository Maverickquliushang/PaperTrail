import { sourceDescriptions, sourceNames, type Source } from './types';

const introductions: Record<Source, string> = {
  arxiv: '追踪各学科的预印本研究，从原始论文发现新方法。',
  openalex: '连接广泛的学术文献索引，补充发表信息和论文出处。',
  huggingface: '探索 Hugging Face 收录的机器学习论文与社区讨论。',
  conferences: '按会议论文集筛选 NeurIPS、CVPR、ACL 等 11 个会议，覆盖受索引限制。',
  openreview: '直接连接 OpenReview，检索 ICLR、ICML、NeurIPS 已录用主会论文。',
};

export function SourceCard({ source, index, mode = 'search' }: {
  source: Source; index: number; mode?: 'search' | 'daily';
}) {
  return <a className={`source-card ${source}`} href={`#/sources/${source}/${mode}`}
    aria-label={`进入 ${sourceNames[source]} 专区`}
    onPointerMove={event => {
      if (event.pointerType !== 'mouse') return;
      const box = event.currentTarget.getBoundingClientRect();
      event.currentTarget.style.setProperty('--pointer-x', `${event.clientX - box.left}px`);
      event.currentTarget.style.setProperty('--pointer-y', `${event.clientY - box.top}px`);
    }}>
    <span className="source-number">{String(index + 1).padStart(2, '0')}<span className={`source-dot ${source}`} /></span>
    <span className="source-card-title">{sourceNames[source]}</span>
    <span className="source-card-description">{introductions[source]}</span>
    <span className="source-card-meta">{sourceDescriptions[source]}</span>
    <span className="source-card-action"><span>进入专区 · 检索与每日推荐</span><span className="source-card-arrow" aria-hidden="true">→</span></span>
  </a>;
}
