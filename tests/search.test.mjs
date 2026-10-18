import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {search, translateQuery, safeLink, sortPapers} from '../web/search.js';
const terms = JSON.parse(readFileSync(new URL('../web/data/terms.json', import.meta.url)));
const paper = (id, title, date, sources=['arxiv']) => ({id,title,date,sources,abstract:''});
test('Chinese phrasing, no-space command and aliases search the same corpus', () => {
  for (const q of ['检索图神经网络','检索 图神经网络','帮我找图神经网络的论文']) assert.equal(translateQuery(q,terms),'graph neural network');
  const data = [paper('a','Graph neural networks','2026-10-01'),paper('b','Convolutional networks','2026-10-02')];
  assert.deepEqual(search(data,translateQuery('图神经网络',terms)).map(p=>p.id),['a']);
});
test('Do not silently discard unsupported Chinese constraints', () => {
  assert.throws(()=>translateQuery('图神经网络但不要推荐系统',terms));
  assert.equal(translateQuery('检索增强生成',terms),'retrieval augmented generation');
});
test('Global date ordering, missing dates last, filters and immutability', () => {
  const data = [paper('a','model',null),paper('b','model','2026-10-01'),paper('c','model','2026-10-03',['openalex'])];
  assert.deepEqual(search(data,'model').map(p=>p.id),['c','b','a']);
  assert.deepEqual(search(data,'model',{sort:'date_asc'}).map(p=>p.id),['b','c','a']);
  assert.deepEqual(search(data,'model',{source:'arxiv',start:'2026-09-01'}).map(p=>p.id),['b']);
  assert.equal(data[0].id,'a');
});
test('BM25 ranks denser relevant text above incidental mentions', () => {
  const data = [paper('a','vision '+'irrelevant '.repeat(100),'2026-10-01'),paper('b','vision vision','2026-09-01')];
  assert.equal(search(data,'vision',{sort:'relevance'})[0].id,'b');
  assert.equal(sortPapers(data,'date_desc')[0].id,'a');
});
test('External links reject executable schemes', () => {
  assert.equal(safeLink('javascript:alert(1)'),null);
  assert.equal(safeLink('https://user@example.com'),null);
  assert.equal(safeLink('https://arxiv.org/abs/1234.56789'),'https://arxiv.org/abs/1234.56789');
});
