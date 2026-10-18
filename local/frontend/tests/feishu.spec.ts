import { test, expect } from '@playwright/test';

test('Feishu setup saves locally, pairs explicitly, and enables the five source pushes', async ({ page }) => {
  let status = { configured: false, app_id: '', enabled: false, connection: '未配置', error: '', paired: false, chat_id: '', push_enabled: false,
    push_sources: ['arxiv', 'openalex', 'huggingface', 'conferences', 'openreview'], deliveries: [], authorization_url: '', registration_status: '尚未开始' };
  const writes: { path: string; body: unknown }[] = [];
  await page.route('**/api/feishu**', route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== 'GET') {
      const body = route.request().postDataJSON();
      writes.push({ path, body });
      if (path.endsWith('/credentials')) status = { ...status, configured: true, app_id: body.app_id, enabled: body.enabled, connection: '已连接' };
      if (path.endsWith('/pairing')) return route.fulfill({ json: { code: 'ABCDEF', expires_in: 600 } });
      if (path.endsWith('/push')) status = { ...status, push_enabled: body.enabled };
    }
    return route.fulfill({ json: status });
  });
  await page.goto('/#/feishu');
  await expect(page.getByRole('heading', { name: '把论文带进群聊' })).toBeVisible();
  await expect(page.getByRole('button', { name: '开启五个专区的每日推送' })).toBeDisabled();
  await page.getByLabel('App ID', { exact: true }).fill('cli_test');
  await page.getByLabel('App Secret', { exact: true }).fill('fake-secret-for-test');
  await page.getByRole('button', { name: '保存并连接' }).click();
  await expect(page.getByLabel('App Secret', { exact: true })).toHaveValue('');
  await page.getByRole('button', { name: '生成绑定码' }).click();
  await expect(page.locator('.pair-code')).toContainText('绑定 ABCDEF');
  status = { ...status, paired: true, chat_id: 'oc_test' };
  await expect(page.getByRole('button', { name: '开启五个专区的每日推送' })).toBeEnabled();
  await page.getByRole('button', { name: '开启五个专区的每日推送' }).click();
  await expect(page.getByRole('button', { name: '关闭每日推送' })).toBeVisible();
  expect(writes.at(-1)?.body).toEqual({ enabled: true, sources: ['arxiv', 'openalex', 'huggingface', 'conferences', 'openreview'] });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: '论文检索', exact: true }).click();
  await expect(page.locator('.source-card')).toHaveCount(5);
});
