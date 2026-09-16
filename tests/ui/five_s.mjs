import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5075';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
try {
  for (const width of [390, 768]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const noOverflow = async () => assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
    await page.goto(base + '/5s-denetim/yeni', { waitUntil: 'domcontentloaded' });
    await noOverflow();
    if (width === 390) {
      await page.locator('[name="title"]').fill('Mobil 5S Denetimi');
      await page.locator('[name="area"]').fill('Kaynak Hattı');
      await page.locator('[name="department"]').fill('Üretim');
      await page.locator('[name="auditor_user_id"]').selectOption({ index: 1 });
      await page.locator('[name="reviewer_user_id"]').selectOption({ index: 2 });
      await page.getByRole('button', { name: 'Denetimi Oluştur' }).click();
      await page.waitForURL('**/5s-denetim/*');
      assert.match(await page.locator('body').innerText(), /5S-2026-0001/);
      await noOverflow();
      await page.getByRole('link', { name: 'Denetimi Uygula' }).click();
      await noOverflow();
      const scoreButtons = page.locator('label', { hasText: /^4$/ });
      for (let i = 0; i < await scoreButtons.count(); i++) await scoreButtons.nth(i).click();
      await page.getByRole('button', { name: 'Taslak Kaydet' }).click();
      await page.waitForURL('**/5s-denetim/*');
      await noOverflow();
    }
    await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-five-s.png`, fullPage: true });
    completed.push(width); await context.close();
  }
} finally { await browser.close(); }
console.log(JSON.stringify({ completed, failures: [] }, null, 2));
