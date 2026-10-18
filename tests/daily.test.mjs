import test from 'node:test';
import assert from 'node:assert/strict';
import {dailyArchive} from '../web/daily.js';
const item = (id, evidence) => ({id, title:id, sources:[...new Set(evidence.map(e=>e.source))], evidence});
const data = [
  item('shared', [{source:'arxiv',submitted_date:'2020-01-01'}, {source:'huggingface',publication_date:'2020-01-02'}]),
  item('hf', [{source:'huggingface',publication_date:'2025-08-03'}]),
  item('year', [{source:'conferences',conference:'ICML',publication_year:2024}]),
  item('future', [{source:'huggingface',publication_date:'2099-01-01'}]),
  item('review', [{source:'openreview',publication_date:'2023-02-03',review_status:'rejected'}]),
];
test('Daily dates include old corpus dates without requiring recommendation runs',()=>{
  const result=dailyArchive(data, [], 'huggingface', 'all', 'accepted', '2026-10-18');
  assert.deepEqual([...result.days.keys()],['2025-08-03','2020-01-02']);
  assert.equal(result.all.length,2);
  assert.equal(result.days.get('2020-01-02')[0].date,'2020-01-02');
});
test('All dates deduplicate papers while individual dates honor source evidence',()=>{
  const result=dailyArchive(data, [], 'all', 'all', 'accepted', '2026-10-18');
  assert.equal(result.all.length,2);
  assert.equal(result.days.get('2020-01-01')[0].id,'shared');
  assert.equal(result.days.get('2020-01-02')[0].id,'shared');
  assert.ok(!result.days.has('2023-02-03'));
  assert.equal(dailyArchive(data, [], 'openreview','all','public').all.length,1);
  assert.equal(dailyArchive(data, [], 'conferences','ICML').all.length,0);
});
test('Archived runs remain browsable, and current metadata replaces stale evidence',()=>{
  const old=item('shared',[{source:'huggingface',publication_date:'2010-01-01'}]);
  const history=[{date:'2026-10-18',recommendations:{huggingface:{papers:[old,data[1]]}}}];
  const result=dailyArchive([data[0]],history,'huggingface');
  assert.equal(result.all.length,2);
  assert.ok(!result.days.has('2010-01-01'));
});
