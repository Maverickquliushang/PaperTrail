import unittest
from datetime import datetime
from scripts.update_catalog import collect, validate_config, BEIJING
from backend.models import Record, SourceData
from backend.sources import SourceError

CONFIG = {'mode':'ai_latest', 'sources':['arxiv','openalex'],
          'community_feed_days':30,'candidate_limit':100,'recommendation_limit':10,'history_days':30}
NOW = datetime(2026,10,18,9,tzinfo=BEIJING)
def record(i=1, source='arxiv', day='2026-10-18'):
    return Record(source=source,source_id=str(i),title='Graph neural networks',
                  arxiv_id=f'2610.{i:05}',submitted_date=day,publication_date=day,
                  url='https://arxiv.org/abs/2610.00001',retrieved_at=NOW.isoformat())
class Provider:
    def __init__(self, failed=()): self.failed=failed
    async def latest(self, source, start, end, limit):
        if source in self.failed: raise SourceError('rate_limited','来源限流')
        return SourceData(records=[record(i,source) for i in range(1,16)]+[record(99,source,'2099-12-31')], retrieved_at=NOW.isoformat())
class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_merge_future_and_per_source_cap(self):
        data=await collect(CONFIG,{},Provider(),NOW)
        self.assertEqual(len(data['papers']),15)
        self.assertEqual(data['papers'][0]['sources'],['arxiv','openalex'])
        self.assertTrue(all(len(r['papers'])==10 for r in data['recommendations'].values()))
    async def test_failure_retains_catalog_without_fake_fresh_recommendation(self):
        old=await collect(CONFIG,{},Provider(),NOW)
        next_day=NOW.replace(day=19)
        data=await collect(CONFIG,old,Provider(('arxiv','openalex')),next_day)
        self.assertEqual(data['updated_at'],old['updated_at'])
        self.assertEqual(len(data['papers']),15)
        self.assertEqual(data['recommendations']['arxiv']['papers'],[])
        self.assertEqual(data['source_status']['arxiv']['state'],'error')
    async def test_history_dedup_and_same_day_retry(self):
        first=await collect(CONFIG,{},Provider(),NOW)
        retry=await collect(CONFIG,first,Provider(),NOW)
        self.assertEqual(len(retry['history']),1)
        self.assertEqual(len(retry['recommendations']['arxiv']['papers']),10)
        later=await collect(CONFIG,retry,Provider(),NOW.replace(day=19))
        self.assertEqual(len(later['recommendations']['arxiv']['papers']),0)
    async def test_partial_sources_explicit(self):
        data=await collect(CONFIG,{},Provider(('openalex',)),NOW)
        self.assertEqual(data['source_status']['openalex']['state'],'error')
        self.assertEqual(data['source_status']['arxiv']['state'],'success')
        self.assertEqual(data['recommendations']['openalex']['papers'],[])
    def test_invalid_config(self):
        with self.assertRaises(ValueError): validate_config({**CONFIG,'recommendation_limit':11})
        with self.assertRaises(ValueError): validate_config({**CONFIG,'sources':['typo']})

    async def test_legacy_personal_catalog_is_not_retained(self):
        legacy = await collect(CONFIG, {}, Provider(), NOW)
        legacy['schema'] = 1
        legacy['topics'] = ['private research interest']
        data = await collect(CONFIG, legacy, Provider(('arxiv','openalex')), NOW)
        self.assertEqual(data['papers'], [])
        self.assertEqual(data['history'][0]['recommendations']['arxiv']['papers'], [])
        self.assertNotIn('topics', data)

    async def test_older_papers_are_searchable_but_not_today_recommendations(self):
        data = await collect(CONFIG, {}, Provider(), NOW.replace(day=19))
        self.assertEqual(len(data['papers']), 15)
        self.assertEqual(data['recommendations']['arxiv']['papers'], [])

    def test_config_accepts_public_feed_window(self):
        self.assertEqual(validate_config(CONFIG), CONFIG)

    async def test_historical_records_survive_refresh_failure(self):
        class HistoricalProvider:
            async def latest(self, source, start, end, limit):
                return SourceData(records=[record(1, source, '2019-01-05')], retrieved_at=NOW.isoformat())
        data = await collect(CONFIG, {}, HistoricalProvider(), NOW)
        self.assertEqual(len(data['papers']), 1)
        later = await collect(CONFIG, data, Provider(('arxiv','openalex')), NOW.replace(year=2027))
        self.assertEqual(later['papers'][0]['date'], '2019-01-05')
        self.assertEqual(later['recommendations']['arxiv']['papers'], [])

    async def test_dblp_year_and_review_status_survive_persistence(self):
        from scripts.public_records import PublicRecord
        class RichProvider:
            async def latest(self, source, start, end, limit):
                if source == 'conferences':
                    r = PublicRecord(source=source,source_id='dblp:conf/icml/test',title='Study',conference='ICML',index_provider='DBLP',publication_year=2018,url='https://dblp.org/rec/conf/icml/test',retrieved_at=NOW.isoformat())
                else:
                    r = PublicRecord(source=source,source_id='public-note',title='Study',conference='ICLR',review_status='under_review',publication_date='2026-10-18',url='https://openreview.net/forum?id=public-note',retrieved_at=NOW.isoformat())
                return SourceData(records=[r],retrieved_at=NOW.isoformat())
        config={**CONFIG,'sources':['conferences','openreview']}
        first=await collect(config,{},RichProvider(),NOW)
        self.assertEqual(first['recommendations']['openreview']['papers'], [])
        self.assertEqual(first['recommendations']['conferences']['papers'], [])
        self.assertEqual(len(first['history'][0]['openreview_public']['papers']), 1)
        retry=await collect(config,first,Provider(('conferences','openreview')),NOW)
        yearpaper=next(p for p in retry['papers'] if 'conferences' in p['sources'])
        self.assertEqual(yearpaper['year'],2018)
        self.assertIsNone(yearpaper['date'])
        self.assertEqual(yearpaper['evidence'][0]['index_provider'],'DBLP')
        self.assertEqual(next(p for p in retry['papers'] if 'openreview' in p['sources'])['evidence'][0]['review_status'],'under_review')
