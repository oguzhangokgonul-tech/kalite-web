import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5067';
const output = process.env.UI_OUTPUT || '.tmp-ui-audit/responsive';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: process.env.UI_BROWSER_CHANNEL || 'chrome' });
const results = [];
const failures = [];
try {
  const manifest = await (await fetch(`${base}/__ui/manifest`)).json();
  const sizes = [[360, 800], [390, 844], [768, 1024], [820, 1180], [1024, 768], [1180, 820], [1366, 1024], [1440, 900]];
  const critical = ['/', '/documents/list', '/kalibrasyon', '/insan-kaynaklari/personel-listesi',
    '/kalite-deneyleri/beton-deneyi', '/organization', '/uzerime-atananlar',
    '/dinamik-formlar/sablon/yeni', '/actions/new', '/dofs/new', '/fmea/yeni'];
  for (const [width, height] of sizes) {
    const context = await browser.newContext({ viewport: { width, height }, hasTouch: width < 1400,
                                               isMobile: width < 768 });
    await context.request.get(`${base}/__ui/login/super_admin`);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    // Full module inventory on phone, portrait tablet, landscape tablet and desktop.
    const paths = [390, 768, 1024, 1440].includes(width) ? manifest.paths : manifest.paths.filter(p => critical.includes(p));
    for (const url of paths) {
      try {
        const response = await page.goto(base + url, { waitUntil: 'domcontentloaded', timeout: 60000 });
        assert.equal(response.status(), 200, url);
        await page.waitForFunction(() => document.querySelector('#dashboardMainContent')?.dataset.responsiveReady === 'true',
          null, { timeout: 10000 });
        await page.waitForTimeout(140);
        const metrics = await page.evaluate(() => {
          const visible = element => element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden';
          const main = document.getElementById('dashboardMainContent');
          const controls = [...(main?.querySelectorAll('input:not([type="hidden"]), select, textarea') || [])]
            .filter(visible).filter(el => !el.closest('.table-responsive:not(.vp-records-active)'));
          const outside = controls.filter(el => {
            const box = el.getBoundingClientRect();
            return box.left < -1 || box.right > innerWidth + 1;
          }).map(el => el.name || el.id);
          return { overflow: Math.max(0, document.documentElement.scrollWidth - innerWidth), outside,
                   records: document.querySelectorAll('.vp-record-row').length,
                   activeLists: document.querySelectorAll('.vp-records-active').length };
        });
        assert.equal(metrics.overflow, 0, `${url} page overflow ${metrics.overflow}`);
        assert.deepEqual(metrics.outside, [], `${url} clipped form controls`);
        results.push({ width, height, url, ...metrics });
        if (critical.includes(url)) await page.screenshot({ path: path.join(output, `${width}-${url.replace(/\W/g, '_') || 'home'}.png`), fullPage: true });
      } catch (error) { failures.push({ width, url, error: error.message }); }
    }
    try {
      await page.goto(base + '/insan-kaynaklari/personel-listesi', { waitUntil: 'domcontentloaded' });
      const records = page.locator('.vp-responsive-table').first();
      await records.waitFor();
      if (width < 1400) {
        const group = page.locator('.vp-list-view-controls').first();
        await group.getByRole('button', { name: 'Liste görünümü', exact: true }).click();
        assert.ok(await records.locator('.vp-record-row').count() >= 3);
        await group.getByRole('button', { name: 'Tablo görünümü', exact: true }).click();
        assert.equal(await page.locator('.vp-records-active').count(), 0);
        assert.equal(await records.locator('thead').evaluate(el => getComputedStyle(el).display), 'table-header-group');
        assert.equal(await records.locator('tbody tr').first().evaluate(el => getComputedStyle(el).display), 'table-row');
        await group.getByRole('button', { name: 'Liste görünümü', exact: true }).click();
        await page.getByRole('button', { name: 'Menüyü aç' }).click();
        const sidebar = page.locator('#dashboardSidebar');
        await sidebar.waitFor({ state: 'visible' });
        for (const button of await sidebar.locator('.dashboard-nav-toggle').all()) {
          await button.scrollIntoViewIfNeeded();
          if (await button.getAttribute('aria-expanded') === 'false') await button.click();
        }
        const logout = sidebar.getByRole('button', { name: 'Çıkış', exact: true });
        await logout.scrollIntoViewIfNeeded();
        assert.ok(await logout.isVisible());
        await page.screenshot({ path: path.join(output, `${width}-sidebar.png`) });
        await sidebar.getByRole('button', { name: 'Kapat', exact: true }).click();
        await page.locator('.offcanvas-backdrop').waitFor({ state: 'detached' });
        await page.goto(base + '/kalite-deneyleri/beton-deneyi', { waitUntil: 'domcontentloaded' });
        const toggle = page.locator('.table-disclosure-toggle').first();
        await toggle.click();
        await page.locator('.concrete-row-detail-panel.show').waitFor();
        await page.waitForTimeout(250);
        const detailFits = await page.locator('.concrete-row-detail-panel').evaluate(el =>
          el.getBoundingClientRect().bottom <= el.closest('td').getBoundingClientRect().bottom + 1);
        assert.ok(detailFits, 'Expanded concrete panel must remain inside its row');
        assert.ok(await page.getByRole('link', { name: 'Ölçüm Gir', exact: true }).isVisible());
        await page.screenshot({ path: path.join(output, `${width}-concrete-expanded.png`), fullPage: true });
        await page.getByRole('link', { name: 'Düzenle', exact: true }).click();
        await page.locator('[name="strength_2_day"]').fill('18.5');
        await page.locator('[name="strength_7_day"]').fill('');
        // Verify original field identity survives view-mode changes; no live data is touched.
        assert.equal(await page.locator('[name="strength_2_day"]').inputValue(), '18.5');
        await page.goto(base + '/dinamik-formlar/sablon/yeni', { waitUntil: 'domcontentloaded' });
        const checkbox = page.locator('.required-box').first();
        const wasChecked = await checkbox.isChecked();
        await page.locator('.form-check-label').first().click();
        assert.equal(await checkbox.isChecked(), !wasChecked);
        await page.getByRole('button', { name: 'Alan Ekle', exact: true }).click();
        assert.equal(await page.locator('.required-box').count(), 2);
        const ids = await page.locator('.required-box').evaluateAll(els => els.map(el => el.id));
        assert.equal(new Set(ids).size, ids.length);
      }
    } catch (error) { failures.push({ width, scenario: 'interactions', error: error.message }); }
    if (errors.length) failures.push({ width, errors });
    console.log(JSON.stringify({ width, checked: paths.length, failures: failures.filter(f => f.width === width) }));
    await context.close();
  }
  // Real role-rendered navigation, not merely a resized superadmin page.
  for (const role of manifest.roles) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    await context.request.get(`${base}/__ui/login/${role}`);
    const page = await context.newPage();
    await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
    const links = await page.locator('#dashboardSidebar a[href]').evaluateAll(els => els.map(el => el.getAttribute('href')));
    for (const url of [...new Set(links)]) {
      const response = await page.goto(base + url, { waitUntil: 'domcontentloaded', timeout: 60000 });
      if (response.status() !== 200) failures.push({ role, url, status: response.status() });
    }
    await context.close();
  }
} finally {
  await browser.close();
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify({ results, failures }, null, 2));
}
console.log(JSON.stringify({ navigations: results.length, failures }, null, 2));
if (failures.length) process.exitCode = 1;
