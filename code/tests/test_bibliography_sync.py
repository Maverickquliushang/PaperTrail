import unittest
from datetime import date
from unittest.mock import patch
from scripts.update_catalog import collect
from scripts.bibliography_sync import synchronize
from backend.models import Record, now


class BibliographyTests(unittest.IsolatedAsyncioTestCase):
    async def test_boundary_day_resume_does_not_skip_or_repeat_records(self):
        rows=[Record(source='arxiv',source_id=str(i),title=str(i),url='https://example.org',retrieved_at=now(),submitted_date='2026-10-18' if i<75 else '2026-10-17') for i in range(350)]
        calls=[]
        async def fake_page(provider,source,job):
            eligible=[r for r in rows if r.filter_date<=job['boundary']]
            calls.append((job['boundary'],job['offset']))
            if len(calls)==3:raise ConnectionError('temporary')
            return eligible[job['offset']:job['offset']+100],len(eligible)
        with patch('scripts.bibliography_sync.page',fake_page):
            first,state=await synchronize(None,'arxiv',date(2026,10,18),{})
            self.assertEqual(len(first),200)
            self.assertEqual(state['boundary'],'2026-10-17')
            self.assertEqual(state['offset'],125)
            rest,done=await synchronize(None,'arxiv',date(2026,10,18),state)
        self.assertEqual(len({r.source_id for r in first+rest}),350)
        self.assertEqual(len(first+rest),350)
        self.assertTrue(done['complete'])
