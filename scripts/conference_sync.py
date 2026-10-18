"""Resumable, fair pagination. Page size is a transport setting, never a corpus cap."""
import asyncio
import copy
import json
import time
from datetime import date, timedelta

from backend.conferences import CONFERENCE_SOURCES
from backend.models import now
from backend.sources import SourceError, parse_openalex
from scripts.public_records import PublicRecord, DBLP_STREAMS, parse_dblp


def new_pass(end, start=None):
    return {'end': str(end), 'start': start, 'cursor': '*', 'offset': 0,
            'scanned': 0, 'pages': 0, 'total': None, 'complete': False}


async def fetch_page(provider, index, name, job):
    if index == 'OpenAlex':
        identifiers = CONFERENCE_SOURCES[name]
        filters = f'primary_location.source.id:{"|".join(identifiers)},to_publication_date:{job["end"]}'
        if job.get('start'):
            filters += ',from_publication_date:' + job['start']
        payload = json.loads(await provider.request('conferences', 'https://api.openalex.org/works', {
            'filter': filters, 'sort': 'publication_date:asc', 'per_page': 100, 'cursor': job['cursor']}))
        parsed, total = parse_openalex(payload, now())
        records = []
        for r, item in zip(parsed, payload['results']):
            source_id = ((item.get('primary_location') or {}).get('source') or {}).get('id', '').rsplit('/', 1)[-1]
            if source_id in identifiers and (not r.filter_date or r.filter_date <= job['end']):
                r.source, r.conference = 'conferences', name
                records.append(PublicRecord(**r.model_dump(), index_provider='OpenAlex'))
        cursor = payload.get('meta', {}).get('next_cursor')
        count = len(payload['results'])
        # A malformed page must not silently terminate a nonempty crawl.
        if count and (cursor == job['cursor'] or ('next_cursor' not in payload.get('meta', {}))):
            raise SourceError('invalid_cursor', '分页游标缺失或重复，保留断点等待重试。')
        if not count and job['scanned'] < total:
            raise SourceError('invalid_page', '来源提前返回空页，保留断点，不标记补采完成。')
        return records, count, total, cursor, not cursor
    payload = await provider.dblp_body({'q': f'stream:conf/{DBLP_STREAMS[name]}:',
                                      'format': 'json', 'h': 1000, 'f': job['offset']})
    records, total = parse_dblp(payload, name, now(), date.fromisoformat(job['end']).year)
    hits = payload['result']['hits'].get('hit', [])
    count = len(hits) if isinstance(hits, list) else 1
    if not count and job['offset'] < total:
        raise SourceError('invalid_page', 'DBLP 提前返回空页，保留断点等待重试。')
    return records, count, total, None, job['offset'] + count >= total


async def synchronize(provider, end, previous, seconds=600):
    state = copy.deepcopy(previous)
    records, jobs, reports, blocked = [], [], {}, {}
    deadline = time.monotonic() + seconds
    for index in ('OpenAlex', 'DBLP'):
        for name in CONFERENCE_SOURCES:
            key = index + ':' + name
            entry = state.setdefault(key, {})
            history = entry.setdefault('history', new_pass(end))
            # Reconcile late-indexed historical works periodically; DBLP has no change-feed here.
            cadence = 30 if index == 'OpenAlex' else 1
            if history['complete'] and (end - date.fromisoformat(history['end'])).days >= cadence:
                entry['last_completed'] = history['end']
                entry['history'] = history = new_pass(end)
            if not history['complete']:
                jobs.append((index, name, 'history'))
            if index == 'OpenAlex':
                recent = entry.get('recent')
                if not recent or (recent['complete'] and recent['end'] < str(end)):
                    start = date.fromisoformat(recent['end']) - timedelta(days=7) if recent else end - timedelta(days=30)
                    entry['recent'] = recent = new_pass(end, str(start))
                if not recent['complete']:
                    jobs.insert(0, (index, name, 'recent'))
            entry.pop('error', None)
            reports[key] = {'conference': name, 'index_provider': index, 'label': name + ' · ' + index,
                            'state': 'success', 'count': 0, 'note': '逐页采集，无收录总量上限。'}
    # One page per queue turn prevents one large conference starving the others.
    while jobs and time.monotonic() < deadline:
        index, name, kind = jobs.pop(0)
        key = index + ':' + name
        entry, report = state[key], reports[key]
        if index in blocked:
            entry['error'] = blocked[index]
            report.update(state='error', note=blocked[index])
            continue
        job = entry[kind]
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            batch, count, total, cursor, complete = await asyncio.wait_for(fetch_page(provider, index, name, job), remaining)
            # Advance only after validation succeeds. All page records and its checkpoint commit together.
            records.extend(batch)
            job.update(cursor=cursor, offset=job['offset'] + count, scanned=job['scanned'] + count,
                       pages=job['pages'] + 1, total=total, complete=complete, updated_at=now())
            report['count'] += len(batch)
            if complete:
                job['completed_at'] = now()
            else:
                jobs.append((index, name, kind))
        except asyncio.TimeoutError:
            break  # Save completed pages; this page is retried next run.
        except Exception as exc:
            note = exc.message if isinstance(exc, SourceError) else '索引分页请求未完成；已保存成功页面，稍后从断点重试。'
            entry['error'] = note
            report.update(state='partial' if report['count'] else 'error', note=note)
            # Reject/limit stops this host, not the other index. No access-challenge bypass.
            if isinstance(exc, SourceError) and exc.code in ('access_denied', 'rate_limited', 'dblp_unavailable'):
                blocked[index] = note
    for key, entry in state.items():
        if key not in reports:
            continue
        entry['pending'] = not entry['history']['complete'] or not entry.get('recent', {'complete': True})['complete']
        if entry.get('error'):
            entry['retry_after'] = str(end + timedelta(days=1))
        else:
            entry.pop('retry_after', None)
        reports[key]['progress'] = entry
        if not entry.get('error'):
            reports[key]['note'] = '分页检查完成（仅当前索引覆盖）。' if not entry['pending'] else '补采进行中，下一轮从已保存断点继续；无篇数上限。'
    return records, list(reports.values()), state


def needs_backfill(state, today):
    return not state or any(e.get('pending') and (not e.get('retry_after') or e['retry_after'] <= str(today)) for e in state.values())
