import { expect, test } from '@playwright/test';

const baseSettings = { enabled: false, topics: ['test'], time: '09:00', timezone: 'Asia/Shanghai', count: 3, lookback_days: 365, dedup_days: 30, conferences: ['ICLR'], sources: ['arxiv'] };

test('workspace search is locked and recommendation calls follow the current source', async ({ page }) => {
  const searches: unknown[] = [];
  const saves: string[] = [];
  const generates: string[] = [];
  await page.route('**/api/searches?source=arxiv', route => {
    const body = route.request().postDataJSON(); searches.push(body.sources);
    return route.fulfill({ status: 202, json: { id: 'scoped', request: body, done: true, started_at: '2026-10-18T00:00:00Z',
      papers: [], merged_count: 0, sources: [{ source: 'arxiv', state: 'success', count: 0, total: 0 }] } });
  });
  await page.route('**/api/recommendations**', route => {
    const url = new URL(route.request().url());
    const scope = url.searchParams.get('source') || 'all';
    const settings = { ...baseSettings, topics: [`${scope} topic`], sources: scope === 'all' ? ['arxiv', 'openalex'] : [scope] };
    const run = { id: scope, settings, date: '2026-10-18', started_at: '2026-10-18T00:00:00Z', status: 'empty', trigger: 'manual',
      note: `${scope} history`, papers: [], paper_count: 0, source_results: [], excluded_count: 0 };
    if (url.pathname.endsWith('/settings')) {
      saves.push(scope);
      expect(route.request().postDataJSON().sources).toEqual([scope]);
      return route.fulfill({ json: route.request().postDataJSON() });
    }
    if (url.pathname.endsWith('/runs')) {
      generates.push(scope);
      return route.fulfill({ status: 202, json: run });
    }
    if (url.pathname.includes('/runs/')) {
      expect(url.pathname.split('/').at(-1)).toBe(scope);
      return route.fulfill({ json: run });
    }
    return route.fulfill({ json: { settings, runs: [run], running: false, storage_error: null, next_run: null } });
  });
  await page.goto('/');
  await page.getByRole('link', { name: '进入 arXiv 专区', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'arXiv 论文检索', exact: true })).toBeVisible();
  await page.getByLabel('你想探索什么研究主题？').fill('compression');
  await page.getByRole('button', { name: '检索论文', exact: true }).click();
  await expect(page.locator('.status-card')).toHaveCount(1);
  expect(searches).toEqual([['arxiv']]);
  await page.getByRole('button', { name: '每日推荐', exact: true }).click();
  await expect(page.getByLabel('推荐研究主题')).toHaveValue('arxiv topic');
  await expect(page.getByRole('checkbox', { name: 'OpenAlex', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('设置已保存');
  await page.getByRole('button', { name: '立即生成', exact: true }).click();
  await expect.poll(() => generates).toEqual(['arxiv']);
  await page.getByRole('navigation', { name: '切换来源专区' }).getByRole('link', { name: 'OpenAlex', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'OpenAlex 每日推荐', exact: true })).toBeVisible();
  await expect(page.getByLabel('推荐研究主题')).toHaveValue('openalex topic');
  await expect(page.locator('.daily-papers')).not.toContainText('arxiv history');
  await page.reload();
  await expect(page.getByLabel('推荐研究主题')).toHaveValue('openalex topic');
  await page.getByRole('link', { name: '← 返回综合工作台' }).click();
  await page.getByRole('button', { name: '每日推荐', exact: true }).click();
  await expect(page.getByLabel('推荐研究主题')).toHaveValue('all topic');
  expect(saves).toEqual(['arxiv']);
  await page.goto('/#/sources/openreview/search');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'OpenReview 论文检索', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('live source-only recommendation remains separate from global and other sources', async ({ page, request }) => {
  test.skip(process.env.PAPERTRAIL_SOURCE_TEST !== '1', 'Requires the isolated validation server and explicit network opt-in.');
  expect((await (await request.get('/api/validation')).json()).isolated_recommendations).toBe(true);
  const originalGlobal = await (await request.get('/api/recommendations')).json();
  const saved = await request.put('/api/recommendations/settings?source=arxiv', { data: baseSettings });
  expect(saved.ok()).toBe(true);
  await page.goto('/#/sources/arxiv/daily');
  const created = page.waitForResponse(r => r.url().endsWith('/api/recommendations/runs?source=arxiv') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '立即生成', exact: true }).click();
  const id = (await (await created).json()).id;
  await expect.poll(async () => (await (await request.get(`/api/recommendations/runs/${id}?source=arxiv`)).json()).status, { timeout: 75000 }).not.toBe('running');
  const result = await (await request.get(`/api/recommendations/runs/${id}?source=arxiv`)).json();
  expect(result.status).toBe('success');
  expect(result.papers).toHaveLength(3);
  expect(result.papers.every((p: { sources: string[] }) => p.sources.length === 1 && p.sources[0] === 'arxiv')).toBe(true);
  await expect(page.locator('.daily-papers .paper-card')).toHaveCount(3);
  await page.reload();
  await expect(page.locator('.daily-papers .paper-card')).toHaveCount(3);
  expect((await request.get(`/api/recommendations/runs/${id}?source=openalex`)).status()).toBe(404);
  const globalAfter = await (await request.get('/api/recommendations')).json();
  expect(globalAfter.settings).toEqual(originalGlobal.settings);
  expect(globalAfter.runs).toEqual(originalGlobal.runs);
});
