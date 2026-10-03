import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5097';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const results = [];
await fs.mkdir('.tmp-ui-audit/notification-policy', { recursive: true });
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width < 1200 });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const role of ['management_representative', 'department_staff']) {
      await context.request.get(`${base}/__ui/login/${role}`);
      const response = await page.goto(base + '/notifications/settings');
      assert.equal(response.status(), 200);
      await page.waitForLoadState('networkidle');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      assert.equal(await page.locator('#company-policy-title').count(), Number(role === 'management_representative'));
      await page.locator('#mode-weekly').check();
      await page.locator('form[action$="/preferences"] button[type=submit]').click();
      await page.waitForLoadState('networkidle');
      assert.equal(await page.locator('#mode-weekly').isChecked(), true);
      if (role === 'management_representative') {
        await page.locator('#weekly-day').selectOption('0');
        await page.locator('input[name="modules.action.days"]').fill('7, 0');
        await page.locator('form[action$="/company"] button[type=submit]').click();
        await page.waitForLoadState('networkidle');
        assert.equal(await page.locator('input[name="modules.action.days"]').inputValue(), '7, 0');
      }
      await page.screenshot({ path: `.tmp-ui-audit/notification-policy/${width}-${role}.png`, fullPage: false });
      assert.equal(await page.locator('.alert-danger').count(), 0);
      results.push({ width, role, result: 'pass' });
    }
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log(JSON.stringify(results, null, 2));
} finally {
  await browser.close();
}
