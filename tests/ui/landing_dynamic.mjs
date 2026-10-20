import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = (process.env.UI_BASE_URL || 'http://127.0.0.1:5132') + '/landing-dynamic-preview';
const output = '.tmp-ui-audit/landing-original-scroll';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true,
  args: process.env.UI_DISABLE_GPU === '1' ? ['--disable-gpu'] : [] });
const screenshotOptions = { animations: 'disabled', timeout: 120000 };
const keys = ['actions', 'if', 'audit', 'docs', 'maintenance'];
const results = [];

async function aligned(page, id) {
  await page.waitForFunction(id => {
    const target = document.getElementById(id);
    const rect = target.getBoundingClientRect();
    const offset = parseFloat(getComputedStyle(target).scrollMarginTop);
    const expected = Math.max(0, Math.min(document.documentElement.scrollHeight - innerHeight, rect.top + scrollY - offset));
    return Math.abs(scrollY - expected) < 3;
  }, id);
}

try {
  for (const [width, height] of [[1440, 768], [1366, 768], [1280, 720], [1101, 720],
    [320, 900], [390, 900], [768, 900], [1024, 900], [1440, 900], [1920, 900]]) {
    const shot = `${width}x${height}`;
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    page.setDefaultTimeout(120000);
    const errors = [], failures = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => { if (response.status() >= 400) failures.push(response.url()); });
    assert.equal((await page.goto(base + '#top', { waitUntil: 'networkidle' })).status(), 200);
    await aligned(page, 'top');
    assert(await page.evaluate(() => scrollY < 3), 'Top link must retain the complete navigation');
    assert.equal(await page.locator('[data-flow-tab]').count(), 0);
    assert(await page.locator('.vp-dynamic-product').isVisible());
    assert.equal(await page.locator('h1').innerText(), 'Kurumsal S\u00fcre\u00e7\nY\u00f6netiminde\nG\u00fcvenilir Dijital \u00c7\u00f6z\u00fcm');
    assert.equal(await page.locator('.vp-dynamic').evaluate(el => getComputedStyle(el).getPropertyValue('--dyn-navy').trim()), '#071421');
    await page.screenshot({ ...screenshotOptions, path: `${output}/${shot}-first.png` });
    for (const id of ['platform', 'flow', 'modules', 'demo']) {
      await page.locator(`.vp-dynamic-nav a[href="#${id}"]`).click();
      await aligned(page, id);
    }
    await page.locator('.vp-dynamic-brand').evaluate(el => el.click());
    await page.waitForFunction(() => scrollY < 3);
    if (width > 1100) {
      assert.equal(await page.locator('.is-inline-story').count(), 0);
      assert.equal(await page.locator('.vp-story-visual > .vp-scene').count(), 5);
      for (const key of [...keys, ...keys.toReversed()]) {
        await page.evaluate(key => {
          const root = document.querySelector('[data-dynamic-landing]');
          const el = document.querySelector(`[data-scene-trigger="${key}"]`);
          const rect = el.getBoundingClientRect();
          const space = parseFloat(getComputedStyle(root).getPropertyValue('--landing-anchor-offset'));
          scrollTo({ top: scrollY + rect.top + rect.height / 2 - (innerHeight + space) / 2, behavior: 'instant' });
        }, key);
        await page.waitForFunction(key => document.querySelector('[data-dynamic-landing]').dataset.activeScene === key, key);
        const state = await page.evaluate(key => {
          const el = document.querySelector(`[data-scene="${key}"]`);
          const rect = el.getBoundingClientRect();
          const copy = document.querySelector(`[data-scene-trigger="${key}"]`).getBoundingClientRect();
          return { top: rect.top, bottom: rect.bottom, rightOfCopy: rect.left >= copy.right,
            header: document.querySelector('header').getBoundingClientRect().bottom,
            hidden: el.getAttribute('aria-hidden'), inactive: [...document.querySelectorAll('.vp-scene:not(.is-active)')].every(el => el.getAttribute('aria-hidden') === 'true') };
        }, key);
        assert.equal(state.hidden, 'false');
        assert(state.inactive);
        assert(state.rightOfCopy, `${shot}: scene must stay beside text`);
        assert(state.top >= state.header && state.bottom <= height + 2, JSON.stringify(state));
        const badgesClear = await page.locator(`[data-scene="${key}"]`).evaluate(scene => {
          const panel = scene.getBoundingClientRect();
          return [...scene.querySelectorAll('.vp-scene-chip')].every(chip => {
            const rect = chip.getBoundingClientRect();
            return (rect.bottom <= panel.top || rect.top >= panel.bottom)
              && rect.top >= document.querySelector('header').getBoundingClientRect().bottom
              && rect.bottom <= innerHeight + 2;
          });
        });
        assert(badgesClear, `${key}: animated badges must not cover panel content`);
      }
      await page.locator('#flow-docs').evaluate(el => el.scrollIntoView({ behavior: 'instant', block: 'center' }));
      await page.waitForTimeout(350);
      await page.screenshot({ ...screenshotOptions, path: `${output}/${shot}-story.png` });
    } else {
      for (const key of keys) {
        assert(await page.locator(`[data-scene-trigger="${key}"]`).evaluate(el => el.nextElementSibling?.dataset.scene === el.dataset.sceneTrigger));
        const scene = page.locator(`[data-scene="${key}"]`);
        assert.equal(await scene.getAttribute('aria-hidden'), 'false');
        assert(await scene.isVisible());
      }
      const last = await page.locator('[data-scene="maintenance"]').boundingBox();
      const footer = await page.locator('footer').boundingBox();
      assert(last.y + last.height <= footer.y, 'Inline panels must not overlap footer');
    }
    await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
    const state = await page.evaluate(() => ({
      width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth,
      brokenImages: [...document.images].filter(img => !img.complete || !img.naturalWidth).length,
      missingAnchors: [...document.querySelectorAll('a[href^="#"]')].filter(a => !document.getElementById(a.hash.slice(1))).length,
    }));
    assert(state.scrollWidth <= width);
    assert.equal(state.brokenImages, 0);
    assert.equal(state.missingAnchors, 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(failures, []);
    await page.screenshot({ ...screenshotOptions, path: `${output}/${shot}.png` });
    results.push({ ...state, scenes: 5, forwardAndBack: width > 1100 });
    await context.close();
  }

  for (const options of [{ javaScriptEnabled: false }, { reducedMotion: 'reduce' }, { colorScheme: 'dark' }]) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ...options });
    const page = await context.newPage();
    await page.goto(base + '#flow-docs', { waitUntil: 'networkidle' });
    if (options.javaScriptEnabled !== false) await aligned(page, 'flow-docs');
    assert.equal(await page.locator('.vp-scene:visible').count(), 5);
    if (options.reducedMotion) assert.equal(await page.evaluate(() => document.getAnimations().length), 0);
    await page.evaluate(() => { location.hash = 'flow-actions'; });
    if (options.javaScriptEnabled !== false) {
      await aligned(page, 'flow-actions');
      await page.goBack();
      await aligned(page, 'flow-docs');
      await page.goForward();
      await aligned(page, 'flow-actions');
    }
    await page.screenshot({ ...screenshotOptions, path: `${output}/${Object.keys(options)[0]}.png` });
    results.push({ options, passed: true });
    await context.close();
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.setViewportSize({ width: 1440, height: 768 });
  await page.waitForFunction(() => !document.querySelector('.vp-dynamic').classList.contains('is-inline-story'));
  assert.equal(await page.locator('.vp-story-visual > .vp-scene').count(), 5);
  results.push({ shortDesktop: '1440x768', sideBySidePanels: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => document.querySelector('.vp-dynamic').classList.contains('is-inline-story'));
  await page.setViewportSize({ width: 1440, height: 768 });
  await page.waitForFunction(() => document.querySelector('.vp-story-visual').children.length === 5);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.setViewportSize({ width: 1366, height: 600 });
  await page.locator('#flow-actions').evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.waitForFunction(() => document.querySelector('[data-dynamic-landing]').dataset.activeScene === 'actions');
  const shortWindow = await page.locator('.vp-story-visual').evaluate(el => {
    el.scrollTop = el.scrollHeight;
    const box = el.getBoundingClientRect();
    const footer = el.querySelector('.vp-scene.is-active .vp-scene-footer').getBoundingClientRect();
    return { scrollable: el.scrollHeight > el.clientHeight, bottom: box.bottom,
      footerVisible: footer.bottom <= box.bottom && footer.top >= box.top,
      inline: document.querySelector('.vp-dynamic').classList.contains('is-inline-story') };
  });
  assert(shortWindow.scrollable && shortWindow.footerVisible && !shortWindow.inline);
  assert(shortWindow.bottom <= 602);
  results.push({ shortWindow: '1366x600', ...shortWindow });
  await page.locator('.vp-story-visual').evaluate(el => { el.scrollTop = 0; });
  await page.setViewportSize({ width: 1440, height: 900 });
  const client = await context.newCDPSession(page);
  await client.send('Performance.enable');
  const metrics = async () => Object.fromEntries((await client.send('Performance.getMetrics')).metrics.map(m => [m.name, m.value]));
  const before = await metrics();
  const timing = await page.evaluate(async () => {
    const root = document.querySelector('.vp-dynamic');
    let geometryReads = 0;
    document.querySelectorAll('[data-scene-trigger]').forEach(el => {
      const original = el.getBoundingClientRect.bind(el);
      el.getBoundingClientRect = () => { geometryReads++; return original(); };
    });
    const start = document.querySelector('#flow').getBoundingClientRect().top + scrollY;
    const end = document.querySelector('#demo').getBoundingClientRect().top + scrollY;
    const intervals = [];
    await new Promise(resolve => {
      let first = 0, last = 0;
      function step(now) {
        if (!first) first = now;
        if (last) intervals.push(now - last);
        last = now;
        const t = Math.min(1, (now - first) / 1800);
        scrollTo({ top: start + (end - start) * t, behavior: 'instant' });
        if (t < 1) requestAnimationFrame(step); else resolve();
      }
      requestAnimationFrame(step);
    });
    intervals.sort((a,b) => a-b);
    return { frames: intervals.length, medianMs: intervals[Math.floor(intervals.length / 2)], p95Ms: intervals[Math.floor(intervals.length * .95)], geometryReads, scene: root.dataset.activeScene };
  });
  const after = await metrics();
  results.push({ syntheticScroll: timing, layoutCount: after.LayoutCount - before.LayoutCount,
    layoutDurationMs: (after.LayoutDuration - before.LayoutDuration) * 1000,
    gpuDisabled: process.env.UI_DISABLE_GPU === '1', notPhysical144HzProof: true });
  await context.close();
  await fs.writeFile(`${output}/results.json`, JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
} finally { await browser.close(); }
