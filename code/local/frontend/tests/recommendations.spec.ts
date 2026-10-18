import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const settings = { enabled: false, topics: [], time: '09:00', timezone: 'Asia/Shanghai', count: 10, lookback_days: 30, dedup_days: 30, sources: ['arxiv'], conferences: ['ICLR'] };

test('group setting changes refresh the web form without overwriting an unsaved draft', async ({ page }) => {
  let saved = { ...settings, topics: ['compression'] };
  let reads = 0;
  await page.route('**/api/recommendations', route => {
    reads++;
    return route.fulfill({ json: { settings: saved, runs: [], running: false, next_run: null, storage_error: null } });
  });
  await page.goto('/#/daily');
  await expect(page.getByLabel('推荐研究主题')).toHaveValue('compression');
  saved = { ...saved, topics: ['low rank decomposition'], count: 20 };
  await expect(page.getByLabel('推荐研究主题')).toHaveValue('low rank decomposition', { timeout: 7000 });
  await expect(page.getByLabel('最多推荐篇数')).toHaveValue('20');
  await page.getByLabel('推荐研究主题').fill('my unsaved draft');
  saved = { ...saved, topics: ['quantization'], count: 5 };
  const before = reads;
  await expect.poll(() => reads, { timeout: 7000 }).toBeGreaterThan(before);
  await expect(page.getByLabel('推荐研究主题')).toHaveValue('my unsaved draft');
  await expect(page.getByLabel('最多推荐篇数')).toHaveValue('20');
  await page.reload();
  await expect(page.getByLabel('推荐研究主题')).toHaveValue('quantization');
  await expect(page.getByLabel('最多推荐篇数')).toHaveValue('5');
});

test('recommendation settings validation, save, mobile readability and service error', async ({ page }) => {
  let saved = { ...settings, topics: [] as string[] };
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/recommendations', route => route.fulfill({ json: { settings: saved, runs: [], running: false, next_run: null, storage_error: null } }));
  await page.route('**/api/recommendations/settings', async route => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: saved });
  });
  await page.route('**/api/recommendations/runs', route => route.fulfill({ status: 503, json: { detail: '本地文件保存失败' } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: '每日推荐', exact: true }).click();
  await expect(page.getByRole('button', { name: '立即生成' })).toBeDisabled();
  await page.getByLabel('推荐研究主题').fill('transformer\nretrieval');
  await page.getByRole('button', { name: '保存设置' }).click();
  await expect(page.getByRole('status')).toContainText('设置已保存');
  expect(saved.topics).toEqual(['transformer', 'retrieval']);
  await page.getByRole('button', { name: '立即生成' }).click();
  await expect(page.getByRole('alert')).toContainText('本地文件保存失败');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await page.getByLabel('推荐研究主题').evaluate(e => parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(16);
  expect(errors).toEqual([]);
});

test('live isolated daily recommendation persists and opens paper details', async ({ page, request }) => {
  test.skip(process.env.PAPERTRAIL_DAILY_TEST !== '1', 'Only use with the isolated validation server.');
  const marker = await request.get('/api/validation');
  expect(marker.ok()).toBe(true);
  expect((await marker.json()).isolated_recommendations).toBe(true);
  await request.put('/api/recommendations/settings', { data: { ...settings, topics: ['transformer'], lookback_days: 365, count: 5, sources: ['arxiv', 'openalex', 'huggingface', 'conferences', 'openreview'], conferences: ['ICLR', 'ICML', 'NeurIPS', 'CVPR'] } });
  await page.goto('/');
  await page.getByRole('button', { name: '每日推荐', exact: true }).click();
  const created = page.waitForResponse(r => r.url().endsWith('/api/recommendations/runs') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '立即生成', exact: true }).click();
  const id = (await (await created).json()).id;
  await expect.poll(async () => (await (await request.get(`/api/recommendations/runs/${id}`)).json()).status, { timeout: 75000 }).not.toBe('running');
  await expect(page.locator('.daily-papers .paper-card')).toHaveCount(5, { timeout: 10000 });
  await page.reload();
  await page.getByRole('button', { name: '每日推荐', exact: true }).click();
  await expect(page.locator('.daily-papers .paper-card')).toHaveCount(5);
  const output = resolve('..', 'output', 'private', 'daily-validation');
  await mkdir(output, { recursive: true });
  await page.screenshot({ path: resolve(output, 'daily-desktop.png'), fullPage: true });
  await page.locator('.daily-papers .paper-title').first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').getByText('来源与时间记录', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: resolve(output, 'daily-mobile.png'), fullPage: true });
});
