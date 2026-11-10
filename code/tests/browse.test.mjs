import test from 'node:test';
import assert from 'node:assert/strict';
import {dateChoices,selectShards,createShardLoader} from '../web/browse.js';
import {conferenceYear} from '../web/search.js';

test('the published catalog reads its exact revision; a local catalog stays on its own origin',async()=>{
  const urls=[], fetcher=async url=>{urls.push(url);return {ok:true,json:async()=>[{id:'p'}]};};
  const base='https://raw.githubusercontent.com/example/fork/'+ 'a'.repeat(40) +'/code/web/data/';
  const shard={file:'papers/part-abcdef.json'};
  for(const storage of [undefined, base]){
    const load=createShardLoader(fetcher,storage);
    assert.equal((await load([shard]))[0].id,'p');
    await assert.rejects(load([{file:'../elsewhere.json'}]),/路径/);
  }
  assert.deepEqual(urls,['./data/'+shard.file,base+shard.file]);
  assert.throws(()=>createShardLoader(fetcher,base.replace('a'.repeat(40),'main')),/地址/);
});

test('year filters use matching conference evidence rather than another edition date',()=>{
  const paper={id:'p',year:2025,evidence:[{source:'conferences',conference:'NeurIPS',publication_year:2025},{source:'conferences',conference:'NeurIPS',publication_year:2026}]};
  assert.equal(conferenceYear([paper],'2026','NeurIPS')[0].year,2026);
  assert.equal(conferenceYear([paper],'2026','ICML').length,0);
});

test('zero-record days remain selectable between collected dates and today',()=>{
  assert.deepEqual(dateChoices({'2026-10-15':3},'2026-10-18'),['2026-10-18','2026-10-17','2026-10-16','2026-10-15']);
});
test('date and year routing only loads matching shards and supports old manifests',()=>{
  const catalog={paper_shards:[{file:'old',sources:['arxiv'],conferences:[]},{file:'one',sources:['arxiv'],conferences:[],dates:['2026-10-15'],years:['2026']},{file:'two',sources:['conferences'],conferences:['ICML'],dates:[],years:['2025'],dated_count:0}]};
  assert.deepEqual(selectShards(catalog,{source:'arxiv',date:'2026-10-16'}).map(s=>s.file),['old']);
  assert.equal(selectShards(catalog,{source:'conferences',conference:'ICML',year:'2026'}).length,0);
  assert.equal(selectShards(catalog,{source:'conferences',year:'2025'}).length,1);
});
test('preload shares requests, retries failures, and abandons obsolete queues',async()=>{
  let calls=0,active=true;
  const load=createShardLoader(async()=>{calls++;return {ok:true,json:async()=>[{id:'p'}]};});
  const shard={file:'papers/part-abc.json'};
  await Promise.all([load([shard]),load([shard])]);assert.equal(calls,1);
  await load([shard,{file:'papers/part-def.json'}],{concurrency:1,active:()=>active,progress:()=>{active=false;}});assert.equal(calls,1);
  let failures=0;
  const retry=createShardLoader(async()=>({ok:++failures>1,json:async()=>[]}));
  await assert.rejects(retry([shard]));await retry([shard]);assert.equal(failures,2);
});
