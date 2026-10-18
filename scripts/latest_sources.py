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
        from scripts.bibliography_sync import synchronize
        state=getattr(self,'source_state',{})
        historical,entry=await synchronize(self,source,end,state.get(source),seconds=getattr(self,'bibliography_seconds',120))
        state[source]=entry;self.source_state=state
        records.extend(historical)
        partial = partial or entry['pending'] or bool(entry.get('error'))
        note += f" 历史分页已检查 {entry['scanned']} 条、{entry['pages']} 页；边界日期 {entry['boundary']}。" + (entry.get('error') or ('将从断点继续补采，无累计篇数上限。' if entry['pending'] else '本轮历史列表已遍历。'))
        scanned = len(records)
        records = list({r.source_id: r for r in records if r.filter_date and r.filter_date <= str(end)}.values())
        records.sort(key=lambda r: (r.filter_date, r.source_id), reverse=True)
        if partial:
            note += '采集尚未完成，当前展示已成功收录的论文。'
        note += f' 近期检索种子每列表读取 {limit} 条；arXiv / OpenAlex 当日列表另行分页读取，不限制推荐展示数量。'
        return LatestData(records=records, total=total, scanned=scanned,
                          limited=entry['pending'], partial=partial,
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
        import time
        from datetime import timedelta
        states=getattr(self,'source_state',{})
        state=states.setdefault('openreview',{'end':str(end),'jobs':{},'pending':True})
        if state.get('end')!=str(end) and not state.get('pending'):
            states['openreview']=state={'end':str(end),'jobs':{},'pending':True}
        self.source_state=states
        if state.get('retry_after','')>str(end):
            return LatestData(records=[],reports=[{'label':'OpenReview','state':'error','count':0,'note':state.get('error','等待来源恢复')}],partial=True,retrieved_at=now())
        records,reports={},[]
        unavailable=None;deadline=time.monotonic()+120
        for name,group in OPENREVIEW_GROUPS.items():
            for year in range(end.year-2,end.year+2):
                venue=f'{group}/{year}/Conference'
                for view in ('accepted','public'):
                    if view=='accepted' and year>end.year:continue
                    label=f'{name} {year} · '+('已录用' if view=='accepted' else '公开投稿')
                    job=state['jobs'].setdefault(label,{'offset':0,'complete':False,'pages':0})
                    count=0
                    try:
                        if unavailable:raise SourceError('access_denied',unavailable)
                        if not job['complete'] and time.monotonic()<deadline:
                            if view=='accepted':
                                params={'content.venueid':venue,'sort':'pdate:desc','limit':100}
                                parse=lambda payload:[PublicRecord(**(r.model_dump()|{'review_status':'accepted','index_provider':'OpenReview'})) for r in parse_openreview(payload,now(),[name])]
                            else:
                                group_data=json.loads(await self.request('openreview','https://api2.openreview.net/groups',{'id':venue}))
                                groups=group_data.get('groups',[])
                                if not groups:
                                    job['complete']=True
                                    reports.append({'label':label,'view':view,'state':'success','count':0,'note':'该年度会议组尚未公开或不存在。'})
                                    continue
                                content=groups[0].get('content',{});submission=value(content,'submission_name')
                                if not submission:raise SourceError('missing_schema','会议未公开投稿入口名称，未猜测接口。')
                                invitation=f'{venue}/-/{submission}'
                                mapping={value(content,key):status for key,status in (('submission_venue_id','under_review'),('withdrawn_venue_id','withdrawn'),('rejected_venue_id','rejected'),('desk_rejected_venue_id','desk_rejected')) if value(content,key)}
                                params={'invitation':invitation,'sort':'cdate:desc','limit':100}
                                parse=lambda payload:parse_public_submissions(payload,name,venue,invitation,mapping,now())
                            while not job['complete'] and time.monotonic()<deadline:
                                payload=json.loads(await asyncio.wait_for(self.request('openreview','https://api2.openreview.net/notes',{**params,'offset':job['offset']}),max(.001,deadline-time.monotonic())))
                                raw=payload.get('notes')
                                if not isinstance(raw,list):raise ValueError('Missing notes')
                                if raw and raw[0].get('id') and raw[0]['id']==job.get('first_id'):raise SourceError('invalid_page','OpenReview 重复返回上一页，保留断点。')
                                parsed=parse(payload)
                                for record in parsed:
                                    if not record.filter_date or record.filter_date<=str(end):records[record.source_id]=record;count+=1
                                job.update(offset=job['offset']+len(raw),pages=job['pages']+1,first_id=raw[0].get('id') if raw else None)
                                job['complete']=len(raw)<100 or (isinstance(payload.get('count'),int) and job['offset']>=payload['count'])
                        reports.append({'label':label,'view':view,'state':'success' if job['complete'] else 'partial','count':count,'note':f"已检查 {job['offset']} 条、{job['pages']} 页；"+('该会议年度查询已完成。' if job['complete'] else '保存断点后继续，无 100 篇总量截断。')})
                    except asyncio.TimeoutError:
                        reports.append({'label':label,'view':view,'state':'partial','count':count,'note':'本轮保存断点，后续继续分页。'})
                    except Exception as exc:
                        note=exc.message if isinstance(exc,SourceError) else 'OpenReview 本轮请求失败，保留断点。'
                        if isinstance(exc,SourceError) and exc.code in ('access_denied','rate_limited'):
                            unavailable=note;state['error']=note;state['retry_after']=str(end+timedelta(days=1))
                        reports.append({'label':label,'view':view,'state':'error','count':count,'note':note})
        state['pending']=any(not j['complete'] for j in state['jobs'].values())
        if not unavailable:state.pop('error',None);state.pop('retry_after',None)
        return LatestData(records=list(records.values()),reports=reports,retrieved_at=now(),partial=any(r['state']!='success' for r in reports),note='支持的会议年度逐页读取；不含未接入的历史 API v1 数据。')
