import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5078';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
try {
  for (const width of [390, 768]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const noOverflow = async () => assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
    await page.goto(base + '/ic-talepler/yeni', { waitUntil: 'domcontentloaded' });
    await noOverflow();
    if (width === 390) {
      await page.locator('[name="title"]').fill('Mobil destek talebi');
      await page.locator('[name="category"]').selectOption('Bilgi Teknolojileri');
      await page.locator('[name="priority"]').selectOption('Yüksek');
      await page.locator('[name="department"]').fill('Bilgi Teknolojileri');
      await page.locator('[name="description"]').fill('Saha tabletinde bağlantı sorunu yaşanıyor.');
      await page.getByRole('button', { name: 'Talebi Oluştur' }).click();
      await page.waitForURL('**/ic-talepler/*');
      assert.match(await page.locator('body').innerText(), /TLP-2026-0001/);
      await noOverflow();
    }
    await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-help-desk.png`, fullPage: true });
    completed.push(width);
    await context.close();
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({ completed, failures: [] }, null, 2));
