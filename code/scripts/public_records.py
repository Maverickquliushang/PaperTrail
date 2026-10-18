"""Additional public-index metadata without changing the local application."""
import re
from datetime import datetime, timezone
from backend.models import Record
from backend.sources import clean, safe_url, doi_id, arxiv_id

DBLP_STREAMS = {name: ('nips' if name == 'NeurIPS' else name.lower())
                for name in ('NeurIPS','ICML','ICLR','CVPR','ICCV','ECCV','ACL','EMNLP','AAAI','IJCAI','KDD')}


class PublicRecord(Record):
    index_provider: str | None = None
    publication_year: int | None = None
    review_status: str | None = None


def parse_dblp(payload, conference, stamp, year):
    hits = payload['result']['hits']
    total = int(hits['@total'])
    items = hits.get('hit', [])
    if isinstance(items, dict):
        items = [items]
    records = []
    for item in items:
        info = item.get('info', {})
        key = info.get('key', '')
        # A stream can include workshops and proceedings metadata. Do not label them main-track papers.
        if not key.startswith('conf/' + DBLP_STREAMS[conference] + '/') or info.get('type') != 'Conference and Workshop Papers':
            continue
        venue = info.get('venue', '')
        if isinstance(venue, list):
            venue = ' / '.join(venue)
        if re.search(r'workshop|companion|findings|demonstration|tutorial', venue, re.I):
            continue
        pubyear = int(info['year']) if str(info.get('year', '')).isdigit() else None
        if pubyear and pubyear > year:
            continue
        authors = (info.get('authors') or {}).get('author', [])
        if not isinstance(authors, list):
            authors = [authors]
        external = info.get('ee', [])
        if not isinstance(external, list):
            external = [external]
        doi = doi_id(info.get('doi')) or next((d for x in external if (d := doi_id(x))), None)
        records.append(PublicRecord(source='conferences', source_id='dblp:' + key,
            title=clean(info.get('title')), authors=[clean(a.get('text') if isinstance(a, dict) else a) for a in authors],
            url=safe_url(info.get('url')) or f'https://dblp.org/rec/{key}', doi=doi,
            conference=conference, venue=clean(venue), publication_year=pubyear,
            index_provider='DBLP', retrieved_at=stamp, rank=10000 + len(records)))
    return records, total


def value(content, key):
    raw = content.get(key)
    return raw.get('value') if isinstance(raw, dict) else raw


def parse_public_submissions(payload, conference, venue_id, invitation, status_ids, stamp):
    if not isinstance(payload.get('notes'), list):
        raise ValueError('Missing notes')
    records = []
    for note in payload['notes']:
        if note.get('replyto') or ('readers' in note and 'everyone' not in note['readers']):
            continue
        if invitation not in note.get('invitations', []):
            continue
        content = note.get('content') or {}
        title, identifier = clean(value(content, 'title')), note.get('id', '')
        if not title or not re.fullmatch(r'[\w-]+', identifier):
            continue
        venue = value(content, 'venueid')
        status = 'accepted' if venue == venue_id else status_ids.get(venue, 'unknown')
        raw_date = note.get('pdate') if status == 'accepted' else note.get('cdate')
        try:
            day = datetime.fromtimestamp(float(raw_date) / 1000, timezone.utc).date().isoformat() if raw_date else None
        except (ValueError, TypeError, OverflowError, OSError):
            day = None
        pdf = value(content, 'pdf')
        if isinstance(pdf, str) and pdf.startswith('/pdf?'):
            pdf = 'https://openreview.net' + pdf
        records.append(PublicRecord(source='openreview', source_id=identifier,
            title=title, authors=[clean(a) for a in (value(content, 'authors') or [])],
            abstract=clean(value(content, 'abstract')) or None, url=f'https://openreview.net/forum?id={identifier}',
            pdf_url=safe_url(pdf), doi=doi_id(value(content, 'doi')),
            arxiv_id=arxiv_id(value(content, 'arxiv_id')) or arxiv_id(value(content, 'html')),
            venue=clean(value(content, 'venue')) or venue_id, conference=conference,
            publication_date=day, review_status=status, index_provider='OpenReview', retrieved_at=stamp))
    return records
