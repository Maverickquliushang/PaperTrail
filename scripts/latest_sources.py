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
    async def daily_pages(self, source, end):
        records, offset, cursor = [], 0, '*'
        while True:
            if source == 'arxiv':
                categories = ' OR '.join('cat:' + c for c in ('cs.AI','cs.LG','cs.CL','cs.CV','cs.NE','stat.ML'))
                body = await self.request(source,'https://export.arxiv.org/api/query',{
                    'search_query':f'({categories}) AND submittedDate:[{end:%Y%m%d}0000 TO {end:%Y%m%d}2359]',
                    'start':offset,'max_results':100,'sortBy':'submittedDate','sortOrder':'ascending'})
                batch,total = parse_arxiv(body,now())
                if not batch and offset < total: raise SourceError('incomplete_page','当日分页提前为空，未完整采集。')
                records.extend(batch); offset += len(batch)
                if offset >= total: break
            else:
                payload = json.loads(await self.request(source,'https://api.openalex.org/works',{
                    'filter':f'primary_topic.subfield.id:1702,from_publication_date:{end},to_publication_date:{end}',
                    'sort':'publication_date:asc','per_page':100,'cursor':cursor}))
                batch,total = parse_openalex(payload,now())
                records.extend(batch)
                next_cursor = payload.get('meta',{}).get('next_cursor')
                if not next_cursor: break
                if next_cursor == cursor: raise SourceError('invalid_cursor','当日分页游标重复，未完整采集。')
                cursor = next_cursor
        return records

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
            return await self.huggingface_catalog(end)
        else:
            return await self.openreview_catalog(end, limit)
        if source in ('arxiv','openalex'):
            try:
                records.extend(await asyncio.wait_for(self.daily_pages(source,end),180))
            except (SourceError,asyncio.TimeoutError):
                partial = True
        scanned = len(records)
        records = list({r.source_id: r for r in records if r.filter_date and r.filter_date <= str(end)}.values())
        records.sort(key=lambda r: (r.filter_date, r.source_id), reverse=True)
        if partial:
            note += '部分子请求失败，当前仅展示成功返回的候选。'
        note += f' 近期检索种子每列表读取 {limit} 条；arXiv / OpenAlex 当日列表另行分页读取，不限制推荐展示数量。'
        return LatestData(records=records, total=total, scanned=scanned,
                          limited=total is None or total > limit, partial=partial,
                          note=note, retrieved_at=stamp)

    async def huggingface_page(self, cursor):
        from urllib.parse import urlparse, parse_qs
        await asyncio.sleep(.3)
        params={'limit':100}
        if cursor:params['cursor']=cursor
        async with self.client.stream('GET','https://huggingface.co/api/papers',params=params,timeout=40) as response:
            if response.status_code in (401,403,429):
                raise SourceError('rate_limited' if response.status_code==429 else 'access_denied','Hugging Face 访问受限，保留断点后重试。')
            if response.status_code != 200:raise SourceError('http_error','Hugging Face 请求失败，保留断点。')
            body=bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body)>8*1024*1024:raise SourceError('response_too_large','Hugging Face 单页响应过大，未推进断点。')
            rows=json.loads(body)
            if not isinstance(rows,list):raise ValueError('Expected papers')
            next_link=response.links.get('next',{}).get('url')
            following=None
            if next_link:
                url=urlparse(next_link)
                if url.scheme!='https' or url.netloc!='huggingface.co' or url.path!='/api/papers':raise ValueError('Unexpected next link')
                following=parse_qs(url.query).get('cursor',[None])[0]
                if not following:raise ValueError('Missing cursor')
            return rows,following

    async def huggingface_catalog(self,end):
        from scripts.huggingface_sync import synchronize
        state=getattr(self,'source_state',{})
        records,entry=await synchronize(self,end,state.get('huggingface'),seconds=getattr(self,'huggingface_seconds',180))
        state['huggingface']=entry;self.source_state=state
        status='partial' if entry.get('pending') or entry.get('error') else 'success'
        note=entry.get('error') or ('历史分页进行中，将从断点自动续采。' if entry['pending'] else '本轮官方论文列表已遍历。')
        note+=f" 已检查 {entry['scanned']} 条、{entry['pages']} 页；无 200 篇或两个月收录上限。"
        return LatestData(records=records,retrieved_at=now(),partial=status!='success',reports=[{
            'label':'Hugging Face 全论文列表','state':status,'count':len(records),'note':note}],scanned=len(records),note=note)

    async def conference_catalog(self, end, limit):
        from scripts.conference_sync import synchronize
        records, reports, state = await synchronize(self, end, getattr(self, 'conference_state', {}),
            seconds=getattr(self, 'conference_seconds', 600))
        self.conference_state = state
        return LatestData(records=records, reports=reports, retrieved_at=now(), scanned=len(records),
                          partial=any(r['state'] in ('error','partial') for r in reports),
                          note='分页补采历史并保留断点；收录总量不设篇数上限。')

    async def dblp_query(self, query):
        # Public official query service. No OpenAlex headers or private credentials are sent.
        await asyncio.sleep(.3)
        async with self.client.stream('GET','https://sparql.dblp.org/sparql',
            params={'query':query,'format':'json'},headers={'Accept':'application/sparql-results+json'},timeout=60) as response:
            if response.status_code == 429:
                raise SourceError('rate_limited','DBLP 查询服务限流，保留已完成页面，次日重试。')
            if response.status_code != 200 or 'json' not in response.headers.get('content-type',''):
                raise SourceError('dblp_unavailable','DBLP 官方查询服务暂时不可用，保留断点，不绕过访问验证。')
            body=bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body)>16*1024*1024:raise SourceError('response_too_large','DBLP 单页响应异常过大，保留断点。')
        data=json.loads(body)
        if not isinstance(data.get('results',{}).get('bindings'),list):raise SourceError('invalid_response','DBLP 查询响应格式异常。')
        return data

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
                            parsed = [PublicRecord(**(r.model_dump() | {'review_status':'accepted','index_provider':'OpenReview'}))
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
