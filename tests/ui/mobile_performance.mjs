import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5100';
const output = '.tmp-ui-audit/mobile-performance';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--disable-gpu'] });
const results = [];
try {
  for (const width of [360, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 820 }, hasTouch: width < 1000, isMobile: width < 768 });
    await context.request.get(base + '/__preview/login/management_representative');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const cdp = await context.newCDPSession(page);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: width < 1000 ? 4 : 1 });
    const ready = async () => {
      await page.waitForLoadState('load');
      await page.waitForFunction(() => document.documentElement.dataset.navigationReady === 'true');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.equal(await page.evaluate(() => document.fonts.check('16px bootstrap-icons')), true);
    };
    const resources = () => page.evaluate(() => performance.getEntriesByType('resource')
      .filter(entry => new URL(entry.name).pathname.startsWith('/static/'))
      .map(entry => ({ path: new URL(entry.name).pathname, bytes: entry.transferSize })));
    await page.goto(base + '/mobil');
    await ready();
    const cold = await resources();
    const expected = '/static/vendor/bootstrap-5.3.3/bootstrap.min.css';
    assert.ok(cold.some(entry => entry.path === expected));
    if (width < 1000) {
      assert.equal(await page.locator('#dashboardSidebar a, #dashboardSidebar button').evaluateAll(elements =>
        elements.filter(el => bootstrap.Tooltip.getInstance(el)).length), 0);
      await page.locator('.dashboard-mobile-menu-button').click();
      await page.waitForFunction(() => document.getElementById('dashboardSidebar').classList.contains('show'));
      await page.locator('#vpNavSearch').fill('zimmet');
      await page.locator('#dashboardSidebar a[href="/zimmet-yonetimi"]').click();
      await ready();
    } else {
      await page.locator('[data-nav-mode-toggle]').click();
      await page.waitForFunction(() => document.documentElement.dataset.navMode === 'compact');
      await page.locator('#dashboardSidebar .dashboard-nav-item').first().hover();
      await page.getByRole('tooltip').waitFor();
      await page.locator('[data-nav-mode-toggle]').click();
      await page.goto(base + '/zimmet-yonetimi');
      await ready();
    }
    const warm = await resources();
    assert.equal(warm.find(entry => entry.path === expected)?.bytes, 0, 'Core stylesheet should be reused without transfer');
    assert.equal(await page.evaluate(() => performance.getEntriesByType('resource').some(entry => entry.name.includes('cdn.jsdelivr.net/npm/bootstrap'))), false);
    await page.getByRole('link', { name: 'Yeni Zimmet', exact: true }).click();
    await ready();
    await page.locator('#custody-personnel').selectOption({ index: 1 });
    await page.locator('#custody-item').fill('Performance test ' + width);
    await Promise.all([page.waitForNavigation(), page.getByRole('button', { name: 'Zimmeti Kaydet', exact: true }).click()]);
    await ready();
    assert.match(page.url(), /\/zimmet-yonetimi\/\d+$/);
    await page.screenshot({ path: `${output}/${width}-detail.png`, fullPage: true });
    if (width < 1000) {
      await page.locator('.dashboard-mobile-menu-button').click();
      await page.locator('#vpNavSearch').fill('');
      const group = page.locator('#dashboardSidebar .dashboard-nav-toggle').first();
      const target = await group.getAttribute('data-bs-target');
      await group.click();
      await page.waitForFunction(selector => !document.querySelector(selector).classList.contains('collapsing'), target);
      const nav = page.locator('.dashboard-sidebar-nav');
      assert.ok(await nav.evaluate(el => { el.scrollTop = el.scrollHeight; return el.scrollTop > 0; }));
      assert.ok(await page.locator('.dashboard-logout').isVisible());
      await page.screenshot({ path: `${output}/${width}-menu.png`, fullPage: true });
    }
    await page.locator('.dashboard-logout').click();
    await page.waitForURL('**/login**');
    assert.equal((await context.request.get(base + '/mobil', { maxRedirects: 0 })).status(), 302);
    assert.deepEqual(errors, []);
    results.push({ width, coldStaticBytes: cold.reduce((sum, r) => sum + r.bytes, 0), warmStaticBytes: warm.reduce((sum, r) => sum + r.bytes, 0), menu: 'passed', create: 'passed', logout: 'passed' });
    await context.close();
  }
} finally {
  await browser.close();
}
await writeFile(`${output}/results.json`, JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
