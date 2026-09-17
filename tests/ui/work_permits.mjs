import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5079';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];

const localValue = (date) => {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
};

try {
  for (const width of [390, 768]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const noOverflow = async () => assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
    await page.goto(base + '/is-izinleri/yeni', { waitUntil: 'domcontentloaded' });
    await noOverflow();
    if (width === 390) {
      const now = new Date();
      await page.locator('[name="permit_type"]').selectOption({ label: 'Sıcak Çalışma' });
      await page.locator('[name="title"]').fill('Mobil kaynak işi');
      await page.locator('[name="location"]').fill('Üretim Holü A');
      await page.locator('[name="requested_start_at"]').fill(localValue(new Date(now.getTime() - 60000)));
      await page.locator('[name="requested_end_at"]').fill(localValue(new Date(now.getTime() + 3600000)));
      const userOptions = await page.locator('[name="responsible_user_id"] option').evaluateAll(options => options.filter(item => item.value).map(item => item.value));
      assert.ok(userOptions.length >= 2);
      await page.locator('[name="responsible_user_id"]').selectOption(userOptions[0]);
      await page.locator('[name="approver_user_id"]').selectOption(userOptions[1]);
      await page.locator('[name="description"]').fill('Kaynakla bağlantı onarımı yapılacak.');
      await page.locator('[name="hazards"]').fill('Yangın ve sıcak yüzey.');
      await page.locator('[name="precautions"]').fill('Alan çevrilecek ve gözcü bulunacak.');
      await page.locator('[name="ppe_requirements"]').fill('Maske, eldiven ve koruyucu kıyafet.');
      await page.getByRole('button', { name: 'Taslağı Oluştur' }).click();
      await page.waitForURL('**/is-izinleri/*');
      assert.match(await page.locator('body').innerText(), /IZIN-\d{4}-0001/);
      await noOverflow();
    }
    await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-work-permits.png`, fullPage: true });
    completed.push(width);
    await context.close();
  }
} finally {
  await browser.close();
}

console.log(JSON.stringify({ completed, failures: [] }, null, 2));
