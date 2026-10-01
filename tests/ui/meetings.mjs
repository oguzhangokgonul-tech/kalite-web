import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5096';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const results = [];
await fs.mkdir('.tmp-ui-audit/meetings', { recursive: true });
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width < 1200 });
    await context.request.get(base + '/__ui/login/department_manager');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const checkLayout = async name => {
      await page.waitForLoadState('networkidle');
      await page.screenshot({ path: `.tmp-ui-audit/meetings/${width}-${name}.png`, fullPage: true });
      const overflow = await page.evaluate(() => [...document.querySelectorAll('main *')].filter(el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && (rect.right > innerWidth + 1 || rect.left < -1);
      }).slice(0, 10).map(el => ({ tag: el.tagName, class: el.className, width: el.getBoundingClientRect().width })));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, name + ' overflow: ' + JSON.stringify(overflow));
    };
    await page.goto(base + '/toplantilar/yeni');
    await page.getByLabel('Başlık').fill(`Üretim ve kalite değerlendirme toplantısı ${width}`);
    await page.getByLabel('Tarih / Saat').fill('2026-09-01T10:30');
    await page.getByLabel('Yer', { exact: true }).fill('Toplantı salonu');
    await page.getByLabel('Gündem').fill('Üretim kalite göstergeleri ve kontrol listeleri.');
    await page.getByLabel('Tutanak', { exact: true }).fill('Kontrol listesi güncellenecek.');
    await page.getByLabel('department_staff', { exact: true }).check();
    await checkLayout('form');
    await page.getByRole('button', { name: 'Taslağı Kaydet' }).click();
    await page.waitForURL(/\/toplantilar\/\d+$/);
    const detailUrl = page.url();
    await page.locator('#new-decision-title').fill('Kontrol listesini güncelle');
    await page.locator('#new-decision-owner').selectOption({ label: 'department_staff' });
    await page.locator('#new-decision-due').fill('2026-10-02');
    await page.getByRole('button', { name: 'Karar Ekle' }).click();
    await page.getByRole('button', { name: 'Yayımla', exact: true }).click();
    await page.getByRole('button', { name: 'Tutanağı Kesinleştir' }).click();
    assert.equal(await page.getByRole('button', { name: 'Arşivle' }).isDisabled(), true);
    await checkLayout('detail');
    await context.request.get(base + '/__ui/login/department_staff');
    await page.goto(detailUrl);
    assert.equal(await page.getByRole('button', { name: 'Yeniden Aç', exact: true }).count(), 0);
    await page.getByText('Kararı Tamamla', { exact: true }).click();
    await page.getByLabel('Tamamlanma Notu').fill('Liste güncellendi ve kontrol edildi.');
    await page.getByRole('button', { name: 'Tamamla', exact: true }).click();
    await page.waitForLoadState('networkidle');
    await context.request.get(base + '/__ui/login/department_manager');
    await page.goto(detailUrl);
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `.tmp-ui-audit/meetings/${width}-before-archive.png`, fullPage: true });
    await page.getByRole('button', { name: 'Arşivle', exact: true }).click();
    await page.getByText('Arşiv', { exact: true }).waitFor();
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('link', { name: 'Excel', exact: true }).click();
    const download = await downloadEvent;
    assert.ok(download.suggestedFilename().endsWith('.xlsx'));
    assert.equal(await download.failure(), null);
    await page.goto(base + '/toplantilar');
    await checkLayout('list');
    assert.deepEqual(errors, []);
    results.push({ width, workflow: 'passed', layout: 'passed', excel: 'passed' });
    await context.close();
  }
} finally {
  await browser.close();
  await fs.writeFile('.tmp-ui-audit/meetings/results.json', JSON.stringify(results, null, 2));
}
console.log(JSON.stringify(results, null, 2));
