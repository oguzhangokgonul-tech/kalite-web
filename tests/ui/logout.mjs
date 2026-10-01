import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5094';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
const failures = [];
await fs.mkdir('.tmp-ui-audit/logout', { recursive: true });

try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width < 1200 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
      if (width < 1200) {
        await page.getByRole('button', { name: 'Menüyü aç' }).click();
        await page.locator('#dashboardSidebar').waitFor({ state: 'visible' });
      }
      const form = page.locator('form[data-logout-form]').first();
      const logoutButton = form.getByRole('button', { name: 'Çıkış', exact: true });
      await page.route('**/session/csrf-token', route => route.abort());
      const dialogShown = new Promise(resolve => page.once('dialog', async dialog => {
        const message = dialog.message();
        await dialog.accept();
        resolve(message);
      }));
      await logoutButton.click();
      assert.match(await dialogShown, /Çıkış tamamlanamadı/);
      assert.equal(await logoutButton.isEnabled(), true);
      assert.notEqual(new URL(page.url()).pathname, '/login');
      await page.unroute('**/session/csrf-token');
      await form.locator('input[name="csrf_token"]').evaluate(input => { input.value = 'expired-token'; });
      const tokenRequest = page.waitForResponse(response => response.url().endsWith('/session/csrf-token'));
      await form.getByRole('button', { name: 'Çıkış', exact: true }).click();
      assert.equal((await tokenRequest).status(), 200);
      await page.waitForURL('**/login', { waitUntil: 'domcontentloaded' });
      assert.equal(new URL(page.url()).pathname, '/login');
      const protectedResponse = await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
      assert.equal(new URL(page.url()).pathname, '/login');
      assert.equal(protectedResponse.status(), 200);
      assert.deepEqual(errors, []);
      await page.screenshot({ path: `.tmp-ui-audit/logout/${width}.png`, fullPage: true });
      completed.push({ width, status: 'passed' });
    } catch (error) {
      failures.push({ width, error: error.message, url: page.url() });
    }
    await context.close();
  }
} finally {
  await browser.close();
  await fs.writeFile('.tmp-ui-audit/logout/results.json', JSON.stringify({ completed, failures }, null, 2));
}

console.log(JSON.stringify({ completed, failures }, null, 2));
if (failures.length) process.exitCode = 1;
