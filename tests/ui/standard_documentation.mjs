import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || '../../.tmp-playwright/node_modules/playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5079';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
try {
  for (const width of [390, 768, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
    await page.goto(`${base}/__ui/login/super_admin`);
    await page.goto(`${base}/standart-dokumantasyon`);
    assert.equal(await page.locator('h1').first().textContent(), 'Standart Dokümantasyon');
    const initialCount = await page.locator('.standard-heading').count();
    await page.locator('.standard-heading summary').first().click();
    assert.equal(await page.locator('.standard-heading').first().getAttribute('open'), '');
    assert.equal(await page.locator('.standard-heading').first().locator('.standard-documents a').count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: `.tmp-standard-${width}.png`, fullPage: true });
    await page.getByRole('link', { name: /Standart Ana Başlık Oluştur/ }).first().click();
    assert.equal(await page.locator('input[name="title"]').count(), 1);
    await page.locator('#standard-document-search').fill('iç');
    assert.equal(await page.locator('.standard-option:not([hidden])').count(), 1);
    await page.locator('#standard-document-search').fill('');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: `.tmp-standard-form-${width}.png`, fullPage: true });
    if (width === 390) {
      await page.locator('input[name="title"]').fill('ISO 14001 Çevre Standardı');
      await page.locator('input[name="related_standard"]').fill('ISO 14001');
      await page.locator('input[name="technical_heading_no"]').fill('X'.repeat(80));
      await page.locator('input[name="document_ids"]').first().check();
      await page.getByRole('button', { name: 'Kaydet' }).click();
      assert.equal(await page.locator('.standard-heading').count(), initialCount + 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.screenshot({ path: '.tmp-standard-long-mobile.png', fullPage: true });
      await page.locator('.standard-heading').last().locator('summary').click();
      await page.locator('.standard-heading').last().getByRole('link', { name: 'Düzenle' }).click();
      assert.equal(await page.locator('input[name="title"]').inputValue(), 'ISO 14001 Çevre Standardı');
    }
    await page.close();
  }
  console.log('Standard Documentation responsive checks passed.');
} finally {
  await browser.close();
}
