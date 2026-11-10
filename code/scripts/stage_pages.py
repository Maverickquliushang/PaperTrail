"""Build a Pages site from public UI files and a commit-pinned catalog (stdlib only)."""
import argparse
import json
from pathlib import Path
import re
import shutil


ASSETS = ('.nojekyll', 'index.html', 'paper.html', 'style.css', 'app.js', 'browse.js',
          'daily.js', 'search.js', 'paper-data.js', 'paper.js', 'data/terms.json')


def stage(web, output, repository, revision):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository, re.ASCII) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('Expected a public GitHub owner/repository and full commit SHA')
    catalog = json.loads((web / 'data/catalog.json').read_bytes())
    if catalog.get('schema') != 2 or not isinstance(catalog.get('paper_shards'), list):
        raise ValueError('Invalid public catalog')
    entries = catalog['paper_shards']
    for entry in entries:
        name = entry['file']
        if not re.fullmatch(r'papers/part-[a-f0-9]+\.json', name) or not (web / 'data' / name).is_file():
            raise ValueError(f'Invalid or missing shard: {name}')
    if sum(s['count'] for s in entries) + len(catalog['papers']) != catalog['paper_count']:
        raise ValueError('Catalog count does not match its shard inventory')
    # Only this staged manifest points to GitHub. Local/offline catalogs are untouched.
    catalog['shard_base'] = f'https://raw.githubusercontent.com/{repository}/{revision}/code/web/data/'
    output.mkdir(parents=True, exist_ok=False)
    (output / 'data').mkdir()
    for name in ASSETS:
        shutil.copyfile(web / name, output / name)
    (output / 'data/catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    size = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    if size > 64 * 1024 * 1024:
        raise ValueError('Pages UI and manifest exceed 64 MiB; review packaging before deploying')
    print(f"Pages: {size:,} bytes. Catalog: {catalog['paper_count']:,} papers, {len(entries):,} external shards at {revision}.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('web', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('repository')
    parser.add_argument('revision')
    args = parser.parse_args()
    stage(args.web, args.output, args.repository, args.revision)
