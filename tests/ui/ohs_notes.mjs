import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5134';
const browser = await chromium.launch({ channel: 'chrome', args: ['--disable-gpu'] });
const output = '.tmp-ui-audit/ohs-notes';
await fs.mkdir(output, { recursive: true });
async function login(page, name) {
  await page.goto(`${base}/login`);
  await page.locator('#company_code').selectOption('001');
  await page.locator('#identity').fill(name);
  await page.locator('#password').fill('Local-preview-001');
  await page.locator('button[type=submit]').click();
  await page.waitForURL(url => url.pathname !== '/login');
}
try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await login(page, 'personel');
    await page.goto(`${base}/mobil`);
    assert((await page.locator('a[href="/isg-notlari/yeni"]').innerText()).includes('İSG Notu Oluştur'));
    assert.equal(await page.locator('a[href="/isg-aksiyonlari/yeni"]').count(), 0);
    await page.locator('a[href="/isg-notlari/yeni"]').click();
    await page.locator('#title').fill(`Zemin gözlemi ${width}`);
    await page.locator('#location').fill('Üretim sahası');
    await page.locator('#description').fill('Geçiş alanında su birikmesi gözlendi.');
    await page.screenshot({ path: `${output}/${width}-form.png`, animations: 'disabled' });
    await page.getByRole('button', { name: 'Kaydet', exact: true }).click();
    await page.waitForURL(/\/isg-notlari\/\d+$/);
    const noteUrl = page.url();
    assert.equal(await page.getByRole('link', { name: 'Aksiyon Oluştur', exact: true }).count(), 0);
    await page.getByRole('link', { name: 'Düzenle', exact: true }).click();
    await page.locator('#description').fill('Geçiş alanı kontrol edilmeli.');
    await page.getByRole('button', { name: 'Kaydet', exact: true }).click();
    await page.waitForURL(noteUrl);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: `${output}/${width}-detail.png`, animations: 'disabled' });

    const managerContext = await browser.newContext({ viewport: { width, height: 900 } });
    const manager = await managerContext.newPage();
    await login(manager, 'yonetici');
    await manager.goto(noteUrl);
    await manager.getByRole('link', { name: 'Aksiyon Oluştur', exact: true }).click();
    assert.equal(await manager.locator('#title').inputValue(), `Zemin gözlemi ${width}`);
    assert.equal(await manager.locator('[name=description]').inputValue(), 'Geçiş alanı kontrol edilmeli.');
    assert(await manager.locator('[name=ohs_note_id]').inputValue());
    await manager.screenshot({ path: `${output}/${width}-conversion.png`, animations: 'disabled' });
    const responsible = await manager.locator('#responsible_user_id option').evaluateAll(
      options => options.find(option => option.value)?.value);
    await manager.locator('#responsible_user_id').selectOption(responsible);
    const department = await manager.locator('#department option').evaluateAll(
      options => options.find(option => option.value)?.value);
    await manager.locator('#department').selectOption(department);
    await manager.locator('#termin_date').fill('2026-12-31');
    await manager.getByRole('button', { name: 'Kaydet', exact: true }).click();
    await manager.waitForURL(`${base}/isg-aksiyonlari`);
    await manager.goto(noteUrl);
    assert.equal(await manager.getByRole('link', { name: 'Aksiyon Oluştur', exact: true }).count(), 0);
    assert(await manager.locator('a[href^="/actions/"]').count());
    const actionUrl = await manager.locator('a[href^="/actions/"]').first().getAttribute('href');
    await manager.goto(`${base}/isg-notlari`);
    assert(await manager.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await manager.screenshot({ path: `${output}/${width}-list.png`, animations: 'disabled' });
    await page.locator('summary').filter({ hasText: 'Notu Sil' }).click();
    await page.getByRole('button', { name: 'Silmeyi Onayla' }).click();
    await page.waitForURL(`${noteUrl}/sil`);
    assert.equal((await page.request.get(noteUrl)).status(), 200);
    await page.goto(noteUrl);
    await page.locator('summary').filter({ hasText: 'Notu Sil' }).click();
    await page.getByRole('button', { name: 'Silmeyi Onayla' }).click();
    await page.waitForURL(`${base}/isg-notlari`);
    assert.equal((await manager.request.get(`${base}${actionUrl}`)).status(), 200);
    assert.equal((await manager.request.get(noteUrl)).status(), 404);
    assert.equal((await manager.request.get(`${base}/isg-aksiyonlari/yeni`)).status(), 200);
    assert.deepEqual(errors, []);
    console.log(`${width}: mobile shortcut, CSRF create/edit/delete, owner permission, manager conversion prefill, overflow passed`);
    await managerContext.close();
    await context.close();
  }
} finally { await browser.close(); }
