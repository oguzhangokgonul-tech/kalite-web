import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5070';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
try {
  for (const width of [390, 768]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const noOverflow = async () => assert.equal(
      await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0
    );
    await page.goto(base + '/tedarikci-degerlendirme/1/kalite-denetimi/yeni', { waitUntil: 'domcontentloaded' });
    await noOverflow();
    if (width === 390) {
      await page.locator('[name="scope"]').fill('Mobil tedarikçi proses denetimi');
      await page.locator('[name="status"]').selectOption('Tamamlandı');
      await page.locator('[name="score"]').selectOption('8');
      await page.locator('[name="findings"]').fill('Etiket izlenebilirliği iyileştirilmeli.');
      await page.getByRole('button', { name: 'Denetimi Kaydet' }).click();
      await page.waitForURL('**/tedarikci-degerlendirme');
      await page.locator('button[aria-controls^="supplier_detail_"]').first().click();
      assert.match(await page.locator('body').innerText(), /Mobil tedarikçi proses denetimi/);
    }
    await page.goto(base + '/tedarikci-degerlendirme/1/anket/yeni', { waitUntil: 'domcontentloaded' });
    await noOverflow();
    if (width === 390) {
      await page.locator('[name="respondent_name"]').fill('Kalite Kullanıcısı');
      await page.locator('[name="quality_score"]').selectOption('9');
      await page.locator('[name="delivery_score"]').selectOption('8');
      await page.locator('[name="communication_score"]').selectOption('7');
      await page.getByRole('button', { name: 'Anketi Kaydet' }).click();
      await page.waitForURL('**/tedarikci-degerlendirme');
      await page.locator('button[aria-controls^="supplier_detail_"]').first().click();
      assert.match(await page.locator('body').innerText(), /Kalite Kullanıcısı/);
    }
    await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-supplier-quality.png`, fullPage: true });
    completed.push(width);
    await context.close();
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({ completed, failures: [] }, null, 2));
