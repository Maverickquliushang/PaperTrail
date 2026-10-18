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
        self.calls,self.fail=[],fail
    async def dblp_query(self, query):
        self.calls.append(query)
        if 'COUNT(' in query:return {'results':{'bindings':[{'count':{'value':'1235'}}]}}
        import re
        match=re.search(r'OFFSET (\d+)',query)
        start=int(match[1]) if match else 0
        if start==self.fail:raise SourceError('rate_limited','limited')
        rows=[{'paper':{'value':f'https://dblp.org/rec/conf/icml/p{i:05}'},'title':{'value':f'Paper {i}'},'year':{'value':'2010'}} for i in range(start,min(start+500,1235))]
        return {'results':{'bindings':rows}}

class PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_more_than_one_page_and_failure_resume(self):
        with patch('scripts.conference_sync.DBLP_STREAMS', {'ICML':'icml'}):
            records,reports,state=await synchronize(Pages(fail=500),date(2026,10,18),{})
            self.assertEqual(len(records),500)
            self.assertTrue(state['DBLP:ICML']['history']['cursor'].endswith('00499'))
            self.assertFalse(state['DBLP:ICML']['history']['complete'])
            provider=Pages()
            more,_,done=await synchronize(provider,date(2026,10,19),state)
            self.assertEqual(len(more),735)
            self.assertTrue(done['DBLP:ICML']['history']['complete'])
            self.assertEqual(done['DBLP:ICML']['history']['scanned'],1235)
            self.assertIn('OFFSET 500',provider.calls[0])

    async def test_transient_failure_can_resume_same_day(self):
        class Transient(Pages):
            async def dblp_query(self, query):
                if 'OFFSET 500' in query: raise ConnectionError('temporary')
                return await super().dblp_query(query)
        with patch('scripts.conference_sync.DBLP_STREAMS', {'ICML':'icml'}):
            records,_,state=await synchronize(Transient(),date(2026,10,18),{})
            self.assertEqual(len(records),500)
            more,_,done=await synchronize(Pages(),date(2026,10,18),state)
            self.assertEqual(len(more),735)
            self.assertTrue(done['DBLP:ICML']['history']['complete'])

    async def test_budget_does_not_advance_unfinished_page(self):
        class Slow(Pages):
            async def dblp_query(self,query):
                await asyncio.sleep(1)
        with patch('scripts.conference_sync.DBLP_STREAMS', {'ICML':'icml'}):
            _,_,state=await synchronize(Slow(),date(2026,10,18),{},seconds=.01)
            self.assertEqual(state['DBLP:ICML']['history']['scanned'],0)
            self.assertTrue(state['DBLP:ICML']['pending'])

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
