import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5100';
const browser = await chromium.launch({ headless: true, channel: 'chrome', args: ['--disable-gpu'] });
const completed = [];
const output = '.tmp-ui-audit/custody';
await mkdir(output, { recursive: true });
try {
  for (const width of [360, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width < 1000, isMobile: width < 768 });
    await context.request.get(base + '/__preview/login/management_representative');
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const inspect = async name => {
      await page.waitForLoadState('load');
      await page.locator('.custody-page').waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, name + ': overflow');
      const small = await page.locator('.custody-page .btn, .custody-page .form-control, .custody-page .form-select').evaluateAll(elements =>
        elements.filter(el => el.getBoundingClientRect().height > 0 && el.getBoundingClientRect().height < 43).map(el => ({ height: el.getBoundingClientRect().height, html: el.outerHTML })));
      assert.deepEqual(small, [], name + ': touch targets');
      await page.screenshot({ path: `${output}/${width}-${name}.png`, fullPage: true });
    };
    const submit = async name => {
      await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), page.getByRole('button', { name, exact: true }).click()]);
    };
    await page.goto(base + '/mobil');
    await page.locator('.pwa-action-card[href="/zimmet-yonetimi"]').click();
    await inspect('list');
    await page.getByRole('link', { name: 'Yeni Zimmet', exact: true }).click();
    await page.locator('#custody-personnel').selectOption({ index: 1 });
    const item = `Mobil Bilgisayar ${width}-${Date.now()}`;
    await page.locator('#custody-item').fill(item);
    await page.locator('#custody-serial').fill(`UI-${width}-${Date.now()}`);
    await page.locator('#custody-notes').fill('Mobil zimmet kontrolu');
    await inspect('form');
    await submit('Zimmeti Kaydet');
    const detailUrl = page.url();
    assert.match(detailUrl, /\/zimmet-yonetimi\/\d+$/);
    await inspect('detail');
    await page.getByRole('link', { name: 'Zimmeti d\u00fczenle', exact: true }).click();
    await page.locator('#custody-notes').fill('Duzenlenmis kayit');
    await submit('De\u011fi\u015fiklikleri Kaydet');
    assert.match(await page.locator('.custody-page').innerText(), /Duzenlenmis kayit/);
    await page.goto('about:blank');
    await context.request.get(base + '/__preview/login/department_staff');
    await page.goto(detailUrl);
    assert.equal(await page.locator('#custody-return-date').count(), 0);
    assert.equal(await page.getByRole('link', { name: 'Zimmeti d\u00fczenle', exact: true }).count(), 0);
    await inspect('staff');
    await page.goto('about:blank');
    await context.request.get(base + '/__preview/login/management_representative');
    await page.goto(detailUrl);
    await page.locator('#custody-return-note').fill('Saglam teslim alindi');
    await submit('Tamam\u0131n\u0131 \u0130ade Al');
    assert.equal(await page.locator('#custody-return-date').count(), 0);
    assert.match(await page.locator('.custody-page').innerText(), /Saglam teslim alindi/);
    await inspect('returned');
    await page.goto(base + '/zimmet-yonetimi?status=returned');
    await page.locator('#custody-search').fill(item);
    await submit('Filtrele');
    assert.equal(await page.locator('.custody-item').count(), 1);
    await inspect('filtered');
    const downloading = page.waitForEvent('download');
    await page.getByRole('link', { name: 'Excel indir', exact: true }).click();
    const download = await downloading;
    assert.match(download.suggestedFilename(), /^zimmetler-\d{8}\.xlsx$/);
    assert.equal(await download.failure(), null);
    assert.deepEqual(errors, []);
    completed.push({ width, create: true, edit: true, ownRead: true, return: true, filter: true, export: true });
    await context.close();
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({ completed }, null, 2));
