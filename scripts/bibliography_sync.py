"""Walk backwards by publication day, retaining offset within the boundary day."""
import asyncio
import copy
import json
import time
from datetime import date, timedelta
from backend.models import now
from backend.sources import SourceError, parse_arxiv, parse_openalex


async def page(provider, source, job):
    end=date.fromisoformat(job['boundary']);offset=job['offset']
    if source=='arxiv':
        categories=' OR '.join('cat:'+c for c in ('cs.AI','cs.LG','cs.CL','cs.CV','cs.NE','stat.ML'))
        body=await provider.request(source,'https://export.arxiv.org/api/query',{
            'search_query':f'({categories}) AND submittedDate:[199101010000 TO {end:%Y%m%d}2359]',
            'start':offset,'max_results':100,'sortBy':'submittedDate','sortOrder':'descending'})
        records,total=parse_arxiv(body,now())
    else:
        body=await provider.request(source,'https://api.openalex.org/works',{
            'filter':f'primary_topic.subfield.id:1702,to_publication_date:{end}',
            'sort':'publication_date:desc','per_page':100,'page':offset//100+1})
        records,total=parse_openalex(json.loads(body),now())
        records=records[offset%100:]
    return records,total


async def synchronize(provider, source, end, previous, seconds=120):
    state=copy.deepcopy(previous or {})
    if not state or (state.get('complete') and state.get('end','')<str(end)):
        state={'end':str(end),'boundary':str(end),'offset':0,'scanned':0,'pages':0,'complete':False,'pending':True}
    records=[]
    if state.get('retry_after','')>str(end):return records,state
    state.pop('error',None)
    deadline=time.monotonic()+seconds
    while not state['complete'] and time.monotonic()<deadline:
        try:
            batch,total=await asyncio.wait_for(page(provider,source,state),max(.001,deadline-time.monotonic()))
            if not batch and state['offset']<total:raise SourceError('incomplete_page','历史分页提前为空，保留断点等待重试。')
            dates=[r.filter_date for r in batch]
            if any(not d or d>state['boundary'] for d in dates):raise SourceError('invalid_page','来源日期无法用于继续分页，保留断点。')
            complete=state['offset']+len(batch)>=total
            if batch:
                boundary=min(dates)
                offset=(state['offset'] if boundary==state['boundary'] else 0)+dates.count(boundary)
                state.update(boundary=boundary,offset=offset)
                records.extend(batch)
            state.update(scanned=state['scanned']+len(batch),pages=state['pages']+1,complete=complete,updated_at=now())
        except asyncio.TimeoutError:break
        except Exception as exc:
            state['error']=exc.message if isinstance(exc,SourceError) else '历史分页暂时中断，保留断点等待续采。'
            if isinstance(exc,SourceError) and exc.code in ('access_denied','rate_limited'):
                state['retry_after']=str(end+timedelta(days=1))
            break
    state['pending']=not state['complete']
    if not state.get('error'):state.pop('retry_after',None)
    return records,state
