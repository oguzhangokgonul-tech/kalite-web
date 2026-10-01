import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5093';
const output = '.tmp-ui-audit/import-center';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const results = [];
const errors = [];
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1000 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    let response = await page.goto(base + '/veri-ice-aktarma');
    assert.equal(response.status(), 200);
    assert.equal(await page.locator('h1').innerText(), 'Veri İçe Aktarma');
    assert.equal(await page.locator('.locale-switcher-sidebar, .locale-switcher-login').count(), 0);
    assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
    await page.locator('#import-company').selectOption({ index: 1 });
    await page.locator('#import-module').selectOption('departments');
    const csv = `Departman Adı;Sıralama\nUI ${width};${width === 390 ? 1 : width === 768 ? 2 : 3}\n`;
    await page.locator('#import-source-file').setInputFiles({
      name: `ui-${width}.csv`, mimeType: 'text/csv', buffer: Buffer.from(csv, 'utf8'),
    });
    await Promise.all([
      page.waitForURL(url => /\/veri-ice-aktarma\/\d+$/.test(url.pathname)),
      page.getByRole('button', { name: 'Önizle' }).click(),
    ]);
    const createSummary = page.locator('section[aria-label="Doğrulama özeti"] > div').filter({ hasText: 'Oluşturulacak' });
    assert.equal((await createSummary.locator('strong').innerText()).trim(), '1');
    assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
    page.once('dialog', dialog => dialog.accept());
    await Promise.all([
      page.waitForURL(url => /\/veri-ice-aktarma\/\d+$/.test(url.pathname)),
      page.getByRole('button', { name: '1 Kaydı İçe Aktar' }).click(),
    ]);
    assert.ok((await page.locator('body').innerText()).includes('Aktarım tamamlandı'));
    page.once('dialog', dialog => dialog.accept());
    await Promise.all([
      page.waitForURL(url => /\/veri-ice-aktarma\/\d+$/.test(url.pathname)),
      page.getByRole('button', { name: 'Aktarımı Geri Al' }).click(),
    ]);
    assert.ok((await page.locator('body').innerText()).includes('Bu aktarım geri alındı'));
    if (width < 1000) {
      const buttonHeights = await page.locator('#dashboardMainContent button:not(.btn-close), #dashboardMainContent a.btn').evaluateAll(items => items.filter(item => item.offsetParent !== null).map(item => item.getBoundingClientRect().height));
      assert.ok(buttonHeights.every(height => height >= 38));
    }
    await page.screenshot({ path: `${output}/${width}.png`, fullPage: true });
    results.push({ width, status: 'passed' });
    await context.close();
  }
} finally {
  await browser.close();
  await fs.writeFile(`${output}/results.json`, JSON.stringify({ results, errors }, null, 2));
}
assert.deepEqual(errors, []);
console.log(JSON.stringify({ results, errors }));
