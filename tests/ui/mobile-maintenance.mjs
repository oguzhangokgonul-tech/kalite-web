import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5097';
const output = '.tmp-ui-audit/mobile-maintenance';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const results = [];
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: true });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const check = async (name) => {
      assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0, name);
      await page.screenshot({ path: `${output}/${width}-${name}.png`, fullPage: true });
    };
    try {
      await context.request.get(`${base}/__ui/login/department_staff`);
      await page.goto(`${base}/mobil`, { waitUntil: 'networkidle' });
      await check('hub');
      assert.equal(await page.locator('.pwa-action-card[href="/bakim"]').count(), 0);
      const shortcut = page.locator('.pwa-action-card[href="/bakim/ariza/yeni"]');
      assert.ok((await shortcut.boundingBox()).height >= 44);
      await shortcut.click();
      await page.locator('#machine_id').selectOption('__unplanned__');
      await page.locator('#title').fill(`Mobil bakım testi ${width}`);
      await page.locator('#reporting_department').selectOption('Kalite');
      await page.locator('#description').fill('Test ortamında bakım talebi');
      await check('form');
      await page.locator('.maintenance-form-card button[type="submit"]').click();
      await page.waitForURL(/\/bakim\/ariza\/\d+$/);
      const detail = page.url();
      await check('detail');
      assert.equal(await page.locator('form[action$="/kapat"]').count(), 0);
      await context.request.get(`${base}/__ui/login/management_representative`);
      await page.goto(detail, { waitUntil: 'networkidle' });
      const closeForm = page.locator('form[action$="/kapat"]');
      await closeForm.locator('[name="closing_note"]').fill('Bakım tamamlandı, kontrol edildi.');
      await closeForm.locator('button[type="submit"]').click();
      await page.waitForLoadState('networkidle');
      assert.equal(await page.locator('form[action$="/kapat"]').count(), 0);
      await page.goto(`${base}/bakim`);
      await page.waitForLoadState('networkidle');
      await check('dashboard');
      assert.ok((await page.locator('body').innerText()).includes(`Mobil bakım testi ${width}`));
      assert.deepEqual(errors, []);
      results.push({ width, result: 'passed' });
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
  await fs.writeFile(`${output}/results.json`, JSON.stringify(results, null, 2));
}
console.log(JSON.stringify(results));
