import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5068';
const output = '.tmp-ui-audit/readiness-analysis';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const results = [];
const errors = [];
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width < 1000 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    for (const route of ['/satisa-hazirlik', '/rapor-merkezi/analiz', '/rapor-merkezi/analiz?source=dofs']) {
      const response = await page.goto(base + route);
      assert.equal(response.status(), 200, route);
      await page.waitForFunction(() => document.documentElement.dataset.navigationReady === 'true');
      assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
      if (route === '/satisa-hazirlik') {
        assert.equal(await page.locator('input[name="completed_items"]').count(), 140);
        assert.equal(await page.locator('input[value="competitor_esignature"], input[value="competitor_sso_mfa"]').count(), 0);
        const next = page.locator('#readiness-next-link');
        if (await next.count()) {
          await next.click();
          assert.equal(await page.evaluate(() => document.activeElement?.name), 'completed_items');
        }
        const selected = await page.locator('input[name="completed_items"]:checked').evaluateAll(els => els.map(el => el.value).sort());
        await Promise.all([
          page.waitForResponse(response => response.request().method() === 'POST' && response.url().includes('/satisa-hazirlik')),
          page.locator('button[form="sales-readiness-form"]').click(),
        ]);
        await page.waitForURL(url => url.pathname === '/satisa-hazirlik');
        await page.waitForLoadState('domcontentloaded');
        assert.deepEqual(await page.locator('input[name="completed_items"]:checked').evaluateAll(els => els.map(el => el.value).sort()), selected);
      } else {
        assert.ok(await page.locator('#analysis-records').isVisible());
        assert.equal(await page.locator('#dashboardSidebar a.active[href="/rapor-merkezi"]').count(), 1);
        const downloadPromise = page.waitForEvent('download');
        await page.locator('a[href*="/analiz/excel"]').click();
        const download = await downloadPromise;
        assert.ok(download.suggestedFilename().endsWith('.xlsx'));
        assert.equal(await download.failure(), null);
        await download.saveAs(`${output}/${width}-${route.includes('dofs') ? 'dofs' : 'actions'}.xlsx`);
      }
      const name = route.includes('satisa') ? 'checklist' : route.includes('dofs') ? 'dofs' : 'actions';
      await page.screenshot({ path: `${output}/${width}-${name}.png`, fullPage: true });
      results.push({ width, route, status: 'passed' });
    }
    await context.close();
  }
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ results, errors }));
} finally {
  await fs.writeFile(`${output}/results.json`, JSON.stringify({ results, errors }, null, 2));
  await browser.close();
}
