import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5081';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];

try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      hasTouch: true,
      isMobile: width < 768,
    });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    const noOverflow = async () => assert.equal(
      await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)),
      0,
    );

    const dashboardResponse = await page.goto(base + '/risk-yonetimi/isg', { waitUntil: 'domcontentloaded' });
    assert.equal(dashboardResponse.status(), 200);
    assert.ok(await page.locator('h2').count());
    await noOverflow();
    await page.goto(base + '/risk-yonetimi/isg/yeni', { waitUntil: 'domcontentloaded' });
    await noOverflow();

    if (width === 390) {
      await page.locator('[name="department_id"]').selectOption({ index: 1 });
      await page.locator('[name="activity"]').fill('Pres hattında güvenli çalışma');
      await page.locator('[name="location"]').fill('Üretim holü');
      await page.locator('[name="exposed_people"]').fill('Operatörler');
      await page.locator('[name="hazard"]').fill('Hareketli parçaya temas');
      await page.locator('[name="risk_description"]').fill('El yaralanması');
      await page.locator('[name="existing_controls"]').fill('Günlük kontrol');
      await page.locator('[name="initial_likelihood"]').selectOption('2');
      await page.locator('[name="initial_severity"]').selectOption('3');
      await page.locator('[name="control_hierarchy"]').selectOption({ index: 1 });
      await page.locator('[name="planned_controls"]').fill('Sabit muhafaza kurulması');

      const owners = await page.locator('[name="responsible_user_id"] option').evaluateAll(
        options => options.filter(item => item.value).map(item => item.value),
      );
      const reviewers = await page.locator('[name="reviewer_user_id"] option').evaluateAll(
        options => options.filter(item => item.value).map(item => item.value),
      );
      assert.ok(owners.length && reviewers.length);
      const reviewer = reviewers[0];
      const owner = owners.find(value => value !== reviewer);
      assert.ok(owner);
      await page.locator('[name="responsible_user_id"]').selectOption(owner);
      await page.locator('[name="reviewer_user_id"]').selectOption(reviewer);
      await page.locator('[name="due_date"]').fill('2026-10-01');
      await page.locator('[name="review_date"]').fill('2026-10-15');
      await page.locator('.ohs-form-actions button[type="submit"]').click();
      await page.waitForURL('**/risk-yonetimi/isg/*');
      assert.match(await page.locator('body').innerText(), /ISG-2026-/);
      assert.equal(await page.locator('.ohs-matrix').count(), 1);
      await noOverflow();
    }

    assert.deepEqual(errors, []);
    await page.screenshot({
      path: `.tmp-ui-audit/responsive/${width}-ohs-risk-management.png`,
      fullPage: true,
    });
    completed.push(width);
    await context.close();
  }
} finally {
  await browser.close();
}

console.log(JSON.stringify({ completed, failures: [] }, null, 2));
