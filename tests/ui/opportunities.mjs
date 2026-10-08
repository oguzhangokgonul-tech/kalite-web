import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5099';
const out = '.tmp-ui-audit/opportunities';
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: 'chrome', args: ['--disable-gpu'] });
const results = [];
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width < 1200 });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const login = async role => {
      await page.goto('about:blank');
      assert.equal((await context.request.get(`${base}/__ui/login/${role}`)).status(), 200);
    };
    const submit = name => Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle' }),
      page.getByRole('button', { name, exact: true }).click(),
    ]);
    const layout = async name => {
      await page.waitForLoadState('networkidle');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width} ${name} overflow`);
      await page.screenshot({ path: `${out}/${width}-${name}.png`, fullPage: true });
    };
    try {
      await login('department_manager');
      await page.goto(`${base}/risk-firsat-portfoyu/firsat/yeni`);
      await page.locator('#title').fill(`Enerji Verimliliği Fırsatı ${width}`);
      await page.locator('#owner_user_id').selectOption({ label: 'department_manager' });
      await page.locator('#analysis_date').fill('2026-10-07');
      await page.locator('#due_date').fill('2026-12-01');
      await page.locator('#review_date').fill('2026-12-02');
      await page.locator('#likelihood').selectOption('4');
      await page.locator('#benefit').selectOption('5');
      for (const key of ['description', 'expected_benefit', 'planned_action', 'success_criteria', 'source_reference']) {
        await page.locator(`#${key}`).fill(`Türkçe kayıt: ${key}`);
      }
      await page.locator('#title').focus();
      await page.keyboard.press('Tab');
      assert.ok(await page.locator('#owner_user_id').evaluate(el => el === document.activeElement));
      await layout('form');
      await submit('Kaydet');
      await page.waitForURL(/\/firsat\/\d+$/);
      const detail = page.url();
      await layout('draft');
      await submit('Aktifleştir');
      assert.equal(await page.getByRole('button', { name: 'Değerlendirmeyi Kaydet', exact: true }).count(), 0);
      await login('viewer');
      assert.equal((await context.request.get(detail, { maxRedirects: 0 })).status(), 404);
      await login('management_representative');
      await page.goto(detail);
      await page.locator('#result_note').fill('Ölçülen tüketimde yüzde on iyileşme.');
      await page.locator('#evidence_sources').fill('Ekim ve Kasım sayaç ölçüm kayıtları.');
      await submit('Değerlendirmeyi Kaydet');
      assert.equal(await page.getByRole('link', { name: 'Düzenle', exact: true }).count(), 0);
      await layout('realized');
      const download = page.waitForEvent('download');
      await page.getByRole('link', { name: 'Rapor İndir', exact: true }).click();
      assert.equal(await (await download).failure(), null);
      await page.locator('#reopen_note').fill('Yeni dönem için yeniden planlanacak.');
      await submit('Yeniden Aç');
      assert.equal(await page.getByRole('link', { name: 'Düzenle', exact: true }).count(), 1);
      await page.locator('#archive_note').fill('Yeni çalışma ile değiştirildi.');
      await submit('Arşive Al');
      await layout('archived');
      await page.goto(`${base}/risk-firsat-portfoyu`);
      await layout('portfolio');
      assert.deepEqual(errors, []);
      results.push({ width, result: 'passed', csrf: 'enabled', flow: 'create/activate/roles/evaluate/export/reopen/archive' });
    } finally { await context.close(); }
  }
} finally {
  await browser.close();
  await fs.writeFile(`${out}/results.json`, JSON.stringify(results, null, 2));
}
console.log(JSON.stringify(results, null, 2));
