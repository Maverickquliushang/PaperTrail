import asyncio
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from scripts.update_catalog import collect
from scripts.conference_sync import synchronize
from scripts.catalog_storage import merge_records, write_catalog, read_catalog
from backend.models import Record
from backend.sources import SourceError
from backend.search import merge_records as reference_merge


class Pages:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    async def request(self, source, url, params):
        self.calls.append(params.copy())
        if 'from_publication_date' in params['filter']:
            return json.dumps({'meta':{'count':0,'next_cursor':None},'results':[]})
        start = 0 if params['cursor']=='*' else int(params['cursor'])
        if start == self.fail:
            raise SourceError('rate_limited','limited')
        stop = min(235, start+100)
        return json.dumps({'meta':{'count':235,'next_cursor':str(stop) if stop<235 else None},
            'results':[{'id':f'https://openalex.org/W{i}','title':f'Historical {i}',
                        'publication_date':'2015-01-01','primary_location':{'source':{'id':'https://openalex.org/S1'}}} for i in range(start,stop)]})

    async def dblp_body(self, params):
        raise SourceError('dblp_unavailable','challenge')


class PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_more_than_one_page_and_failure_resume(self):
        with patch('scripts.conference_sync.CONFERENCE_SOURCES', {'ICML':['S1']}):
            records,reports,state=await synchronize(Pages(fail=100),date(2026,10,18),{})
            self.assertEqual(len(records),100)
            self.assertEqual(state['OpenAlex:ICML']['history']['cursor'],'100')
            self.assertFalse(state['OpenAlex:ICML']['history']['complete'])
            provider=Pages()
            more,_,done=await synchronize(provider,date(2026,10,19),state)
            self.assertEqual(len(more),135)
            self.assertTrue(done['OpenAlex:ICML']['history']['complete'])
            self.assertEqual(done['OpenAlex:ICML']['history']['scanned'],235)
            self.assertEqual(next(p['cursor'] for p in provider.calls if 'from_publication_date' not in p['filter']),'100')
            self.assertTrue(done['DBLP:ICML']['pending'])

    async def test_budget_does_not_advance_unfinished_page(self):
        class Slow(Pages):
            async def request(self,*args):
                await asyncio.sleep(1)
        with patch('scripts.conference_sync.CONFERENCE_SOURCES', {'ICML':['S1']}):
            _,_,state=await synchronize(Slow(),date(2026,10,18),{},seconds=.01)
            self.assertEqual(state['OpenAlex:ICML']['history']['scanned'],0)
            self.assertTrue(state['OpenAlex:ICML']['pending'])

    def test_linear_merge_preserves_bridge_and_shard_roundtrip(self):
        def rec(i,doi=None,arxiv=None):
            return Record(source='arxiv',source_id=str(i),title=str(i),doi=doi,arxiv_id=arxiv,url='https://example.org',retrieved_at='2026-10-18T09:00:00+08:00')
        records=[rec(1,'10.1000/a'),rec(2,None,'2610.00001'),rec(3,'10.1000/a','2610.00001')]+[rec(i) for i in range(4,1100)]
        fast=merge_records(records,'date')
        self.assertEqual(fast,reference_merge(records,'date'))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'catalog.json'
            write_catalog(path,{'papers':fast})
            manifest=json.loads(path.read_text(encoding='utf-8'))
            self.assertGreater(len(manifest['paper_shards']),1)
            self.assertEqual(read_catalog(path)['papers'],fast)
