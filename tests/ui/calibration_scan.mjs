import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5067';
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/Q3cAAAAASUVORK5CYII=', 'base64');
const browser = await chromium.launch({ headless: true, channel: 'chrome' });

try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      isMobile: width < 768,
      hasTouch: width < 768,
    });
    await context.request.get(`${base}/__ui/login/super_admin`);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    const response = await page.goto(`${base}/mobil/kalibrasyon`, { waitUntil: 'networkidle' });
    assert.equal(response.status(), 200);
    const first = page.locator('.calibration-mobile-item').first();
    const second = page.locator('.calibration-mobile-item').nth(1);
    assert.equal(await first.locator('[data-scan-ready]').isVisible(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);

    const chooserPromise = page.waitForEvent('filechooser');
    await first.locator('[data-scan-open]').click();
    const chooser = await chooserPromise;
    assert.equal(await chooser.element().getAttribute('capture'), 'environment');
    await chooser.setFiles({ name: 'scan-one.png', mimeType: 'image/png', buffer: png });
    await first.locator('[data-scan-ready]').waitFor({ state: 'visible' });
    assert.equal(await first.locator('[data-scan-preview] img').count(), 1);
    assert.equal(await second.locator('[data-scan-ready]').isVisible(), false);
    assert.equal(await first.locator('[data-scan-submit]').isVisible(), true);

    const secondChooserPromise = page.waitForEvent('filechooser');
    await first.locator('[data-scan-open]').click();
    await (await secondChooserPromise).setFiles({ name: 'scan-two.png', mimeType: 'image/png', buffer: png });
    assert.equal(await first.locator('[data-scan-preview] img').count(), 2);
    await first.locator('.calibration-scan-page button').first().click();
    assert.equal(await first.locator('[data-scan-preview] img').count(), 1);
    await page.screenshot({ path: `.tmp-calibration-scan-${width}.png`, fullPage: true });

    await first.locator('[data-scan-submit]').click();
    await page.waitForURL(/\/kalibrasyon\/\d+\/pdf/);
    assert.match(await page.locator('body').innerText(), /PDF.*eklendi|scan-two\.png|kalibrasyon-tarama/);
    const download = page.locator('a[href*="/pdf/"][href$="/indir"]').first();
    const href = await download.getAttribute('href');
    const pdf = await context.request.get(base + href);
    assert.equal(pdf.status(), 200);
    assert.equal((await pdf.body()).subarray(0, 5).toString(), '%PDF-');
    const detailChooserPromise = page.waitForEvent('filechooser');
    await page.locator('[data-scan-open]').click();
    await (await detailChooserPromise).setFiles({ name: 'detail.png', mimeType: 'image/png', buffer: png });
    await page.locator('[data-scan-ready]').waitFor({ state: 'visible' });
    await page.locator('[data-scan-cancel]').click();
    assert.equal(await page.locator('[data-scan-ready]').isVisible(), false);
    assert.equal(await page.locator('[data-scan-preview] img').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    await context.close();
    console.log(`calibration scan ${width}: ok`);
  }
} finally {
  await browser.close();
}
