"""Linear grouping and bounded JSON files for the growing public corpus."""
import hashlib
import json
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


def write_catalog(path, value):
    directory = path.parent / 'papers'
    directory.mkdir(exist_ok=True)
    shards, expected, groups = [], set(), {}
    papers = value['papers']
    for paper in papers:
        # Group by conference so a single-conference view need not download the full archive.
        names = sorted({e.get('conference') for e in paper['evidence'] if e.get('conference') and e['source'] == 'conferences'})
        group = names[0] if names else 'other'
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
                           'sources': sorted({s for p in batch for s in p['sources']}),
                           'dated_count': sum(any(e.get('submitted_date') if e['source'] == 'arxiv' else e.get('publication_date') for e in p['evidence']) for p in batch),
                           'conferences': sorted({e['conference'] for p in batch for e in p['evidence'] if e.get('conference') and e['source'] == 'conferences'})})
    manifest = {**value, 'papers': [], 'paper_count': len(papers), 'paper_shards': shards}
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)
    # Only remove generated shards in this project's dedicated output directory.
    for file in directory.glob('part-*.json'):
        if file.name not in expected:
            file.unlink()
