import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5117';
const output = '.tmp-ui-audit/theme';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--disable-gpu'] });
const failures = [], results = [];
try {
  for (const width of [320, 390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 960 } });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    page.on('pageerror', error => failures.push(error.message));
    for (const pathname of ['/', '/mobil', '/documents/list', '/kalibrasyon', '/insan-kaynaklari/personel-listesi', '/kalite-deneyleri/beton-deneyi', '/actions/1', '/documents/upload']) {
      const response = await page.goto(base + pathname);
      assert.equal(response.status(), 200, pathname);
      const toggle = page.locator('[data-theme-toggle]');
      await toggle.waitFor({ state: 'visible' });
      if (await toggle.getAttribute('aria-pressed') === 'false') await toggle.click();
      assert.equal(await page.locator('html').getAttribute('data-bs-theme'), 'dark');
      const box = await toggle.boundingBox();
      assert.ok(box.width >= 40 && box.height >= 40, 'touch target');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      if (overflow > 1) failures.push(`${width} ${pathname}: overflow ${overflow}`);
      const body = await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor);
      assert.notEqual(body, 'rgb(255, 255, 255)', pathname);
      await page.screenshot({ path: `${output}/${width}-${pathname.replaceAll('/', '_') || 'home'}-dark.png` });
      results.push({ width, pathname, body });
    }
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-bs-theme'), 'dark', 'saved theme');
    await page.emulateMedia({ media: 'print' });
    assert.equal(await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)', 'print stays light');
    await page.emulateMedia({ media: 'screen' });
    await page.locator('[data-theme-toggle]').click();
    assert.equal(await page.locator('html').getAttribute('data-bs-theme'), 'light');
    await page.screenshot({ path: `${output}/${width}-light.png` });
    await context.close();
  }
  const context = await browser.newContext();
  await context.request.get(base + '/__ui/login/super_admin');
  const page = await context.newPage();
  await page.goto(base + '/documents/upload');
  const input = page.locator('input[name="title"]');
  await input.fill('Theme preserves unsaved input');
  await page.locator('[data-theme-toggle]').click();
  assert.equal(await input.inputValue(), 'Theme preserves unsaved input');
  const second = await context.newPage();
  await second.goto(base + '/');
  assert.equal(await second.locator('html').getAttribute('data-bs-theme'), 'dark');
  await page.locator('[data-theme-toggle]').click();
  await second.waitForFunction(() => document.documentElement.dataset.bsTheme === 'light');
  await page.locator('[data-theme-toggle]').click();
  await context.request.get(base + '/__ui/login/viewer');
  await page.goto(base + '/');
  assert.equal(await page.locator('html').getAttribute('data-bs-theme'), 'light', 'user isolation');
  await context.close();
  for (const javaScriptEnabled of [true, false]) {
    const guest = await browser.newContext({ javaScriptEnabled, viewport: { width: 390, height: 844 } });
    const page = await guest.newPage();
    await page.goto(base + '/login');
    assert.equal(await page.locator('[data-theme-toggle]').isVisible(), javaScriptEnabled);
    if (javaScriptEnabled) {
      await page.locator('[data-theme-toggle]').click();
      await page.screenshot({ path: `${output}/login-dark.png` });
      await page.reload();
      assert.equal(await page.locator('html').getAttribute('data-bs-theme'), 'dark');
    }
    await guest.close();
  }
  await fs.writeFile(`${output}/results.json`, JSON.stringify({ results, failures }, null, 2));
  assert.deepEqual(failures, []);
  console.log(`PASS ${results.length} responsive dark views; persistence, print, tabs, user isolation, unsaved form, login and no-JS`);
} finally {
  await browser.close();
}
