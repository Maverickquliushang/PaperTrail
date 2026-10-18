"""Resume the official full paper listing; page size is not a corpus cap."""
import asyncio
import copy
import time
from datetime import timedelta
from backend.sources import SourceError, parse_huggingface
from backend.models import now


async def synchronize(provider, end, previous, seconds=180):
    state = copy.deepcopy(previous or {})
    if not state or (state.get('complete') and state.get('end', '') < str(end)):
        state = {'end':str(end),'cursor':None,'pages':0,'scanned':0,'complete':False,'pending':True}
    records = []
    if state.get('retry_after', '') > str(end):
        return records, state
    state.pop('error', None)
    deadline = time.monotonic() + seconds
    while not state['complete'] and time.monotonic() < deadline:
        try:
            rows, cursor = await asyncio.wait_for(provider.huggingface_page(state['cursor']), max(.001, deadline-time.monotonic()))
            if cursor and (cursor == state['cursor'] or not rows):
                raise SourceError('invalid_cursor','Hugging Face 分页未推进，保留断点。')
            parsed = parse_huggingface(rows, now())
            records.extend(r for r in parsed if r.filter_date and r.filter_date <= str(end))
            state.update(cursor=cursor,pages=state['pages']+1,scanned=state['scanned']+len(rows),complete=not cursor,updated_at=now())
        except asyncio.TimeoutError:
            break
        except Exception as exc:
            state['error'] = exc.message if isinstance(exc,SourceError) else 'Hugging Face 请求中断，已保存页面将在后续任务续接。'
            if isinstance(exc,SourceError) and exc.code in ('rate_limited','access_denied'):
                state['retry_after'] = str(end+timedelta(days=1))
            break
    state['pending'] = not state['complete']
    if not state.get('error'):state.pop('retry_after',None)
    return records,state
