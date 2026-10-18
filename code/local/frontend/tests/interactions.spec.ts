import { expect, test } from '@playwright/test';

test('all source cards enter dedicated pages with hover, keyboard and back navigation', async ({ page }) => {
  const writes: string[] = [];
  page.on('request', request => { if (request.method() !== 'GET') writes.push(request.url()); });
  await page.goto('/');
  await expect(page.locator('.source-card')).toHaveCount(5);
  for (const [source, name] of [['arxiv', 'arXiv'], ['openalex', 'OpenAlex'], ['huggingface', 'Hugging Face'], ['conferences', '顶会索引'], ['openreview', 'OpenReview']]) {
    const card = page.getByRole('link', { name: `进入 ${name} 专区`, exact: true });
    await card.hover();
    await expect.poll(() => card.evaluate(e => getComputedStyle(e).transform)).not.toBe('none');
    await card.click();
    await expect(page).toHaveURL(new RegExp(`#/sources/${source}/search$`));
    await expect(page.getByRole('heading', { name: `${name} 论文检索`, exact: true })).toBeVisible();
    await expect(page.getByRole('checkbox', { name: 'arXiv', exact: true })).toHaveCount(0);
    await page.goBack();
    await expect(page.locator('.source-card')).toHaveCount(5);
  }
  const first = page.locator('.source-card').first();
  await first.focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#\/sources\/arxiv\/search$/);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'arXiv 论文检索', exact: true })).toBeVisible();
  await page.getByRole('link', { name: '← 返回综合工作台' }).click();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await first.hover();
  await expect.poll(() => first.evaluate(e => getComputedStyle(e).transform)).toBe('none');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(writes).toEqual([]);
});

test('paper, status and detail cards have hover feedback and reduced-motion support', async ({ page }) => {
  const paper = { id: 'p', title: 'Hover example paper', date: '2026-10-18', authors: ['Author'], sources: ['arxiv'],
    evidence: [{ source: 'arxiv', title: 'Hover example paper', url: 'https://arxiv.org/abs/2601.12345', retrieved_at: '2026-10-18T00:00:00Z' }] };
  await page.route('**/api/searches', route => route.fulfill({ status: 202, json: { id: 'test', done: true,
    request: { query: 'test', sources: ['arxiv'], limit: 10, sort: 'relevance' }, started_at: '2026-10-18T00:00:00Z',
    sources: [{ source: 'arxiv', state: 'success', count: 1, total: 1 }], papers: [paper], merged_count: 0 } }));
  await page.goto('/');
  await page.getByLabel('你想探索什么研究主题？').fill('test');
  await page.getByRole('button', { name: '检索论文', exact: true }).click();
  for (const selector of ['.paper-card', '.status-card']) {
    const card = page.locator(selector).first();
    await card.hover();
    await expect.poll(() => card.evaluate(e => getComputedStyle(e).transform)).not.toBe('none');
  }
  await page.getByRole('button', { name: '摘要与来源', exact: true }).click();
  const evidence = page.locator('.evidence-block');
  await evidence.hover();
  await expect.poll(() => evidence.evaluate(e => getComputedStyle(e).transform)).not.toBe('none');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect.poll(() => evidence.evaluate(e => getComputedStyle(e).transform)).toBe('none');
});
