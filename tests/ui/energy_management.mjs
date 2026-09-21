import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5081';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];

try {
  for (const width of [390, 768]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    const noOverflow = async () => assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
    await page.goto(base + '/enerji-yonetimi', { waitUntil: 'domcontentloaded' });
    assert.match(await page.locator('body').innerText(), /Enerji Y.netimi/);
    await noOverflow();
    await page.goto(base + '/enerji-yonetimi/sayac/yeni', { waitUntil: 'domcontentloaded' });
    await noOverflow();
    if (width === 390) {
      await page.locator('[name="meter_code"]').fill('UI-ELK-01');
      await page.locator('[name="name"]').fill('Mobil Ana Sayaç');
      await page.locator('[name="location"]').fill('Ana Pano');
      await page.locator('[name="energy_type"]').selectOption('Elektrik');
      await page.locator('[name="unit"]').selectOption('kWh');
      await page.locator('[name="department_id"]').selectOption({ index: 1 });
      const owners = await page.locator('[name="responsible_user_id"] option').evaluateAll(options => options.filter(item => item.value).map(item => item.value));
      const reviewers = await page.locator('[name="reviewer_user_id"] option').evaluateAll(options => options.filter(item => item.value).map(item => item.value));
      assert.ok(owners.length && reviewers.length);
      const owner = owners[0];
      const reviewer = reviewers.find(value => value !== owner) || reviewers[0];
      await page.locator('[name="responsible_user_id"]').selectOption(owner);
      await page.locator('[name="reviewer_user_id"]').selectOption(reviewer);
      await page.getByRole('button', { name: 'Kaydet' }).click();
      await page.waitForURL('**/enerji-yonetimi/sayac/*');
      assert.match(await page.locator('body').innerText(), /UI-ELK-01/);
      await noOverflow();
    }
    assert.deepEqual(errors, []);
    await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-energy-management.png`, fullPage: true });
    completed.push(width);
    await context.close();
  }
} finally {
  await browser.close();
}

console.log(JSON.stringify({ completed, failures: [] }, null, 2));
