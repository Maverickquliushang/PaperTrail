"""DBLP official knowledge-graph pagination, with durable per-conference checkpoints."""
import asyncio
import copy
import json
import re
import time
from datetime import date, timedelta
from backend.models import now
from backend.sources import SourceError, doi_id, safe_url
from scripts.public_records import PublicRecord, DBLP_STREAMS

PREFIX = 'PREFIX dblp: <https://dblp.org/rdf/schema#> '
METHOD = 'dblp-sparql-offset-v2'
PAGE_SIZE = 500
TRANSIENT_NOTE = 'DBLP 分页请求未完成，保留断点稍后重试。'


def new_pass(end):
    return {'end':str(end), 'cursor':'', 'scanned':0, 'pages':0, 'total':None, 'complete':False}


def base_pattern(name, year):
    stream = DBLP_STREAMS[name]
    return f'''?paper a dblp:Inproceedings; dblp:publishedInStream <https://dblp.org/streams/conf/{stream}>;
      dblp:yearOfPublication ?year . FILTER(STR(?year) <= "{year}")
      FILTER NOT EXISTS {{ ?paper dblp:publishedIn ?venue .
        FILTER(REGEX(STR(?venue),"workshop|companion|findings|demonstration|tutorial","i")) }}'''


async def fetch_page(provider, name, job):
    pattern = base_pattern(name,date.fromisoformat(job['end']).year)
    total = job['total']
    if total is None:
        result = await provider.dblp_query(PREFIX + 'SELECT (COUNT(DISTINCT ?paper) AS ?count) WHERE {' + pattern + '}')
        total = int(result['results']['bindings'][0]['count']['value'])
    offset = job['scanned']
    query = PREFIX + f'''
SELECT ?paper (SAMPLE(?t) AS ?title) (SAMPLE(?y) AS ?year) (SAMPLE(?v) AS ?venue)
 (SAMPLE(?url) AS ?link) (GROUP_CONCAT(DISTINCT ?name; separator="|") AS ?authors)
WHERE {{ {{ SELECT DISTINCT ?paper WHERE {{ {pattern} }} ORDER BY ?paper LIMIT {PAGE_SIZE} OFFSET {offset} }}
 ?paper dblp:title ?t; dblp:yearOfPublication ?y .
 OPTIONAL {{ ?paper dblp:publishedIn ?v }} OPTIONAL {{ ?paper dblp:primaryDocumentPage ?url }}
 OPTIONAL {{ ?paper dblp:authoredBy ?author . ?author dblp:primaryCreatorName ?name }}
}} GROUP BY ?paper ORDER BY ?paper'''
    payload = await provider.dblp_query(query)
    rows = payload['results']['bindings']
    records, ids = [], []
    for row in rows:
        get = lambda key: row.get(key,{}).get('value','')
        identifier = get('paper')
        if not identifier.startswith('https://dblp.org/rec/'):
            raise SourceError('invalid_page','DBLP 分页没有向前推进，保留断点等待重试。')
        ids.append(identifier)
        records.append(PublicRecord(source='conferences',source_id='dblp:'+identifier.split('/rec/',1)[1],
            title=get('title'),authors=get('authors').split('|') if get('authors') else [],
            url=safe_url(get('link')) or identifier,doi=doi_id(get('link')),conference=name,
            venue=get('venue'),publication_year=int(get('year')),index_provider='DBLP',retrieved_at=now(),rank=10000))
    if len(set(ids)) != len(ids):
        raise SourceError('invalid_page','DBLP 分页出现重复标识，未推进断点。')
    complete = len(ids) < PAGE_SIZE
    # The graph can change during a crawl; an unexpectedly short scan must not be called complete.
    if complete and job['scanned']+len(ids) < total:
        raise SourceError('incomplete_snapshot','DBLP 索引在采集中变化，保留断点稍后核对。')
    return records,len(ids),total,ids[-1] if ids else job['cursor'],complete


async def synchronize(provider, end, previous, seconds=600):
    state = {key:copy.deepcopy(entry) for key,entry in previous.items() if key.startswith('DBLP:') and entry.get('method')==METHOD}
    records,jobs,reports = [],[],{}
    deadline = time.monotonic()+seconds
    blocked = None
    for name in DBLP_STREAMS:
        key='DBLP:'+name
        entry=state.setdefault(key,{'method':METHOD,'history':new_pass(end)})
        reports[key]={'conference':name,'index_provider':'DBLP','label':name+' · DBLP','state':'success','count':0,'note':''}
        if entry.get('error') == TRANSIENT_NOTE:
            entry.pop('retry_after',None)
        if entry.get('retry_after') and entry['retry_after'] > str(end):
            reports[key].update(state='error',note=entry.get('error','等待来源恢复'))
            continue
        entry.pop('error',None)
        history=entry['history']
        if history['complete'] and history['end'] < str(end):
            entry['last_completed']=history['end']
            entry['history']=history=new_pass(end)
        if not history['complete']:jobs.append(name)
    while jobs and time.monotonic()<deadline:
        name=jobs.pop(0);key='DBLP:'+name
        entry,report=state[key],reports[key]
        if blocked:
            entry['error']=blocked;entry['retry_after']=str(end+timedelta(days=1));report.update(state='error',note=blocked);continue
        job=entry['history']
        try:
            batch,count,total,cursor,complete=await asyncio.wait_for(fetch_page(provider,name,job),max(.001,deadline-time.monotonic()))
            records.extend(batch)
            job.update(cursor=cursor,scanned=job['scanned']+count,pages=job['pages']+1,total=total,complete=complete,updated_at=now())
            report['count']+=len(batch)
            if complete:job['completed_at']=now()
            else:jobs.append(name)
        except asyncio.TimeoutError:
            break
        except Exception as exc:
            note=exc.message if isinstance(exc,SourceError) else TRANSIENT_NOTE
            entry['error']=note;report.update(state='partial' if report['count'] else 'error',note=note)
            if isinstance(exc,SourceError) and exc.code in ('access_denied','rate_limited','dblp_unavailable'):
                blocked=note
                entry['retry_after']=str(end+timedelta(days=1))
    for key,entry in state.items():
        entry['pending']=not entry['history']['complete']
        if not entry.get('error'):entry.pop('retry_after',None)
        reports[key]['progress']=entry
        if not entry.get('error'):
            reports[key]['note']='本轮 DBLP 历史索引已遍历。' if not entry['pending'] else 'DBLP 历史分页进行中，保存断点后自动续采；不设收录篇数上限。'
    return records,list(reports.values()),state


def needs_backfill(state,today):
    return not state or any(e.get('pending') and (not e.get('retry_after') or e['retry_after']<=str(today)) for e in state.values())
