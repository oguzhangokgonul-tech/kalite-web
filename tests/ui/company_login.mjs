import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5133';
const output = '.tmp-ui-audit/company-login';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', args: ['--disable-gpu'] });
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    page.setDefaultTimeout(90000);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base, { waitUntil: 'networkidle' });
    assert(await page.locator('[data-dynamic-landing]').isVisible());
    await page.locator('.vp-dynamic-actions a[href="/login"]').click();
    await page.waitForURL('**/login');
    assert.deepEqual(await page.locator('#company_code option').evaluateAll(
      options => options.map(o => o.value)), ['', '001', '002']);
    assert.equal(await page.locator('#company_code').inputValue(), '001');
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: `${output}/${width}.png`, animations: 'disabled', timeout: 90000 });
    await page.locator('#company_code').selectOption('002');
    await page.locator('#identity').fill('demo-user');
    await page.locator('#password').fill('Local-preview-001');
    await page.locator('button[type=submit]').click();
    await page.waitForSelector('.alert-danger');
    assert.equal(await page.locator('#company_code').inputValue(), '002');
    assert.equal(await page.locator('#password').inputValue(), '');
    await page.locator('#password').fill('Local-preview-002');
    await page.locator('#remember_me').check();
    await page.locator('button[type=submit]').click();
    await page.waitForURL(url => !url.pathname.startsWith('/login'));
    assert.equal(await page.locator('[data-dynamic-landing]').count(), 0);
    assert.deepEqual(errors, []);
    console.log(`${width}: landing, login selector, rejection, session redirect passed`);
    await context.close();
  }
} finally { await browser.close(); }
