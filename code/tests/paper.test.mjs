import test from 'node:test';
import assert from 'node:assert/strict';
import {paperHref,findPaper} from '../web/paper-data.js';

const shards=['abc','def','123'].map(id=>({file:`papers/part-${id}.json`,sources:['arxiv'],dates:['2026-01-01'],years:['2026'],conferences:[]}));
test('paper links encode identifiers and target a standalone local page',()=>{
  const url=new URL(paperHref({id:'doi:10/x?&',sources:['arxiv']},shards[1].file),'https://example.org/PaperTrail/');
  assert.equal(url.pathname,'/PaperTrail/paper.html');
  assert.equal(url.searchParams.get('id'),'doi:10/x?&');
  assert.equal(url.searchParams.get('shard'),shards[1].file);
});
test('detail lookup prioritizes manifest hint, stops early, and ignores injected paths',async()=>{
  const calls=[];
  const load=async([s])=>{calls.push(s.file);return s===shards[1]?[{id:'p'}]:[];};
  const catalog={paper_shards:shards};
  assert.equal((await findPaper(catalog,new URLSearchParams({id:'p',shard:shards[1].file}),load)).id,'p');
  assert.deepEqual(calls,[shards[1].file]);
  calls.length=0;
  await findPaper(catalog,new URLSearchParams({id:'p',shard:'https://evil.example/secrets',date:'2000-01-01'}),load);
  assert.deepEqual(calls,[shards[0].file,shards[1].file]);
});
test('missing paper distinguishes incomplete loading from an absent record',async()=>{
  assert.equal(await findPaper({paper_shards:shards},new URLSearchParams({id:'missing'}),async()=>[]),null);
  await assert.rejects(findPaper({paper_shards:shards},new URLSearchParams({id:'missing'}),async()=>{throw new Error('offline');}),/未能加载/);
  assert.equal((await findPaper({papers:[{id:'p'}]},new URLSearchParams({id:'p'}),()=>{throw Error('should not fetch');})).id,'p');
});
