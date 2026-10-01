import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5092';
const roles = (process.env.I18N_TEST_ROLES || 'super_admin,management_representative,management,department_manager,department_staff,viewer').split(',');
const widths = (process.env.I18N_TEST_WIDTHS || '390,768,1024,1440').split(',').map(Number);
const browser = await chromium.launch({ headless: true, channel: process.env.UI_BROWSER_CHANNEL || 'chrome' });
const completed = [];
const failures = [];

await fs.mkdir('.tmp-ui-audit/i18n', { recursive: true });
try {
  for (const width of widths) {
    for (const role of roles) {
      const context = await browser.newContext({
        viewport: { width, height: 900 },
        hasTouch: width < 1400,
        isMobile: width < 768,
      });
      await context.request.get(`${base}/__ui/login/${role}`);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (error) => errors.push(String(error)));
      try {
        await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
        if (width < 1200) {
          await page.locator('.dashboard-mobile-menu-button').click();
          await page.locator('#dashboardSidebar').waitFor({ state: 'visible' });
        } else {
          await page.mouse.move(32, 120);
          await page.waitForTimeout(220);
        }
        assert.equal(await page.locator('.locale-switcher-sidebar, .locale-switcher-login').count(), 0, 'visible language controls removed');
        const csrf = await page.locator('input[name="csrf_token"]').first().inputValue();
        const languageResponse = await page.evaluate(async ({ csrf }) => {
          const response = await fetch('/dil', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ csrf_token: csrf, locale: 'en', next: '/' }),
          });
          return response.status;
        }, { csrf });
        assert.equal(languageResponse, 200, 'hidden language infrastructure endpoint');
        await page.reload({ waitUntil: 'domcontentloaded' });
        assert.equal(await page.locator('html').getAttribute('lang'), 'en', 'html lang');
        const sidebarText = await page.locator('#dashboardSidebar').textContent();
        assert.equal(sidebarText.includes('Home'), true, 'translated Home label');
        assert.equal(sidebarText.includes('Sign Out'), true, 'translated Sign Out label');
        assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0, 'horizontal overflow');
        assert.deepEqual(errors, []);

        const manifest = await page.evaluate(async () => (await fetch('/manifest.webmanifest')).json());
        assert.equal(manifest.lang, 'en');
        assert.equal(manifest.shortcuts[1].name, 'My Tasks');

        await page.reload({ waitUntil: 'domcontentloaded' });
        assert.equal(await page.locator('html').getAttribute('lang'), 'en');
        completed.push({ width, role });
        if (width === 390 && ['super_admin', 'viewer'].includes(role)) {
          await page.screenshot({ path: `.tmp-ui-audit/i18n/${width}-${role}.png`, fullPage: true });
        }
      } catch (error) {
        failures.push({
          width,
          role,
          error: error.message,
          url: page.url(),
          lang: await page.locator('html').getAttribute('lang').catch(() => null),
          sidebar: (await page.locator('#dashboardSidebar').textContent().catch(() => '')).slice(0, 500),
        });
      }
      await context.close();
    }
  }
} finally {
  await browser.close();
  await fs.writeFile(
    '.tmp-ui-audit/i18n/results.json',
    JSON.stringify({ completed, failures }, null, 2),
  );
}

console.log(JSON.stringify({ completed: completed.length, failures }, null, 2));
if (failures.length) process.exitCode = 1;
