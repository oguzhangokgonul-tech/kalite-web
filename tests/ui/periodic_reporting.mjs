import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5067';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];

try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({
      viewport: { width, height: 960 },
      hasTouch: width < 1400,
      isMobile: width < 768,
      acceptDownloads: true,
    });
    const page = await context.newPage();
    await page.goto(`${base}/__ui/login/super_admin`, { waitUntil: 'domcontentloaded' });
    await page.goto(`${base}/rapor-merkezi`, { waitUntil: 'domcontentloaded' });
    assert.equal(page.url().includes('/rapor-merkezi'), true);
    assert.match(await page.locator('body').innerText(), /Rapor Merkezi/);
    assert.equal(
      await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)),
      0,
    );

    await page.locator('#reportPeriod').selectOption('quarter');
    await page.getByRole('button', { name: 'Uygula' }).click();
    await page.waitForLoadState('domcontentloaded');
    assert.equal(await page.locator('#reportPeriod').inputValue(), 'quarter');
    assert.match(await page.locator('body').innerText(), /3 Aylık/);

    const moduleOptions = await page.locator('#activityModule option').count();
    assert.equal(moduleOptions, 46);
    await page.locator('#activityModule').selectOption('maintenance');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Excel İndir' }).last().click();
    const download = await downloadPromise;
    assert.match(download.suggestedFilename(), /module-activity-maintenance/);

    await fs.mkdir('.tmp-ui-audit/responsive', { recursive: true });
    await page.screenshot({
      path: `.tmp-ui-audit/responsive/${width}-periodic-reporting.png`,
      fullPage: true,
    });
    completed.push(width);
    await context.close();
  }
} finally {
  await browser.close();
  await fs.mkdir('.tmp-ui-audit/responsive', { recursive: true });
  await fs.writeFile(
    '.tmp-ui-audit/responsive/periodic-reporting.json',
    JSON.stringify({ completed }, null, 2),
  );
}
