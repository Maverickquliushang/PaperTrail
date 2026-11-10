import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('stage_pages', ROOT / 'code/scripts/stage_pages.py')
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)


class PagesBundle(unittest.TestCase):
    def test_site_keeps_manifest_but_never_copies_corpus_or_private_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp) / 'web'
            (web / 'data/papers').mkdir(parents=True)
            for name in pages.ASSETS:
                (web / name).write_bytes((ROOT / 'code/web' / name).read_bytes())
            shard = 'papers/part-abc.json'
            catalog = {'schema': 2, 'papers': [], 'paper_count': 2,
                       'paper_shards': [{'file': shard, 'count': 2}], 'history': [{'date':'2026-10-01'}]}
            (web / 'data/catalog.json').write_text(json.dumps(catalog))
            (web / '.env').write_text('not public')
            stage = lambda dest: pages.stage(web, Path(tmp) / dest, 'example/fork', 'a'*40)
            with self.assertRaisesRegex(ValueError, 'missing shard'):
                stage('incomplete')
            (web / 'data' / shard).write_text('[{},{}]')
            stage('site')
            site = Path(tmp) / 'site'
            self.assertEqual({p.relative_to(site).as_posix() for p in site.rglob('*') if p.is_file()},
                             {*pages.ASSETS, 'data/catalog.json'})
            staged = json.loads((site / 'data/catalog.json').read_bytes())
            self.assertEqual(staged.pop('shard_base'), f'https://raw.githubusercontent.com/example/fork/{"a"*40}/code/web/data/')
            self.assertEqual(staged, catalog)
            self.assertEqual(json.loads((web / 'data/catalog.json').read_bytes()), catalog)
