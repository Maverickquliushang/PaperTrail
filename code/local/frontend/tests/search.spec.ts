import { expect, test } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const requestData = { query: 'example query', sources: ['arxiv', 'openalex', 'huggingface'], limit: 10, start_date: null, end_date: null, sort: 'relevance' };
const status = (source: string, state: string, note = '') => ({ source, state, count: 0, total: null, scanned: 0, note, cached_at: null, retrieved_at: '2026-10-18T00:00:00Z', error_code: null });
const initial = { id: 'test-task', request: requestData, started_at: '2026-10-18T00:00:00Z', done: false, sources: [status('arxiv', 'running'), status('openalex', 'running'), status('huggingface', 'running')], papers: [], raw_count: 0, merged_count: 0 };
const paper = {
  id: 'arxiv:2601.12345', title: 'A verifiable paper for browser testing', authors: ['Test Author'],
  abstract: 'This is a deterministic browser test abstract.', abstract_source: 'arxiv', date: '2026-01-01', date_kind: '首次提交', date_source: 'arxiv', arxiv_id: '2601.12345', doi: null, sources: ['arxiv'],
  evidence: [{ source: 'arxiv', source_id: '2601.12345', title: 'A verifiable paper for browser testing', url: 'https://arxiv.org/abs/2601.12345', pdf_url: 'https://arxiv.org/pdf/2601.12345', publication_date: null, submitted_date: '2026-01-01', updated_date: null, listed_date: null, venue: null, retrieved_at: '2026-10-18T00:00:00Z', cached: false }],
};

test('partial source failure retains papers and accessible source details', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/searches', route => route.fulfill({ status: 202, json: initial }));
  await page.route('**/api/searches/test-task/events', route => route.fulfill({
    contentType: 'text/event-stream', body: `event: snapshot\ndata: ${JSON.stringify({ ...initial, done: true, papers: [paper], raw_count: 1, sources: [{ ...status('arxiv', 'success'), count: 1 }, status('openalex', 'error', '来源请求超时，请稍后重试。'), status('huggingface', 'limited', '候选上限 120，总命中数未知。')] })}\n\n`,
  }));
  await page.goto('/');
  await page.getByLabel('你想探索什么研究主题？').fill('example query');
  await page.getByRole('button', { name: '检索论文', exact: true }).click();
  await expect(page.getByText('1 个来源失败，其余结果已保留')).toBeVisible();
  await expect(page.locator('.paper-card')).toHaveCount(1);
  await page.getByRole('button', { name: paper.title }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByText('来源与时间记录', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog').getByRole('link', { name: 'PDF', exact: true })).toHaveAttribute('href', 'https://arxiv.org/pdf/2601.12345');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('form validation and mobile layout', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('你想探索什么研究主题？').fill('test');
  for (const name of ['arXiv', 'OpenAlex', 'Hugging Face', '顶会索引', 'OpenReview']) await page.getByRole('checkbox', { name, exact: true }).uncheck();
  await page.getByRole('button', { name: '检索论文', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('至少选择一个来源');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('checkbox', { name: 'arXiv', exact: true }).check();
  await page.getByLabel('开始日期', { exact: true }).fill('2026-10-18');
  await page.getByLabel('结束日期', { exact: true }).fill('2026-01-01');
  await page.getByRole('button', { name: '检索论文', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('开始日期不能晚于结束日期');
});

test('all source failures are not presented as no papers', async ({ page }) => {
  await page.route('**/api/searches', route => route.fulfill({ status: 202, json: initial }));
  await page.route('**/api/searches/test-task/events', route => route.fulfill({ contentType: 'text/event-stream', body: `event: snapshot\ndata: ${JSON.stringify({ ...initial, done: true, sources: initial.sources.map(s => ({ ...s, state: 'error', note: '无法连接来源' })) })}\n\n` }));
  await page.goto('/');
  await page.getByLabel('你想探索什么研究主题？').fill('example query');
  await page.getByRole('button', { name: '检索论文', exact: true }).click();
  await expect(page.getByText('所有来源检索失败', { exact: true })).toBeVisible();
  await expect(page.getByText('请查看上方来源状态；请求失败不代表没有论文。')).toBeVisible();
});

test('live five-channel search and desktop/mobile screenshots', async ({ page, request }) => {
  test.skip(process.env.PAPERTRAIL_LIVE_TEST !== '1', 'Explicit opt-in: this test calls public paper APIs.');
  const output = resolve('..', 'output', 'private', 'm1-validation');
  await mkdir(output, { recursive: true });
  await page.goto('/');
  await page.screenshot({ path: resolve(output, 'home-desktop.png'), fullPage: true });
  await page.getByLabel('你想探索什么研究主题？').fill('transformer');
  await page.getByLabel('每个来源结果数').selectOption('5');
  const created = page.waitForResponse(r => r.url().endsWith('/api/searches') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '检索论文', exact: true }).click();
  const task = await (await created).json();
  await expect(page.getByRole('button', { name: '检索论文', exact: true })).toBeEnabled({ timeout: 75000 });
  const result = await (await request.get(`/api/searches/${task.id}`)).json();
  await writeFile(resolve(output, 'live-result.json'), JSON.stringify(result, null, 2));
  await page.screenshot({ path: resolve(output, 'results-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(output, 'results-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(result.sources.every((s: { state: string }) => ['success', 'limited'].includes(s.state))).toBe(true);
  expect(result.sources.every((s: { count: number }) => s.count > 0)).toBe(true);
  expect(result.done).toBe(true);
});
