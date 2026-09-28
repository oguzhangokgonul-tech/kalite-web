import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5091';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
const failures = [];

try {
  for (const width of [390, 768, 1024, 1440]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      hasTouch: true,
      isMobile: width < 768,
      serviceWorkers: 'allow',
    });
    await context.request.get(base + '/__ui/login/management_representative');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    page.setDefaultTimeout(15000);
    try {
      const response = await page.goto(base + '/mobil', { waitUntil: 'networkidle' });
      assert.equal(response.status(), 200);
      assert.match(await page.locator('body').innerText(), /Mobil Merkez/);
      await page.locator('.pwa-qr-frame img').waitFor({ state: 'visible' });
      assert.equal(
        await page.locator('.pwa-qr-frame img').evaluate((image) => image.complete && image.naturalWidth > 0),
        true,
      );
      assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
      const manifest = await page.evaluate(async () => (await fetch('/manifest.webmanifest')).json());
      assert.equal(manifest.start_url, '/mobil');
      assert.equal(manifest.scope, '/');
      assert.match(manifest.name, /VolkaPortal/);
      assert.deepEqual(errors, []);
      await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-pwa.png`, fullPage: true });
      completed.push(width);
    } catch (error) {
      failures.push({
        width,
        error: error.message,
        url: page.url(),
        body: (await page.locator('body').innerText()).slice(0, 1400),
      });
    }
    await context.close();
  }

  const iosContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
    serviceWorkers: 'allow',
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1',
  });
  await iosContext.request.get(base + '/__ui/login/department_staff');
  const iosPage = await iosContext.newPage();
  try {
    await iosPage.goto(base + '/mobil', { waitUntil: 'networkidle' });
    const install = iosPage.locator('[data-pwa-install]').last();
    await install.waitFor({ state: 'visible' });
    assert.match(await install.innerText(), /Ana Ekrana Ekle/);
    await install.click();
    await iosPage.locator('[data-pwa-ios-help]').last().waitFor({ state: 'visible' });
  } catch (error) {
    failures.push({ width: 'ios', error: error.message, url: iosPage.url() });
  }
  await iosContext.close();

  const offlineContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
    serviceWorkers: 'allow',
  });
  await offlineContext.request.get(base + '/__ui/login/department_staff');
  const offlinePage = await offlineContext.newPage();
  try {
    await offlinePage.goto(base + '/mobil', { waitUntil: 'networkidle' });
    await offlinePage.evaluate(async () => {
      await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller) {
        await new Promise((resolve) => navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true }));
      }
    });
    await offlineContext.setOffline(true);
    await offlinePage.goto(base + '/mobil?offline-test=1', { waitUntil: 'domcontentloaded' });
    assert.match(await offlinePage.locator('body').innerText(), /Bağlantı kurulamadı/);
  } catch (error) {
    failures.push({ width: 'offline', error: error.message, url: offlinePage.url() });
  }
  await offlineContext.close();
} finally {
  await browser.close();
  await fs.writeFile(
    '.tmp-ui-audit/responsive/pwa.json',
    JSON.stringify({ completed, failures }, null, 2),
  );
}

console.log(JSON.stringify({ completed, failures }, null, 2));
if (failures.length) process.exitCode = 1;
