import json
import unittest
from datetime import date
from scripts.update_catalog import collect  # Initializes the isolated backend import path.
from scripts.latest_sources import LatestProviders
from backend.sources import SourceError


class FakeLatest(LatestProviders):
    def __init__(self, fail_one=False):
        super().__init__(None)
        self.calls = []
        self.fail_one = fail_one

    async def request(self, source, url, params):
        self.calls.append((source, url, params))
        if source == 'arxiv':
            return b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/"><o:totalResults>0</o:totalResults></feed>'
        if source in ('openalex', 'conferences'):
            return b'{"results":[],"meta":{"count":0}}'
        if source == 'openreview':
            if self.fail_one and 'ICLR' in params['content.venueid']:
                raise SourceError('network_error', 'unavailable')
            return b'{"notes":[]}'
        return json.dumps([{'paper': {'id':'2610.00001','title':'AI study','publishedAt':'2026-10-01'},
                            'publishedAt':'2026-10-18'},
                           {'paper': {'id':'9912.00001','title':'Future study','publishedAt':'2099-12-31'}}]).encode()


class LatestTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_categories_without_keywords(self):
        provider = FakeLatest()
        for source in ('arxiv','openalex','conferences','huggingface','openreview'):
            await provider.latest(source, date(2026,9,19), date(2026,10,18), 100)
        params = {source: p for source, _, p in provider.calls}
        self.assertIn('cat:cs.AI', params['arxiv']['search_query'])
        self.assertIn('primary_topic.subfield.id:1702', params['openalex']['filter'])
        self.assertIn('primary_location.source.id:', params['conferences']['filter'])
        self.assertNotIn('search', params['openalex'])
        self.assertNotIn('search.title_and_abstract', params['openalex'])
        self.assertEqual({p['month'] for s, _, p in provider.calls if s == 'huggingface'}, {'2026-09','2026-10'})
        self.assertEqual(len([1 for s, _, _ in provider.calls if s == 'openreview']), 6)

    async def test_community_listing_does_not_replace_publication_date(self):
        data = await FakeLatest().latest('huggingface', date(2026,9,19), date(2026,10,18), 100)
        self.assertEqual(len(data.records), 1)
        self.assertEqual(data.records[0].filter_date, '2026-10-01')

    async def test_failed_conference_subset_is_explicit(self):
        data = await FakeLatest(fail_one=True).latest('openreview', date(2026,9,19), date(2026,10,18), 100)
        self.assertTrue(data.partial)
