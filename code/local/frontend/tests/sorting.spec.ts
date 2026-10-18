import { expect, test } from '@playwright/test';

const papers = [
  { id: 'b', title: 'Beta paper', date: '2026-01-01', score: .9, recommendation_score: 60 },
  { id: 'a', title: 'Alpha paper', date: '2026-10-01', score: .1, recommendation_score: 20 },
  { id: 'c', title: 'Gamma paper', date: null, score: .5, recommendation_score: 90 },
].map(p => ({ ...p, authors: ['Test Author'], abstract: 'Test abstract', abstract_source: 'arxiv',
  sources: ['arxiv'], date_kind: '首次提交', date_source: 'arxiv', reasons: ['Test reason'], topics: ['test'],
  evidence: [{ source: 'arxiv', source_id: p.id, url: 'https://arxiv.org/abs/2601.12345', title: p.title, cached: false }],
}));
const settings = { topics: ['test'], sources: ['arxiv'], conferences: ['ICLR'], enabled: false, time: '09:00', timezone: 'Asia/Shanghai', count: 10, lookback_days: 30, dedup_days: 30 };

test('search results sort instantly, restore relevance and do not fetch again', async ({ page }) => {
  let searches = 0;
  await page.route('**/api/searches', route => {
    searches++;
    return route.fulfill({ status: 202, json: { id: 'sorted', request: { query: 'test', sources: ['arxiv'], limit: 10, sort: 'date' },
      started_at: '2026-10-18T00:00:00Z', done: true, papers: [...papers].reverse(), merged_count: 0,
      sources: [{ source: 'arxiv', state: 'success', count: 3, total: 3, note: 'test' }],
    } });
  });
  await page.goto('/');
  await page.getByLabel('你想探索什么研究主题？').fill('test');
  await page.getByLabel('检索取数顺序').selectOption('date');
  await page.getByRole('button', { name: '检索论文', exact: true }).click();
  const titles = page.locator('.results .paper-title');
  await expect(titles).toHaveText(['Alpha paper', 'Beta paper', 'Gamma paper']);
  await page.getByLabel('检索结果排序').selectOption('date_asc');
  await expect(titles).toHaveText(['Beta paper', 'Alpha paper', 'Gamma paper']);
  await page.getByLabel('检索结果排序').selectOption('rank');
  await expect(titles).toHaveText(['Beta paper', 'Gamma paper', 'Alpha paper']);
  await page.getByLabel('检索结果排序').selectOption('title');
  await expect(titles).toHaveText(['Alpha paper', 'Beta paper', 'Gamma paper']);
  await page.getByLabel('检索取数顺序').selectOption('relevance');
  await expect(titles).toHaveText(['Beta paper', 'Gamma paper', 'Alpha paper']);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel('检索结果排序').selectOption('date_desc');
  await expect(titles).toHaveText(['Alpha paper', 'Beta paper', 'Gamma paper']);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(searches).toBe(1);
});

test('daily sorting survives polling and history changes without generating or saving', async ({ page }) => {
  let reads = 0;
  const writes: string[] = [];
  page.on('request', request => { if (request.method() !== 'GET') writes.push(request.url()); });
  const run = { id: 'latest', date: '2026-10-18', started_at: '2026-10-18T00:00:00Z', status: 'success', trigger: 'manual',
    settings, paper_count: 3, papers, note: 'Test run', excluded_count: 0, source_results: [] };
  await page.route('**/api/recommendations', route => route.fulfill({ json: {
    settings, runs: [run, { ...run, id: 'older', date: '2026-10-17' }], running: false, next_run: null, storage_error: null,
  } }));
  await page.route('**/api/recommendations/runs/*', route => {
    reads++;
    const older = route.request().url().endsWith('/older');
    return route.fulfill({ json: { ...run, id: older ? 'older' : 'latest', date: older ? '2026-10-17' : run.date } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '每日推荐', exact: true }).click();
  const titles = page.locator('.daily-papers .paper-title');
  const order = page.getByLabel('推荐列表排序');
  await expect(titles).toHaveText(['Gamma paper', 'Beta paper', 'Alpha paper']);
  await order.selectOption('date_desc');
  await expect(titles).toHaveText(['Alpha paper', 'Beta paper', 'Gamma paper']);
  const before = reads;
  await expect.poll(() => reads, { timeout: 7000 }).toBeGreaterThan(before);
  await expect(titles).toHaveText(['Alpha paper', 'Beta paper', 'Gamma paper']);
  await page.locator('.run-history button').filter({ hasText: '2026-10-17' }).click();
  await expect(order).toHaveValue('date_desc');
  await expect(titles).toHaveText(['Alpha paper', 'Beta paper', 'Gamma paper']);
  await order.selectOption('date_asc');
  await expect(titles).toHaveText(['Beta paper', 'Alpha paper', 'Gamma paper']);
  await order.selectOption('title');
  await expect(titles).toHaveText(['Alpha paper', 'Beta paper', 'Gamma paper']);
  await order.selectOption('rank');
  await expect(titles).toHaveText(['Gamma paper', 'Beta paper', 'Alpha paper']);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(writes).toEqual([]);
});
