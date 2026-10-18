import {expect,test,type Page} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';

const paper={id:'arxiv:2601.00001',title:'A paper with persistent reading state',authors:['First Author','Second Author'],abstract:'Full abstract remains readable while other records arrive.',date:'2026-01-01',date_kind:'首次提交',year:2026,sources:['arxiv'],arxiv_id:'2601.00001',evidence:[{source:'arxiv',url:'https://arxiv.org/abs/2601.00001',pdf_url:'https://arxiv.org/pdf/2601.00001',submitted_date:'2026-01-01',title:'A paper with persistent reading state'}]};
const newer={...paper,id:'newer',title:'A newer paper',date:'2026-01-02'};
const shards=['abc','def'].map(id=>({file:`papers/part-${id}.json`,sources:['arxiv'],dates:['2026-01-01','2026-01-02'],years:['2026'],conferences:[]}));
const catalog={schema:2,mode:'ai_latest',papers:[],paper_count:2,paper_shards:shards,history:[],source_status:{},updated_at:'2026-01-02T00:00:00Z'};

async function mockShared(page:Page,prefix:string,wait?:Promise<void>) {
  await page.route(`**/${prefix}/**`,async route=>{
    const name=new URL(route.request().url()).pathname.split(`/${prefix}/`)[1] || 'index.html';
    if(name==='data/catalog.json')return route.fulfill({json:catalog});
    if(name==='data/terms.json')return route.fulfill({json:{}});
    if(name==='data/papers/part-abc.json')return route.fulfill({json:[paper]});
    if(name==='data/papers/part-def.json'){if(wait)await wait;return route.fulfill({json:[newer]});}
    if(!/^[a-z-]+\.(js|css|html)$/.test(name))return route.fulfill({status:404});
    const body=await readFile(resolve('../../web',name));
    return route.fulfill({body,contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'});
  });
}

test('background shards preserve expanded reading; title opens a reloadable page and back restores filters',async({page})=>{
  let release!:()=>void;
  const wait=new Promise<void>(r=>{release=r;});
  await mockShared(page,'catalog',wait);
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/catalog/#/arxiv/search');
  const card=page.locator('article.paper').filter({hasText:paper.title});
  await expect(card).toBeVisible();
  await card.locator('summary').click();
  await expect(card.locator('details')).toHaveAttribute('open','');
  release();
  await expect(page.locator('#load-status')).toContainText('加载完成');
  await expect(card.locator('details')).toHaveAttribute('open','');
  await expect(page.getByRole('link',{name:newer.title,exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'新结果已就绪 · 更新列表'}).click();
  await expect(card.locator('details')).toHaveAttribute('open','');
  await expect(page.getByRole('link',{name:newer.title,exact:true})).toBeVisible();
  await page.locator('#query').fill('persistent');
  await page.getByRole('button',{name:'检索论文 →',exact:true}).click();
  await card.getByRole('link',{name:paper.title,exact:true}).click();
  await expect(page).toHaveURL(/paper\.html\?id=/);
  await expect(page.getByRole('heading',{name:paper.title,exact:true})).toBeVisible();
  await expect(page.locator('.abstract')).toHaveText(paper.abstract);
  await expect(page.getByRole('link',{name:'查看原文 ↗'}).first()).toHaveAttribute('href',paper.evidence[0].url);
  await page.reload();
  await expect(page.locator('.abstract')).toHaveText(paper.abstract);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.goBack();
  await expect(page.locator('#query')).toHaveValue('persistent');
  await expect(card.locator('details')).toHaveAttribute('open','');
  expect(errors).toEqual([]);
});

test('direct paper link resolves current data; failed and missing records are explicit',async({page})=>{
  await mockShared(page,'catalog');
  await page.goto('/catalog/paper.html?id=arxiv%3A2601.00001&shard=papers%2Fpart-old.json');
  await expect(page.getByRole('heading',{name:paper.title,exact:true})).toBeVisible();
  await page.goto('/catalog/paper.html?id=missing');
  await expect(page.locator('#paper-status')).toContainText('未找到');
  await page.route('**/data/papers/*.json',route=>route.fulfill({status:503}));
  await page.reload();
  await expect(page.locator('#paper-status')).toContainText('未能加载');
  await expect(page.getByRole('button',{name:'重新加载'})).toBeVisible();
});

test('local search title uses shared page and keeps the external original link separate',async({page})=>{
  await mockShared(page,'library');
  await page.route('**/api/searches',route=>route.fulfill({status:202,json:{id:'task',request:{query:'test',sources:['arxiv'],limit:10,sort:'date'},papers:[paper],sources:[{source:'arxiv',state:'success',count:1,total:1}],done:true,merged_count:1,raw_count:1}}));
  await page.goto('/');
  await page.getByLabel('你想探索什么研究主题？').fill('test');
  await page.getByRole('button',{name:'检索论文',exact:true}).click();
  await expect(page.getByRole('link',{name:'查看原文',exact:true})).toHaveAttribute('href',paper.evidence[0].url);
  await page.getByRole('link',{name:paper.title,exact:true}).click();
  await expect(page).toHaveURL(/\/library\/paper.html\?local=/);
  await expect(page.locator('.abstract')).toHaveText(paper.abstract);
  await page.reload();
  await expect(page.getByRole('heading',{name:paper.title,exact:true})).toBeVisible();
  await page.evaluate(()=>sessionStorage.clear());
  await page.reload();
  await expect(page.locator('#paper-status')).toContainText('记录已失效');
});

test('local recommendation titles use the same detail page with desktop and mobile layouts',async({page},testInfo)=>{
  await mockShared(page,'library');
  const settings={topics:['test'],sources:['arxiv'],conferences:['ICLR'],enabled:false,time:'09:00',timezone:'Asia/Shanghai',count:0,lookback_days:30,dedup_days:30};
  const run={id:'daily',date:'2026-01-01',started_at:'2026-01-01T00:00:00Z',status:'success',trigger:'manual',settings,paper_count:1,papers:[{...paper,reasons:['Matches topic'],recommendation_score:1}],excluded_count:0,source_results:[]};
  await page.route('**/api/recommendations',route=>route.fulfill({json:{settings,runs:[run],running:false,next_run:null}}));
  await page.route('**/api/recommendations/runs/daily',route=>route.fulfill({json:run}));
  await page.goto('/#/daily');
  await expect(page.getByRole('link',{name:'查看原文',exact:true})).toHaveAttribute('href',paper.evidence[0].url);
  await page.getByRole('link',{name:paper.title,exact:true}).click();
  await expect(page.locator('.abstract')).toHaveText(paper.abstract);
  await page.screenshot({path:testInfo.outputPath('paper-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('paper-mobile.png'),fullPage:true});
  await page.reload();
  await expect(page.locator('#back-link')).toHaveAttribute('href',/\/#\/daily$/);
});
