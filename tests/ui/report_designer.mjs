import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5091';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
const failures = [];

try {
  for (const width of [390, 768, 1024, 1440]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      hasTouch: true,
      isMobile: width < 768,
    });
    await context.request.get(base + '/__ui/login/management_representative');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    page.setDefaultTimeout(15000);
    try {
      const response = await page.goto(base + '/rapor-merkezi/tasarim/yeni', { waitUntil: 'domcontentloaded' });
      assert.equal(response.status(), 200);
      await page.locator('#reportName').fill(`Responsive Aksiyon Raporu ${width}`);
      await page.locator('#reportSource').selectOption('actions_master');
      await page.locator('input[name="columns"]').first().waitFor({ state: 'visible' });
      const columnChecks = page.locator('input[name="columns"]');
      for (let index = 0; index < await columnChecks.count(); index += 1) {
        await columnChecks.nth(index).uncheck();
      }
      for (const value of ['Aksiyon No', 'Başlık', 'Departman', 'Durum']) {
        await page.locator(`input[name="columns"][value="${value}"]`).check();
      }
      await page.locator('[name="filter_column"]').first().selectOption('Departman');
      await page.locator('[name="filter_operator"]').first().selectOption('equals');
      await page.locator('[name="filter_value"]').first().fill('Kalite');
      await page.locator('[name="sort_column"]').first().selectOption('Başlık');
      await page.locator('[name="sort_direction"]').first().selectOption('asc');
      await page.locator('#reportGroupBy').selectOption('Durum');
      const [previewPage] = await Promise.all([
        page.waitForEvent('popup'),
        page.getByRole('button', { name: 'Önizle', exact: true }).click(),
      ]);
      await previewPage.waitForLoadState('domcontentloaded');
      assert.match(await previewPage.locator('body').innerText(), /Bu bir önizlemedir/);
      assert.equal(await previewPage.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
      await previewPage.close();
      await page.getByRole('button', { name: 'Raporu Oluştur', exact: true }).click();
      await page.waitForURL('**/rapor-merkezi/tasarim/*');
      assert.match(await page.locator('body').innerText(), /Responsive Aksiyon Raporu/);
      assert.match(await page.locator('body').innerText(), /Rapor Sonuçları/);
      assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
      assert.deepEqual(errors, []);
      await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-report-designer.png`, fullPage: true });
      completed.push(width);
    } catch (error) {
      failures.push({
        width,
        error: error.message,
        url: page.url(),
        body: (await page.locator('body').innerText()).slice(0, 1400),
      });
    }
    await context.close();
  }
} finally {
  await browser.close();
  await fs.writeFile(
    '.tmp-ui-audit/responsive/report-designer.json',
    JSON.stringify({ completed, failures }, null, 2),
  );
}

console.log(JSON.stringify({ completed, failures }, null, 2));
if (failures.length) process.exitCode = 1;
