"""Linear grouping and bounded JSON files for the growing public corpus."""
import hashlib
import json
import re
from pathlib import Path
from backend.search import identities, merge_records as format_group


def merge_records(records, sort):
    parents = list(range(len(records)))
    owner = {}
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, record in enumerate(records):
        for key in identities(record):
            if key in owner:
                parents[root(i)] = root(owner[key])
            owner[key] = i
    groups = {}
    for i, record in enumerate(records):
        groups.setdefault(root(i), []).append(record)
    papers = [format_group(group, sort)[0] for group in groups.values()]
    if sort == 'date':
        papers.sort(key=lambda p: (p['date'] or (f"{p['year']}-00-00" if p.get('year') else ''), p['score'], p['id']), reverse=True)
    else:
        papers.sort(key=lambda p: (-p['score'], p['id']))
    return papers


def read_catalog(path):
    if not path.exists():
        return {'papers': [], 'history': []}
    value = json.loads(path.read_text(encoding='utf-8'))
    for shard in value.get('paper_shards', []):
        file = (path.parent / shard['file']).resolve()
        if not file.is_relative_to(path.parent.resolve() / 'papers'):
            raise ValueError('Invalid public catalog shard path')
        value['papers'].extend(json.loads(file.read_text(encoding='utf-8')))
    return value


def browse_index(papers):
    index = {}
    for paper in papers:
        scopes = {}
        for e in paper['evidence']:
            source = e['source']
            accepted = source != 'openreview' or e.get('review_status', 'accepted') == 'accepted'
            keys = (['all', source] if accepted else [])
            if source == 'openreview':
                keys += ['openreview/public'] + (['openreview/accepted'] if accepted else [])
            if source == 'conferences' and e.get('conference'):
                keys.append('conferences/' + e['conference'])
            date = e.get('submitted_date') if source == 'arxiv' else e.get('publication_date')
            date = date if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date or '') else None
            year = date[:4] if date else str(e.get('publication_year') or '')
            for key in keys:
                dates, years = scopes.setdefault(key, (set(), set()))
                if date: dates.add(date)
                if re.fullmatch(r'\d{4}', year): years.add(year)
        for key, (dates, years) in scopes.items():
            item = index.setdefault(key, {'total': 0, 'dated_total': 0, 'dates': {}, 'years': {}})
            item['total'] += 1
            item['dated_total'] += bool(dates)
            for date in dates: item['dates'][date] = item['dates'].get(date, 0) + 1
            for year in years: item['years'][year] = item['years'].get(year, 0) + 1
    return index


def write_catalog(path, value):
    directory = path.parent / 'papers'
    directory.mkdir(exist_ok=True)
    shards, expected, groups = [], set(), {}
    papers = value['papers']
    for paper in papers:
        # Group by conference so a single-conference view need not download the full archive.
        names = sorted({e.get('conference') for e in paper['evidence'] if e.get('conference') and e['source'] == 'conferences'})
        period = (paper.get('date') or str(paper.get('year') or 'unknown'))[:7]
        group = (names[0] if names else 'other', period)
        groups.setdefault(group, []).append(paper)
    for group, items in groups.items():
        for offset in range(0, len(items), 500):
            batch = items[offset:offset + 500]
            body = json.dumps(batch, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            name = 'part-' + hashlib.sha256(body).hexdigest()[:20] + '.json'
            file = directory / name
            file.write_bytes(body)
            expected.add(name)
            shards.append({'file': 'papers/' + name, 'count': len(batch),
                           'dates': sorted({d for p in batch for e in p['evidence'] if (d := e.get('submitted_date') if e['source'] == 'arxiv' else e.get('publication_date'))}),
                           'years': sorted({str(e.get('publication_year') or (e.get('publication_date') or e.get('submitted_date') or '')[:4]) for p in batch for e in p['evidence']} - {''}),
                           'sources': sorted({s for p in batch for s in p['sources']}),
                           'dated_count': sum(any(e.get('submitted_date') if e['source'] == 'arxiv' else e.get('publication_date') for e in p['evidence']) for p in batch),
                           'conferences': sorted({e['conference'] for p in batch for e in p['evidence'] if e.get('conference') and e['source'] == 'conferences'})})
    manifest = {**value, 'papers': [], 'paper_count': len(papers), 'paper_shards': shards, 'browse_index': browse_index(papers)}
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)
    # Only remove generated shards in this project's dedicated output directory.
    for file in directory.glob('part-*.json'):
        if file.name not in expected:
            file.unlink()
