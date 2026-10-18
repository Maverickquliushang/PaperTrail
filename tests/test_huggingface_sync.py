import unittest
from datetime import date
from scripts.update_catalog import collect
from scripts.huggingface_sync import synchronize


class Pages:
    def __init__(self, fail=None): self.fail=fail
    async def huggingface_page(self, cursor):
        offset=int(cursor or 0)
        if offset==self.fail:raise ConnectionError('temporary')
        rows=[{'id':f'2601.{i:05d}','title':str(i),'publishedAt':'2026-01-01'} for i in range(offset,min(offset+100,250))]
        return rows,str(offset+100) if offset+100<250 else None


class HuggingFacePagesTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_beyond_200_and_reaches_end(self):
        records,state=await synchronize(Pages(),date(2026,10,18),{})
        self.assertEqual(len(records),250)
        self.assertEqual(state['pages'],3)
        self.assertFalse(state['pending'])

    async def test_resume_preserves_finished_pages_without_restarting(self):
        records,state=await synchronize(Pages(fail=100),date(2026,10,18),{})
        self.assertEqual(len(records),100)
        self.assertEqual(state['cursor'],'100')
        self.assertTrue(state['pending'])
        more,done=await synchronize(Pages(),date(2026,10,18),state)
        self.assertEqual(len(more),150)
        self.assertEqual(done['scanned'],250)
        self.assertTrue(done['complete'])
