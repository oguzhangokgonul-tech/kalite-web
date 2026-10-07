import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5098';
const out = '.tmp-ui-audit/context';
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: 'chrome', args: ['--disable-gpu'] });
const results = [];
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width < 1200 });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const login = role => context.request.get(`${base}/__ui/login/${role}`);
    const submit = async name => Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle' }),
      page.getByRole('button', { name, exact: true }).click(),
    ]);
    const layout = async name => {
      await page.waitForLoadState('networkidle');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), name + ' overflow');
      await page.screenshot({ path: `${out}/${width}-${name}.png`, fullPage: true });
    };
    try {
      await login('department_manager');
      await page.goto(`${base}/kurulus-baglami/yeni`);
      await page.locator('#title').fill(`Üretim Bağlam ${width}`);
      await page.locator('#scope').fill('Üretim kalite planlaması');
      await page.locator('#owner_user_id').selectOption({ label: 'department_manager' });
      await page.locator('#analysis_date').fill('2026-10-05');
      await page.locator('#review_date').fill('2027-01-05');
      for (const key of ['internal_issues', 'external_issues', 'climate_reason', 'evidence_sources', 'strategy']) {
        await page.locator(`#${key}`).fill(`Türkçe değerlendirme: ${key}`);
      }
      await page.locator('#climate_relevance').selectOption('relevant');
      await page.locator('#title').focus();
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('#owner_user_id').evaluate(el => el === document.activeElement), true);
      await layout('form');
      await submit('Taslağı Kaydet');
      await page.waitForURL(/\/kurulus-baglami\/\d+$/);
      const detail = page.url();
      await layout('draft');
      assert.equal(await page.getByRole('button', { name: 'Gözden Geçirmeyi Tamamla' }).count(), 0);
      await page.getByRole('link', { name: 'İlgili Taraflar Matrisi', exact: true }).click();
      await page.waitForURL(/\/ilgili-taraflar$/);
      await layout('stakeholders');
      await page.getByRole('link', { name: 'Kuruluş Bağlamı', exact: true }).click();
      await page.waitForURL(/\/kurulus-baglami$/);
      await page.waitForLoadState('networkidle');
      await page.goto('about:blank');
      await login('viewer');
      assert.equal((await context.request.get(detail, { maxRedirects: 0 })).status(), 404);
      await login('management_representative');
      await page.goto(detail);
      await page.locator('#review_note').fill('İç ve dış hususlar, iklim ve strateji değerlendirildi.');
      await submit('Gözden Geçirmeyi Tamamla');
      await layout('reviewed');
      assert.equal(await page.getByRole('link', { name: 'Düzenle', exact: true }).count(), 0);
      const download = page.waitForEvent('download');
      await page.getByRole('link', { name: 'Rapor İndir', exact: true }).click();
      assert.equal(await (await download).failure(), null);
      await page.locator('#reopen_note').fill('Yeni dönem gözden geçirmesi');
      await submit('Yeniden Aç');
      assert.equal(await page.getByRole('link', { name: 'Düzenle', exact: true }).count(), 1);
      await page.locator('#archive_note').fill('Dönem arşivi');
      await submit('Arşive Al');
      await layout('archive');
      await page.goto(`${base}/kurulus-baglami`);
      await layout('dashboard');
      const action = await page.getByRole('link', { name: 'Analizi Aç', exact: true }).first().boundingBox();
      assert.ok(action && action.x >= 0 && action.x + action.width <= width + 1, 'list action clipped');
      assert.deepEqual(errors, []);
      results.push({ width, result: 'passed', workflow: 'create/roles/review/export/reopen/archive', csrf: 'enabled' });
    } finally { await context.close(); }
  }
} finally {
  await browser.close();
  await fs.writeFile(`${out}/results.json`, JSON.stringify(results, null, 2));
}
console.log(JSON.stringify(results, null, 2));
