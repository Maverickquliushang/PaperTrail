import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'local'))
import unittest
from scripts.official_conferences import parse_virtual,parse_html,registry,discovered_entries
from scripts.catalog_storage import browse_index
from backend.search import identities

class OfficialTests(unittest.TestCase):
    def test_new_year_does_not_keep_old_location_or_use_wrong_year(self):
        self.assertIn('/2027/papers.html',registry(2027)['NeurIPS'][1])
        body='<a href="/virtual/2027/loc/new-city/papers.html">Papers</a><a href="/virtual/2026/papers.html">Old</a><a href="https://other.example/2027/papers">Other</a>'
        self.assertEqual(discovered_entries(body,'https://neurips.cc/',2027),['https://neurips.cc/virtual/2027/loc/new-city/papers.html'])
    def test_unpublished_official_paper_keeps_year_and_openreview_identity(self):
        row={'name':'Public accepted paper','visible':True,'virtualsite_url':'/virtual/2026/poster/1','authors':[{'fullname':'A B'}],'paper_url':'https://openreview.net/forum?id=abc','starttime':'2026-12-10T00:00:00Z'}
        r=parse_virtual({'results':[row,{**row,'visible':False}]},'NeurIPS',2026,'https://neurips.cc/')[0]
        self.assertIsNone(r.publication_date);self.assertEqual(r.publication_year,2026)
        self.assertIn('openreview:abc',identities(r));self.assertNotIn('openalex:'+r.source_id,identities(r))
        i=browse_index([{'evidence':[r.model_dump()]}])
        self.assertEqual(i['conferences/NeurIPS']['years'],{'2026':1});self.assertEqual(i['conferences']['dates'],{})
    def test_official_html_formats(self):
        cvf='<dt class="ptitle"><a href="/content/CVPR2026/html/X_CVPR_2026_paper.html">Paper</a></dt><dd><input name="query_author" value="A B"><a href="/paper.pdf">pdf</a></dd>'
        r=parse_html(cvf,'CVPR',2026,'https://openaccess.thecvf.com/','cvf')[0]
        self.assertEqual(r.authors,['A B']);self.assertIsNone(r.publication_date)
        kdd='const cycle1Papers = [{"title":"Paper","url":"https://doi.org/10.1/x","authors":"A B (Institute); C D (Lab)"}];'
        self.assertEqual(parse_html(kdd,'KDD',2026,'https://kdd2026.kdd.org/','kdd')[0].authors,['A B','C D'])
        self.assertEqual(len(registry(2026)),11)
    def test_counts_deduplicate_across_days_and_sources(self):
        e={'source':'arxiv','submitted_date':'2026-10-15'}
        index=browse_index([{'evidence':[e,e,{'source':'huggingface','publication_date':'2026-10-16'}]}])
        self.assertEqual(index['all']['dated_total'],1)
        self.assertEqual(index['all']['dates'],{'2026-10-15':1,'2026-10-16':1})
