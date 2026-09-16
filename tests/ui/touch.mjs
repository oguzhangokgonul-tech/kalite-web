import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5067';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
const failures = [];
try {
  for (const [width, height] of [[320, 740], [640, 400], [1366, 1024]]) {
    const context = await browser.newContext({ viewport: { width, height }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const check = async (name, task) => {
      try { await task(); completed.push({ width, name }); console.log('PASS', width, name); }
      catch (error) { failures.push({ width, name, error: error.message }); console.log('FAIL', width, name, error.message); }
    };
    await check('touch menu, expanded submenus, footer and rotation', async () => {
      await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
      const sidebar = page.locator('#dashboardSidebar');
      await page.getByRole('button', { name: 'Menüyü aç' }).tap();
      for (const button of await sidebar.locator('.dashboard-nav-toggle').all()) {
        await button.scrollIntoViewIfNeeded();
        if (await button.getAttribute('aria-expanded') === 'false') await button.tap();
      }
      const lastLink = sidebar.locator('.dashboard-subnav.collapse.show a').last();
      await lastLink.scrollIntoViewIfNeeded();
      assert.ok(await lastLink.evaluate(el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }));
      const logout = sidebar.getByRole('button', { name: 'Çıkış', exact: true });
      await logout.scrollIntoViewIfNeeded();
      assert.ok(await logout.evaluate(el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }));
      await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-touch-menu.png` });
      await sidebar.getByRole('button', { name: 'Kapat', exact: true }).tap();
      await page.locator('.offcanvas-backdrop').waitFor({ state: 'detached' });
      await page.setViewportSize({ width: height, height: width });
      await page.getByRole('button', { name: 'Menüyü aç' }).tap();
      await logout.scrollIntoViewIfNeeded();
      await logout.tap();
      await page.waitForURL('**/login', { waitUntil: 'domcontentloaded' });
      await page.setViewportSize({ width, height });
      assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
      await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-touch-login.png`, fullPage: true });
    });
    await context.request.get(base + '/__ui/login/super_admin');
    await check('organization touch pan, secondary finger and cancelled drag', async () => {
      await page.goto(base + '/organization', { waitUntil: 'domcontentloaded' });
      if (await page.locator('.org-node').count() === 0) {
        await page.locator('[data-add-root-person]').tap();
        await page.locator('.org-node').first().waitFor();
      }
      const node = page.locator('.org-node').first();
      await page.locator('[data-center-view]').tap();
      const map = page.locator('[data-org-map]');
      await map.scrollIntoViewIfNeeded();
      const session = await context.newCDPSession(page);
      const touch = (type, touchPoints) => session.send('Input.dispatchTouchEvent', { type, touchPoints });
      const canvas = page.locator('[data-org-canvas]');
      const transform = () => canvas.evaluate(el => el.style.transform);
      const before = await transform();
      const bounds = await map.boundingBox();
      const p1 = { x: bounds.x + 18, y: Math.min(height - 40, Math.max(80, bounds.y + 28)), id: 1 };
      const p2 = { x: p1.x + 85, y: p1.y + 45, id: 2 };
      await touch('touchStart', [p1]);
      await touch('touchMove', [{ ...p1, x: p1.x + 25, y: p1.y + 15 }]);
      const moved = await transform();
      assert.notEqual(moved, before);
      await touch('touchStart', [{ ...p1, x: p1.x + 25, y: p1.y + 15 }, p2]);
      await touch('touchMove', [{ ...p1, x: p1.x + 25, y: p1.y + 15 }, { ...p2, x: p2.x + 30 }]);
      assert.equal(await transform(), moved);
      await touch('touchCancel', []);
      assert.equal(await transform(), before);
      await page.locator('[data-center-view]').tap();
      await map.scrollIntoViewIfNeeded();
      const nodeBounds = await node.boundingBox();
      const origin = await node.evaluate(el => [el.style.left, el.style.top]);
      const drag = { x: nodeBounds.x + nodeBounds.width / 2, y: nodeBounds.y + nodeBounds.height / 2, id: 3 };
      const posts = [];
      page.on('request', request => { if (request.method() === 'POST' && /\/move$/.test(new URL(request.url()).pathname)) posts.push(request.url()); });
      await touch('touchStart', [drag]);
      await touch('touchMove', [{ ...drag, x: drag.x + 20, y: drag.y + 15 }]);
      assert.notDeepEqual(await node.evaluate(el => [el.style.left, el.style.top]), origin);
      await touch('touchCancel', []);
      assert.deepEqual(await node.evaluate(el => [el.style.left, el.style.top]), origin);
      assert.equal(posts.length, 0);
      await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-touch-organization.png`, fullPage: true });
      await session.detach();
    });
    await context.close();
  }
} finally {
  await browser.close();
  await fs.writeFile('.tmp-ui-audit/responsive/touch.json', JSON.stringify({ completed, failures }, null, 2));
}
console.log(JSON.stringify({ completed: completed.length, failures }, null, 2));
if (failures.length) process.exitCode = 1;
