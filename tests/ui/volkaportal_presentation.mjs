import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const entry = path.resolve('app/static/presentations/vp-tanitim-a91f4c72/index.html');
const entryUrl = process.env.PRESENTATION_URL || pathToFileURL(entry).href;
const output = path.resolve('.tmp-presentation-qa');
await fs.mkdir(output, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--disable-gpu'] });
try {
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 900 },
    { name: 'tablet', width: 768, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'mobile-small', width: 320, height: 700 },
  ]) {
    const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(entryUrl, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.locator('.slide').count(), 13);
    assert.deepEqual(errors, []);

    const assets = await page.locator('img[src]').evaluateAll(images => images.map(image => ({ src: image.src, eager: image.loading !== 'lazy', loaded: image.complete && image.naturalWidth > 0 })));
    for (const asset of assets) {
      if (asset.src.startsWith('file:')) await fs.access(fileURLToPath(asset.src));
      else assert.ok((await page.request.get(asset.src)).ok(), `${viewport.name}: asset ${asset.src}`);
    }
    assert.deepEqual(assets.filter(asset => asset.eager && !asset.loaded), [], `${viewport.name}: broken eager images`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    assert.ok(overflow <= 1, `${viewport.name}: horizontal overflow ${overflow}px`);

    await page.screenshot({ path: path.join(output, `${viewport.name}-cover.png`), animations: 'disabled' });
    await page.locator('#mobil').evaluate(slide => slide.scrollIntoView({ block: 'start', behavior: 'instant' }));
    await page.waitForTimeout(650);
    await page.screenshot({ path: path.join(output, `${viewport.name}-mobile-center.png`), animations: 'disabled' });
    await page.locator('#yonetim').evaluate(slide => slide.scrollIntoView({ block: 'start', behavior: 'instant' }));
    await page.waitForTimeout(650);
    const managementTop = await page.locator('#yonetim').evaluate(slide => slide.getBoundingClientRect().top);
    assert.ok(Math.abs(managementTop) <= 2, `${viewport.name}: section shifted by ${managementTop}px`);
    await page.screenshot({ path: path.join(output, `${viewport.name}-management.png`), animations: 'disabled' });

    await page.locator('#outline-button').click();
    assert.equal(await page.locator('#outline-dialog').evaluate(dialog => dialog.open), true);
    await page.locator('#outline-nav a[href="#kalite"]').click();
    await page.waitForTimeout(500);
    assert.equal(await page.locator('#outline-dialog').evaluate(dialog => dialog.open), false);
    await page.locator('#kalite figure.screen').click();
    assert.equal(await page.locator('#image-dialog').evaluate(dialog => dialog.open), true);
    await page.locator('#image-close').click();
    assert.equal(await page.locator('#image-dialog').evaluate(dialog => dialog.open), false);
    await page.locator('#mobil figure.phone-screen').click();
    assert.equal(await page.locator('#image-dialog').evaluate(dialog => dialog.open), true);
    if (viewport.width <= 390) {
      const widths = await page.evaluate(() => ({
        preview: document.querySelector('.phone-screen img').getBoundingClientRect().width,
        expanded: document.querySelector('#image-expanded').getBoundingClientRect().width,
      }));
      assert.ok(widths.expanded > widths.preview, `${viewport.name}: phone image did not enlarge`);
    }
    await page.locator('#image-close').click();

    await page.evaluate(() => document.activeElement?.blur());
    await page.keyboard.press('End');
    await page.waitForTimeout(1200);
    assert.match(await page.locator('#slide-counter').textContent(), /^13 \/ 13$/);
    await page.keyboard.press('ArrowLeft');
    await page.waitForTimeout(800);
    assert.match(await page.locator('#slide-counter').textContent(), /^12 \/ 13$/);
    await page.keyboard.press('Home');
    await page.waitForTimeout(1200);
    assert.match(await page.locator('#slide-counter').textContent(), /^01 \/ 13$/);
    await page.locator('#next-button').click();
    await page.waitForTimeout(750);
    await page.keyboard.press('ArrowLeft');
    await page.waitForTimeout(750);
    assert.match(await page.locator('#slide-counter').textContent(), /^01 \/ 13$/);

    if (viewport.name === 'desktop' || viewport.name === 'mobile') {
      for (const id of ['akis', 'giris', 'kalite', 'katilim', 'operasyon', 'raporlama', 'son']) {
        await page.locator(`#${id}`).evaluate(slide => slide.scrollIntoView({ block: 'start', behavior: 'instant' }));
        await page.waitForTimeout(150);
        await page.screenshot({ path: path.join(output, `${viewport.name}-${id}.png`), animations: 'disabled' });
      }
    }

    console.log(`${viewport.name}: 13 slides, images, layout, outline and image zoom passed`);
    await page.close();
  }
} finally {
  await browser.close();
}
