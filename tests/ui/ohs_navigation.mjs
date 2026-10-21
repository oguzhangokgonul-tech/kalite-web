import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5134';
const browser = await chromium.launch({ channel: 'chrome', args: ['--disable-gpu'] });
await fs.mkdir('.tmp-ui-audit/ohs-navigation', { recursive: true });
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${base}/login`);
    await page.locator('#company_code').selectOption('001');
    await page.locator('#identity').fill('yonetici');
    await page.locator('#password').fill('Local-preview-001');
    await page.getByRole('button', { name: 'Giriş Yap', exact: true }).click();
    await page.waitForURL(base + '/');
    await page.goto(`${base}/isg-notlari`);
    await page.waitForFunction(() => document.documentElement.dataset.navigationReady === 'true');
    if (width < 1200) await page.locator('[data-bs-toggle="offcanvas"][data-bs-target="#dashboardSidebar"]').click();
    const toggle = page.locator('[data-bs-target="#occupationalHealthNav"]');
    const panel = page.locator('#occupationalHealthNav');
    assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
    assert.equal(await panel.locator('a.active').getAttribute('href'), '/isg-notlari');
    await toggle.click();
    await page.waitForFunction(() => !document.querySelector('#occupationalHealthNav').classList.contains('show') && !document.querySelector('#occupationalHealthNav').classList.contains('collapsing'));
    await toggle.focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('#occupationalHealthNav').classList.contains('show'));
    await page.locator('#vpNavSearch').fill('İSG Notları');
    assert(await panel.locator('a[href="/isg-notlari"]').isVisible());
    assert(!(await panel.locator('a[href="/isg-aksiyonlari"]').isVisible()));
    await page.locator('#vpNavSearch').fill('');
    assert(await panel.locator('a[href="/isg-aksiyonlari"]').isVisible());
    if (width >= 1200) {
      await page.locator('[data-nav-mode-toggle]').click();
      assert.equal(await page.locator('html').getAttribute('data-nav-mode'), 'compact');
      await toggle.click();
      assert.equal(await page.locator('html').getAttribute('data-nav-mode'), 'expanded');
      assert(await panel.isVisible());
    }
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: `.tmp-ui-audit/ohs-navigation/${width}.png`, animations: 'disabled', timeout: 90000 });
    await panel.locator('a[href="/isg-aksiyonlari"]').click();
    await page.waitForURL(`${base}/isg-aksiyonlari`);
    assert.equal(await page.locator('#occupationalHealthNav a.active').getAttribute('href'), '/isg-aksiyonlari');
    assert.deepEqual(errors, []);
    console.log(`${width}: collapse, keyboard, search, active link and compact/mobile navigation passed`);
    await context.close();
  }
} finally { await browser.close(); }
