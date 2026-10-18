"""On-demand title search for the local edition's DBLP conference channel."""
import json
from backend.models import SourceData, now
from backend.sources import effective_end_date, doi_id, safe_url
from scripts.latest_sources import LatestProviders
from scripts.conference_sync import PREFIX, base_pattern
from scripts.public_records import PublicRecord


async def search_conferences(client, request):
    end = effective_end_date(request)
    if request.start_date or request.end_date:
        return SourceData(records=[],retrieved_at=now(),limited=True,
            note='DBLP 仅提供发表年份，无法精确匹配月日。请清空日期或到累计论文库浏览年份。')
    terms = [word.lower() for word in request.query.split() if word]
    filters = ' '.join('FILTER(CONTAINS(LCASE(STR(?title)), '+json.dumps(word)+'))' for word in terms)
    unions = ' UNION '.join('{'+base_pattern(name,end.year)+' BIND('+json.dumps(name)+' AS ?conference) }' for name in request.conferences)
    query = PREFIX + f'''SELECT DISTINCT ?paper ?title ?year ?conference ?link WHERE {{
      {{ {unions} }} ?paper dblp:title ?title . {filters}
      OPTIONAL {{ ?paper dblp:primaryDocumentPage ?link }}
    }} ORDER BY DESC(?year) ?paper LIMIT {request.limit + 1}'''
    payload = await LatestProviders(client).dblp_query(query)
    rows = payload['results']['bindings']
    records=[]
    for row in rows[:request.limit]:
        get=lambda key:row.get(key,{}).get('value','')
        identifier=get('paper')
        records.append(PublicRecord(source='conferences',source_id='dblp:'+identifier.split('/rec/',1)[1],
            title=get('title'),url=safe_url(get('link')) or identifier,doi=doi_id(get('link')),
            conference=get('conference'),publication_year=int(get('year')),index_provider='DBLP',retrieved_at=now()))
    return SourceData(records=records,scanned=len(rows),limited=len(rows)>request.limit,retrieved_at=now(),
        note='DBLP 标题实时匹配；通常没有摘要，仅提供年份。当前返回数由本次检索设置决定；累计论文库没有总量上限。')
