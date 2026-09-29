import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5067';
const output = '.tmp-ui-audit/navigation';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const completed = [], failures = [], frameSamples = [];
const check = async (name, task) => {
  try { await task(); completed.push(name); console.log('PASS', name); }
  catch (error) { failures.push({ name, error: error.message }); console.log('FAIL', name, error.message); }
};
const ready = page => page.waitForFunction(() => document.documentElement.dataset.navigationReady === 'true');
const fit = async page => assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
const screenshot = (page, name) => page.screenshot({ path: path.join(output, name + '.png'), fullPage: true });

try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await ctx.request.get(base + '/__ui/login/super_admin');
  const page = await ctx.newPage();
  page.on('pageerror', error => failures.push({ name: 'javascript', error: error.message }));
  await page.goto(base + '/'); await ready(page);
  const sidebar = page.locator('#dashboardSidebar');
  const mode = page.locator('[data-nav-mode-toggle]');
  await check('desktop expanded, compact, hover stability, preference and tooltips', async () => {
    assert.equal((await sidebar.boundingBox()).width, 280);
    assert.equal(await page.getByRole('button', { name: 'Filtreler', exact: true }).isVisible(), false);
    const filterButton = page.getByRole('button', { name: 'Filtrele', exact: true });
    await filterButton.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab');
    assert.equal(await filterButton.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
    await screenshot(page, 'desktop-expanded');
    await mode.click(); await page.waitForTimeout(220);
    assert.equal((await sidebar.boundingBox()).width, 72);
    const before = await page.locator('.dashboard-main').boundingBox();
    const home = sidebar.locator('.dashboard-nav-item').first();
    await home.hover();
    await page.getByRole('tooltip').waitFor();
    assert.equal(await page.getByRole('tooltip').innerText(), 'Ana Sayfa');
    assert.equal((await sidebar.boundingBox()).width, 72);
    assert.equal((await page.locator('.dashboard-main').boundingBox()).x, before.x);
    assert.equal(await home.locator('span').evaluate(el => getComputedStyle(el).clipPath), 'inset(50%)');
    assert.equal(await sidebar.locator('.locale-switcher').isVisible(), false);
    await page.mouse.move(500, 700); await screenshot(page, 'desktop-compact');
    await page.reload(); await ready(page);
    assert.equal((await sidebar.boundingBox()).width, 72);
    assert.equal(await page.evaluate(() => localStorage.getItem('vp-nav-mode')), 'compact');
    await sidebar.locator('[data-bs-target="#companyManagementStatusNav"]').click();
    await page.waitForTimeout(220);
    assert.equal((await sidebar.boundingBox()).width, 280);
    assert.equal(await sidebar.getByRole('link', { name: 'Rapor Merkezi', exact: true }).isVisible(), true);
  });
  await check('Turkish menu search, closed submenu, no results, state restoration', async () => {
    const search = page.locator('#vpNavSearch');
    await search.fill('beton');
    const link = sidebar.getByRole('link', { name: 'Beton Deneyi', exact: true });
    assert.ok(await link.isVisible());
    assert.equal(await sidebar.getByRole('link', { name: 'Ana Sayfa', exact: true }).isVisible(), false);
    await screenshot(page, 'desktop-search');
    await search.fill('İNSAN');
    assert.ok(await sidebar.getByRole('link', { name: 'Personel Listesi', exact: true }).isVisible());
    await search.fill('zzz-no-module');
    assert.ok(await sidebar.locator('.vp-nav-empty').isVisible());
    await search.press('Escape');
    assert.equal(await search.inputValue(), '');
    assert.ok(await sidebar.getByRole('link', { name: 'Ana Sayfa', exact: true }).isVisible());
    await search.fill('rapor');
    await sidebar.getByRole('link', { name: 'Rapor Merkezi', exact: true }).click();
    await page.waitForURL('**/rapor-merkezi'); await ready(page);
    assert.ok(await page.locator('.report-card-grid article').first().isVisible());
    await screenshot(page, 'desktop-reports');
  });
  await check('compact active group expands without closing its current submenu', async () => {
    const group = sidebar.locator('[data-bs-target="#companyManagementStatusNav"]');
    assert.equal(await group.getAttribute('aria-expanded'), 'true');
    await mode.click(); await page.waitForTimeout(220);
    await group.click(); await page.waitForTimeout(220);
    assert.equal(await group.getAttribute('aria-expanded'), 'true');
    assert.ok(await sidebar.getByRole('link', { name: 'Rapor Merkezi', exact: true }).isVisible());
  });
  await check('mobile search clears on compact resize and keyboard focus remains visible', async () => {
    await mode.click(); await page.waitForTimeout(220);
    await page.setViewportSize({ width: 390, height: 844 });
    const trigger = page.getByRole('button', { name: 'Menüyü aç', exact: true });
    await trigger.click(); await page.waitForTimeout(220);
    await page.locator('#vpNavSearch').fill('zzz-no-module');
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.locator('.offcanvas-backdrop').waitFor({ state: 'detached' });
    assert.equal(await page.locator('#vpNavSearch').inputValue(), '');
    assert.ok(await sidebar.getByRole('link', { name: 'Ana Sayfa', exact: true }).isVisible());
    assert.ok(await mode.evaluate(el => el === document.activeElement));
    await mode.click();
    await page.locator('#vpNavSearch').focus();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.activeElement?.matches('.dashboard-mobile-menu-button'));
    assert.ok(await trigger.evaluate(el => el === document.activeElement));
    await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab');
    assert.equal(await trigger.evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.waitForFunction(() => document.activeElement?.matches('[data-nav-mode-toggle]'));
  });
  await check('report catalog stays accessible on desktop and toggles on mobile', async () => {
    await page.setViewportSize({ width: 1440, height: 960 });
    const catalog = page.locator('.report-catalog');
    await page.waitForFunction(() => document.querySelector('.report-catalog').open);
    assert.ok(await catalog.evaluate(el => el.open));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => !document.querySelector('.report-catalog').open);
    assert.equal(await catalog.evaluate(el => el.open), false);
    await catalog.locator('summary').click();
    assert.ok(await page.locator('.report-card-grid article').first().isVisible());
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.waitForFunction(() => document.querySelector('.report-catalog').open);
    assert.ok(await page.locator('.report-card-grid article').first().isVisible());
  });
  await check('form fields named method do not break CSRF initialization', async () => {
    assert.equal(await page.evaluate(() => {
      const form = document.createElement('form');
      form.setAttribute('method', 'post');
      const field = document.createElement('input'); field.name = 'method';
      form.append(field); document.body.append(form);
      form.addEventListener('submit', e => e.preventDefault());
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      const token = form.querySelector('[name="csrf_token"]')?.value;
      form.remove();
      return token === document.querySelector('meta[name="csrf-token"]').content;
    }), true);
  });
  await check('desktop rapid toggles and animation properties', async () => {
    const result = await page.evaluate(async () => {
      const button = document.querySelector('[data-nav-mode-toggle]');
      const samples = []; let last; let running = true;
      const tick = time => { if (last) samples.push(time - last); last = time; if (running) requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
      for (let i = 0; i < 8; i++) { button.click(); await new Promise(resolve => setTimeout(resolve, 100)); }
      await new Promise(resolve => setTimeout(resolve, 240)); running = false;
      const sidebarStyle = getComputedStyle(document.querySelector('#dashboardSidebar'));
      return { intervals: samples, transition: sidebarStyle.transitionDuration, width: sidebarStyle.width };
    });
    assert.equal(result.transition, '0s');
    assert.equal(result.width, '280px');
    frameSamples.push(result.intervals);
    await fit(page);
  });
  await check('desktop breakpoint and open mobile drawer resize', async () => {
    for (const width of [1199, 1200, 1366, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.getByRole('button', { name: 'Menüyü aç', exact: true }).isVisible(), width < 1200);
      await fit(page);
    }
    await page.setViewportSize({ width: 1100, height: 900 });
    await page.getByRole('button', { name: 'Menüyü aç', exact: true }).click();
    await sidebar.waitFor({ state: 'visible' });
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.locator('.offcanvas-backdrop').waitFor({ state: 'detached' });
    assert.notEqual(await page.locator('body').evaluate(el => el.style.overflow), 'hidden');
  });
  await ctx.close();

  for (const [width, height] of [[320, 740], [390, 844], [768, 1024], [1024, 768], [1366, 1024], [640, 400]]) {
    const context = await browser.newContext({ viewport: { width, height }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/super_admin');
    const p = await context.newPage();
    p.on('pageerror', e => failures.push({ name: `javascript-${width}`, error: e.message }));
    await p.goto(base + '/'); await ready(p);
    await check(`${width} mobile/tablet menu, focus, scroll, close`, async () => {
      await fit(p); await screenshot(p, `${width}-home`);
      const trigger = p.getByRole('button', { name: 'Menüyü aç', exact: true });
      await trigger.click();
      const menu = p.locator('#dashboardSidebar');
      await p.waitForTimeout(240);
      assert.ok(await p.evaluate(() => document.getElementById('dashboardSidebar').contains(document.activeElement)));
      for (const toggle of await menu.locator('.dashboard-nav-toggle').all()) {
        await toggle.scrollIntoViewIfNeeded();
        if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
      }
      const finalLink = menu.locator('.dashboard-sidebar-nav a').last();
      await finalLink.scrollIntoViewIfNeeded();
      const linkBox = await finalLink.boundingBox();
      assert.ok(linkBox.y >= 0 && linkBox.y + linkBox.height <= height);
      const logout = menu.getByRole('button', { name: 'Çıkış', exact: true });
      await logout.scrollIntoViewIfNeeded();
      const box = await logout.boundingBox();
      assert.ok(box.y >= 0 && box.y + box.height <= height);
      await screenshot(p, `${width}-menu`);
      await p.keyboard.press('Escape');
      await p.locator('.offcanvas-backdrop').waitFor({ state: 'detached' });
      assert.ok(await trigger.evaluate(el => el === document.activeElement));
      await trigger.click(); await p.waitForTimeout(220);
      await p.mouse.click(width - 3, 150);
      await p.locator('.offcanvas-backdrop').waitFor({ state: 'detached' });
      await fit(p);
    });
    if (width < 768 && height > 600) await check(`${width} collapsed filters and real form values`, async () => {
      const filter = p.getByRole('button', { name: 'Filtreler', exact: true });
      assert.equal(await p.locator('#search').isVisible(), false);
      await filter.click();
      await p.locator('#search').fill('üretim');
      await filter.click(); await filter.click();
      assert.equal(await p.locator('#search').inputValue(), 'üretim');
      await p.getByRole('button', { name: 'Filtrele', exact: true }).click();
      await p.waitForURL('**/?**');
      assert.ok(await p.locator('#search').isVisible());
      assert.equal(await p.locator('#search').inputValue(), 'üretim');
    });
    if (width === 390) await check('mobile document actions stay visible with collapsed filters', async () => {
      await p.goto(base + '/documents/list'); await ready(p);
      assert.ok(await p.getByRole('link', { name: 'Yeni Doküman', exact: true }).isVisible());
      assert.equal(await p.getByRole('heading', { name: 'Doküman Listesi', exact: true }).count(), 1);
      assert.equal(await p.locator('#search').isVisible(), false);
      await screenshot(p, '390-documents');
      await p.getByRole('button', { name: 'Filtreler', exact: true }).click();
      assert.ok(await p.locator('#department').isVisible());
      await fit(p);
    });
    await context.close();
  }
  for (const role of ['super_admin', 'management_representative', 'management', 'department_manager', 'department_staff', 'viewer']) {
    const c = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true });
    await c.request.get(base + '/__ui/login/' + role);
    const p = await c.newPage(); await p.goto(base + '/'); await ready(p);
    await check(`${role} search preserves rendered access boundaries`, async () => {
      const original = await p.locator('#dashboardSidebar a').evaluateAll(els => els.map(el => el.getAttribute('href')));
      await p.getByRole('button', { name: 'Menüyü aç', exact: true }).click();
      await p.locator('#vpNavSearch').fill('admin');
      if (role !== 'super_admin') assert.equal(await p.locator('#adminPanelNav').count(), 0);
      await p.locator('#vpNavSearch').fill('rapor');
      const current = await p.locator('#dashboardSidebar a').evaluateAll(els => els.filter(el => el.getClientRects().length).map(el => el.getAttribute('href')));
      assert.ok(current.every(link => original.includes(link)));
    });
    await c.close();
  }
  await check('reduced motion and blocked preference storage', async () => {
    const c = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
    await c.addInitScript(() => Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } }));
    await c.request.get(base + '/__ui/login/super_admin');
    const p = await c.newPage(); await p.goto(base + '/'); await ready(p);
    await p.locator('[data-nav-mode-toggle]').click();
    assert.equal(await p.evaluate(() => document.documentElement.dataset.navMode), 'compact');
    assert.equal(await p.evaluate(() => document.querySelector('.dashboard-main').getAnimations().length), 0);
    await c.close();
  });
} finally {
  await browser.close();
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify({ completed, failures, frameSamples }, null, 2));
}
console.log(JSON.stringify({ passed: completed.length, failures }, null, 2));
if (failures.length) process.exitCode = 1;
