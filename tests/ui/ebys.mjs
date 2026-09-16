import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5071';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
try {
  for (const width of [390, 768]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      hasTouch: true,
      isMobile: width < 768,
    });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const assertNoOverflow = async () => assert.equal(
      await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)),
      0
    );
    await page.goto(base + '/resmi-yazismalar/yeni', { waitUntil: 'domcontentloaded' });
    await assertNoOverflow();
    if (width === 390) {
      await page.locator('[name="subject"]').fill('Mobil resmî yazışma testi');
      await page.locator('[name="sender"]').fill('Denetim Kurumu');
      await page.locator('[name="recipient"]').fill('VolkaPortal Test Şirketi');
      await page.locator('[name="department"]').fill('Kalite');
      await page.locator('[name="due_date"]').fill('2026-09-25');
      await page.getByRole('button', { name: 'Kaydet' }).click();
      await page.waitForURL('**/resmi-yazismalar/*');
      assert.match(await page.locator('body').innerText(), /EBYS-2026-0001/);
      await assertNoOverflow();
    }
    await page.screenshot({
      path: `.tmp-ui-audit/responsive/${width}-ebys.png`,
      fullPage: true,
    });
    completed.push(width);
    await context.close();
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({ completed, failures: [] }, null, 2));
