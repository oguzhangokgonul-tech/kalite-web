import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5081';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
const isoDate = (offset) => { const value = new Date(); value.setDate(value.getDate() + offset); return value.toISOString().slice(0, 10); };

try {
  for (const width of [390, 768]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    const noOverflow = async () => assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
    await page.goto(base + '/cevre-yonetimi/boyut/yeni', { waitUntil: 'domcontentloaded' });
    assert.equal(page.url().includes('/cevre-yonetimi/boyut/yeni'), true);
    await noOverflow();
    if (width === 390) {
      await page.locator('[name="department_id"]').selectOption({ index: 1 });
      await page.locator('[name="process"]').fill('Mobil Üretim');
      await page.locator('[name="activity"]').fill('Parça temizleme');
      await page.locator('[name="aspect"]').fill('Atık yağ oluşumu');
      await page.locator('[name="impact"]').fill('Toprak ve su kirliliği');
      await page.locator('[name="existing_controls"]').fill('Sızdırmaz kap ve ikincil hazne.');
      await page.locator('[name="review_due_date"]').fill(isoDate(90));
      const users = await page.locator('[name="responsible_user_id"] option').evaluateAll(options => options.filter(item => item.value).map(item => item.value));
      assert.ok(users.length >= 2);
      await page.locator('[name="responsible_user_id"]').selectOption(users[0]);
      await page.locator('[name="reviewer_user_id"]').selectOption(users[1]);
      await page.locator('[name="assessment_rationale"]').fill('Mobil saha değerlendirmesi.');
      await page.getByRole('button', { name: 'Kaydet' }).click();
      await page.waitForURL('**/cevre-yonetimi/boyut/*');
      assert.match(await page.locator('body').innerText(), /CEV-\d{4}-0001/);
      await noOverflow();
    } else {
      await page.goto(base + '/cevre-yonetimi', { waitUntil: 'domcontentloaded' });
      await noOverflow();
    }
    assert.deepEqual(errors, []);
    await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-environmental-management.png`, fullPage: true });
    completed.push(width);
    await context.close();
  }
} finally {
  await browser.close();
}

console.log(JSON.stringify({ completed, failures: [] }, null, 2));
