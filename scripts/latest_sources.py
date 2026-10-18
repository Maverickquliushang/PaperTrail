"""Public AI category/feed collection; no personal keyword queries."""
import json
import asyncio
from scripts.public_records import PublicRecord, DBLP_STREAMS, parse_dblp, parse_public_submissions, value
from pydantic import Field
from backend.conferences import CONFERENCE_SOURCES, OPENREVIEW_GROUPS
from backend.models import SourceData, now
from backend.sources import (Providers, SourceError, parse_arxiv, parse_openalex,
                             parse_huggingface, parse_openreview)


class LatestData(SourceData):
    partial: bool = False
    reports: list[dict] = Field(default_factory=list)


class LatestProviders(Providers):
    async def latest(self, source, start, end, limit):
        stamp = now()
        partial = False
        if source == 'arxiv':
            categories = ' OR '.join('cat:' + c for c in ('cs.AI', 'cs.LG', 'cs.CL', 'cs.CV', 'cs.NE', 'stat.ML'))
            body = await self.request(source, 'https://export.arxiv.org/api/query', {
                'search_query': f'({categories}) AND submittedDate:[199101010000 TO {end:%Y%m%d}2359]',
                'start': 0, 'max_results': limit, 'sortBy': 'submittedDate', 'sortOrder': 'descending'})
            records, total = parse_arxiv(body, stamp)
            note = 'AI、机器学习、语言、视觉、神经计算分类；日期为首次提交日（UTC）。'
        elif source == 'conferences':
            return await self.conference_catalog(end, limit)
        elif source == 'openalex':
            body = await self.request(source, 'https://api.openalex.org/works', {
                'filter': f'primary_topic.subfield.id:1702,to_publication_date:{end}',
                'sort': 'publication_date:desc', 'per_page': limit})
            records, total = parse_openalex(json.loads(body), stamp)
            note = 'OpenAlex 主主题属于 Artificial Intelligence 子领域（1702）。日期为索引发表日。'
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
            return await self.openreview_catalog(end, limit)
        scanned = len(records)
        records = list({r.source_id: r for r in records if r.filter_date and r.filter_date <= str(end)}.values())
        records.sort(key=lambda r: (r.filter_date, r.source_id), reverse=True)
        if partial:
            note += '部分子请求失败，当前仅展示成功返回的候选。'
        note += f' 每个列表至多读取 {limit} 条候选，不保证全量覆盖。'
        return LatestData(records=records[:limit], total=total, scanned=scanned,
                          limited=total is None or total > limit, partial=partial,
                          note=note, retrieved_at=stamp)

    async def conference_catalog(self, end, limit):
        """Query each venue independently, with no lower publication-date bound."""
        records, reports = [], []
        stamp = now()
        for name, identifiers in CONFERENCE_SOURCES.items():
            try:
                body = await self.request('conferences', 'https://api.openalex.org/works', {
                    'filter': f'primary_location.source.id:{"|".join(identifiers)},to_publication_date:{end}',
                    'sort': 'publication_date:desc', 'per_page': limit})
                payload = json.loads(body)
                parsed, total = parse_openalex(payload, stamp)
                accepted = []
                for record, item in zip(parsed, payload['results']):
                    identifier = ((item.get('primary_location') or {}).get('source') or {}).get('id', '').rsplit('/', 1)[-1]
                    if identifier in identifiers and record.filter_date and record.filter_date <= str(end):
                        record.source, record.conference = 'conferences', name
                        accepted.append(record)
                records.extend(accepted)
                reports.append({'conference': name, 'index_provider': 'OpenAlex', 'label': name + ' · OpenAlex',
                                'state': 'limited' if total > limit else 'success',
                                'count': len(accepted), 'total': total,
                                'note': f'不设起始日期；本轮取该会议最新至多 {limit} 篇。仅代表 OpenAlex 论文集索引，非会议官网全集。'})
            except Exception as exc:
                reports.append({'conference': name, 'index_provider': 'OpenAlex', 'label': name + ' · OpenAlex', 'state': 'error', 'count': 0,
                                'note': exc.message if isinstance(exc, SourceError) else '会议索引请求未完成，请稍后重试。'})
        dblp_records, dblp_reports = await self.dblp_catalog(end, limit)
        records.extend(dblp_records)
        reports.extend(dblp_reports)
        return LatestData(records=records, reports=reports, retrieved_at=stamp,
                          scanned=len(records), partial=any(r['state'] == 'error' for r in reports),
                          limited=any(r['state'] == 'limited' for r in reports),
                          note='分会议采集，不设起始日期；历史记录不因超过 30 天而移除。')

    async def dblp_body(self, params):
        # Never reuse the OpenAlex request helper: its Authorization header is host-specific.
        await asyncio.sleep(1)
        async with self.client.stream('GET', 'https://dblp.org/search/publ/api', params=params, timeout=20) as response:
            if response.status_code != 200 or 'json' not in response.headers.get('content-type', ''):
                raise SourceError('dblp_unavailable', 'DBLP 当前返回访问验证或不可用响应；未取得论文数据，可打开 DBLP 会议目录查看。')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 8 * 1024 * 1024:
                    raise SourceError('response_too_large', 'DBLP 响应超过本次大小上限。')
        return json.loads(body)

    async def dblp_catalog(self, end, limit):
        records, reports, unavailable = [], [], None
        for name, stream in DBLP_STREAMS.items():
            try:
                if unavailable:
                    raise SourceError('dblp_unavailable', unavailable)
                payload = await self.dblp_body({'q': f'stream:conf/{stream}:', 'format': 'json', 'h': limit})
                parsed, total = parse_dblp(payload, name, now(), end.year)
                records.extend(parsed)
                reports.append({'conference': name, 'index_provider': 'DBLP', 'label': name + ' · DBLP',
                                'state': 'limited' if total > limit else 'success', 'count': len(parsed), 'total': total,
                                'note': f'不设起始日期；本轮读取至多 {limit} 条会议流候选。仅提供年份时不补造月日、不进入当日推荐；摘要通常缺失。'})
            except Exception as exc:
                unavailable = exc.message if isinstance(exc, SourceError) else 'DBLP 本轮请求失败，后续会议暂缓请求；可打开 DBLP 会议目录。'
                reports.append({'conference': name, 'index_provider': 'DBLP', 'label': name + ' · DBLP',
                                'state': 'error', 'count': 0, 'note': unavailable})
        return records, reports

    async def openreview_catalog(self, end, limit):
        records, reports = {}, []
        unavailable = None
        for year in (end.year - 1, end.year, end.year + 1):
            for name, group in OPENREVIEW_GROUPS.items():
                venue = f'{group}/{year}/Conference'
                for view in ('accepted', 'public'):
                    if view == 'accepted' and year > end.year:
                        continue
                    label = f'{name} {year} · ' + ('已录用' if view == 'accepted' else '公开投稿')
                    try:
                        if unavailable:
                            raise SourceError('access_denied', unavailable)
                        if view == 'accepted':
                            payload = json.loads(await self.request('openreview', 'https://api2.openreview.net/notes', {
                                'content.venueid': venue, 'sort': 'pdate:desc', 'limit': limit}))
                            parsed = [PublicRecord(**r.model_dump(), review_status='accepted', index_provider='OpenReview')
                                      for r in parse_openreview(payload, now(), [name])]
                        else:
                            group_data = json.loads(await self.request('openreview', 'https://api2.openreview.net/groups', {'id': venue}))
                            groups = group_data.get('groups', [])
                            if not groups:
                                reports.append({'label': label, 'view': view, 'state': 'success', 'count': 0, 'note': '该年度会议组尚未公开或不存在。'})
                                continue
                            content = groups[0].get('content', {})
                            submission = value(content, 'submission_name')
                            if not submission:
                                raise SourceError('missing_schema', '会议未公开投稿入口名称，未猜测接口。')
                            invitation = f'{venue}/-/{submission}'
                            mapping = {value(content, key): status for key, status in (
                                ('submission_venue_id','under_review'), ('withdrawn_venue_id','withdrawn'),
                                ('rejected_venue_id','rejected'), ('desk_rejected_venue_id','desk_rejected')) if value(content, key)}
                            payload = json.loads(await self.request('openreview', 'https://api2.openreview.net/notes', {
                                'invitation': invitation, 'sort': 'cdate:desc', 'limit': limit}))
                            parsed = parse_public_submissions(payload, name, venue, invitation, mapping, now())
                        parsed = [r for r in parsed if not r.filter_date or r.filter_date <= str(end)]
                        for r in parsed:
                            records[r.source_id] = r
                        reports.append({'label': label, 'view': view, 'state': 'limited', 'count': len(parsed),
                                        'note': f'至多 {limit} 条公开候选，不设起始日期；仅按来源明确提供的状态标注，未知状态不视为在审。'})
                    except Exception as exc:
                        note = exc.message if isinstance(exc, SourceError) else 'OpenReview 本轮请求失败。'
                        if isinstance(exc, SourceError) and exc.code in ('access_denied','rate_limited'):
                            unavailable = note
                        reports.append({'label': label, 'view': view, 'state': 'error', 'count': 0, 'note': note})
        return LatestData(records=list(records.values()), reports=reports, retrieved_at=now(), limited=True,
                          partial=any(r['state'] == 'error' for r in reports), note='已录用与公开投稿分开浏览。')
