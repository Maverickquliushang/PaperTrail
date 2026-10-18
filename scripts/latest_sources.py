"""Public AI category/feed collection; no personal keyword queries."""
import json
from backend.conferences import CONFERENCE_SOURCES, OPENREVIEW_GROUPS
from backend.models import SourceData, now
from backend.sources import (Providers, SourceError, parse_arxiv, parse_openalex,
                             parse_huggingface, parse_openreview)


class LatestData(SourceData):
    partial: bool = False


class LatestProviders(Providers):
    async def latest(self, source, start, end, limit):
        stamp = now()
        partial = False
        if source == 'arxiv':
            categories = ' OR '.join('cat:' + c for c in ('cs.AI', 'cs.LG', 'cs.CL', 'cs.CV', 'cs.NE', 'stat.ML'))
            body = await self.request(source, 'https://export.arxiv.org/api/query', {
                'search_query': f'({categories}) AND submittedDate:[{start:%Y%m%d}0000 TO {end:%Y%m%d}2359]',
                'start': 0, 'max_results': limit, 'sortBy': 'submittedDate', 'sortOrder': 'descending'})
            records, total = parse_arxiv(body, stamp)
            note = 'AI、机器学习、语言、视觉、神经计算分类；日期为首次提交日（UTC）。'
        elif source in ('openalex', 'conferences'):
            lookup = {identifier: name for name, ids in CONFERENCE_SOURCES.items() for identifier in ids}
            scope = ('primary_location.source.id:' + '|'.join(lookup) if source == 'conferences'
                     else 'primary_topic.subfield.id:1702')
            body = await self.request(source, 'https://api.openalex.org/works', {
                'filter': f'{scope},from_publication_date:{start},to_publication_date:{end}',
                'sort': 'publication_date:desc', 'per_page': limit})
            data = json.loads(body)
            records, total = parse_openalex(data, stamp)
            if source == 'conferences':
                for record, item in zip(records, data['results']):
                    identifier = ((item.get('primary_location') or {}).get('source') or {}).get('id', '').rsplit('/', 1)[-1]
                    record.source = source
                    record.conference = lookup.get(identifier)
                records = [r for r in records if r.conference]
            note = ('11 个 AI 会议的 OpenAlex 论文集索引，覆盖有限。' if source == 'conferences'
                    else 'OpenAlex 主主题属于 Artificial Intelligence 子领域（1702）。') + '日期为索引发表日。'
        elif source == 'huggingface':
            # Current and previous month cover a 30-day window across month boundaries.
            months = sorted({str(start)[:7], str(end)[:7]})
            records, successes = [], 0
            for month in months:
                try:
                    body = await self.request(source, 'https://huggingface.co/api/daily_papers', {
                        'month': month, 'limit': limit, 'sort': 'publishedAt'})
                    records.extend(parse_huggingface(json.loads(body), stamp))
                    successes += 1
                except SourceError:
                    partial = True
            if not successes:
                raise SourceError('feed_unavailable', 'Hugging Face 社区论文列表请求失败。')
            total = None
            note = 'Hugging Face 月度 Daily Papers 候选；日期使用原论文 publishedAt，社区收录日不作为发表日。'
        else:
            records, successes = [], 0
            for year in (end.year - 1, end.year):
                for name, group in OPENREVIEW_GROUPS.items():
                    try:
                        body = await self.request(source, 'https://api2.openreview.net/notes', {
                            'content.venueid': f'{group}/{year}/Conference', 'sort': 'pdate:desc', 'limit': limit})
                        records.extend(parse_openreview(json.loads(body), stamp, [name]))
                        successes += 1
                    except SourceError:
                        partial = True
            if not successes:
                raise SourceError('feed_unavailable', 'OpenReview 已录用会议列表请求失败。')
            total = None
            note = '最近两年 ICLR / ICML / NeurIPS 已录用主会候选；日期为 pdate（录用日期），不代表当天新投稿。'
        scanned = len(records)
        records = list({r.source_id: r for r in records if r.filter_date and str(start) <= r.filter_date <= str(end)}.values())
        records.sort(key=lambda r: (r.filter_date, r.source_id), reverse=True)
        if partial:
            note += '部分子请求失败，当前仅展示成功返回的候选。'
        note += f' 每个列表至多读取 {limit} 条候选，不保证全量覆盖。'
        return LatestData(records=records[:limit], total=total, scanned=scanned,
                          limited=total is None or total > limit, partial=partial,
                          note=note, retrieved_at=stamp)
