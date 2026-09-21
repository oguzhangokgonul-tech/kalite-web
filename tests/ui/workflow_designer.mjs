import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5082';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
const failures = [];

try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/management_representative');
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    const name = `Mobil Onay Akışı ${width}`;
    try {
      let response = await page.goto(base + '/is-akislari', { waitUntil: 'domcontentloaded' });
      assert.equal(response.status(), 200);
      assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
      await page.getByRole('link', { name: 'Yeni Akış', exact: true }).click();
      await page.locator('[name="name"]').fill(name);
      await page.getByRole('button', { name: 'Tasarlamaya Başla', exact: true }).click();
      await page.getByRole('button', { name: 'Adım Ekle', exact: true }).click();
      await page.getByRole('button', { name: 'Adım Ekle', exact: true }).click();
      const steps = page.locator('.workflow-step');
      assert.equal(await steps.count(), 2);
      await steps.nth(0).locator('[name="step_name"]').fill('Yönetim Onayı');
      await steps.nth(0).locator('[name="step_type"]').selectOption('approval');
      await steps.nth(0).locator('[name="assignment_mode"]').selectOption('user');
      await steps.nth(0).locator('[name="assigned_user_id"]').selectOption({ label: 'management' });
      await steps.nth(1).locator('[name="step_name"]').fill('Uygulama Görevi');
      await steps.nth(1).locator('[name="step_type"]').selectOption('task');
      await steps.nth(1).locator('[name="assignment_mode"]').selectOption('user');
      await steps.nth(1).locator('[name="assigned_user_id"]').selectOption({ label: 'department_staff' });
      await steps.nth(1).getByRole('button', { name: 'Yukarı taşı' }).click();
      assert.equal(await steps.nth(0).locator('[name="step_name"]').inputValue(), 'Uygulama Görevi');
      await steps.nth(0).getByRole('button', { name: 'Aşağı taşı' }).click();
      assert.equal(await steps.nth(0).locator('[name="step_name"]').inputValue(), 'Yönetim Onayı');
      await page.getByRole('button', { name: 'Taslağı Kaydet', exact: true }).click();
      await page.waitForLoadState('domcontentloaded');
      await page.getByRole('button', { name: 'Kaydedilmiş Sürümü Yayınla', exact: true }).click();
      await page.waitForURL('**/is-akislari');
      assert.match(await page.locator('body').innerText(), new RegExp(name));

      if (width === 390) {
        await context.request.get(base + '/__ui/login/department_staff');
        await page.goto(base + '/is-akislari', { waitUntil: 'domcontentloaded' });
        const templateRow = page.locator('tr', { hasText: name });
        await templateRow.getByRole('link', { name: 'Başlat', exact: true }).click();
        await page.locator('[name="title"]').fill('Mobil satın alma talebi');
        await page.locator('[name="department_id"]').selectOption({ index: 1 });
        await page.locator('[name="description"]').fill('Mobil kullanım akışı doğrulaması.');
        await page.getByRole('button', { name: 'Süreci Başlat', exact: true }).click();
        await page.waitForURL('**/is-akislari/kayit/*');
        const detailUrl = page.url();
        await context.request.get(base + '/__ui/login/management');
        await page.goto(detailUrl, { waitUntil: 'domcontentloaded' });
        await page.locator('[name="note"]').fill('Bütçe bilgisini ekleyin.');
        await page.locator('button[name="decision"][value="return"]').click();
        await context.request.get(base + '/__ui/login/department_staff');
        await page.goto(detailUrl, { waitUntil: 'domcontentloaded' });
        const resubmitButton = page.getByRole('button', { name: 'Yeniden Gönder', exact: true });
        await resubmitButton.waitFor({ state: 'visible' });
        await page.locator('[name="description"]').fill('Bütçe bilgisi eklenmiş mobil kullanım akışı.');
        await resubmitButton.click();
        await context.request.get(base + '/__ui/login/management');
        await page.goto(detailUrl, { waitUntil: 'domcontentloaded' });
        const approveButton = page.locator('button[name="decision"][value="approve"]');
        await approveButton.waitFor({ state: 'visible' });
        await approveButton.click();
        await context.request.get(base + '/__ui/login/department_staff');
        await page.goto(detailUrl, { waitUntil: 'domcontentloaded' });
        const completeButton = page.locator('button[name="decision"][value="approve"]');
        await completeButton.waitFor({ state: 'visible' });
        await completeButton.click();
        assert.match(await page.locator('body').innerText(), /Tamamlandı/);
        await context.request.get(base + '/__ui/login/management_representative');
        await page.goto(detailUrl, { waitUntil: 'domcontentloaded' });
        await page.getByRole('button', { name: 'Arşivle', exact: true }).waitFor({ state: 'visible' });
      }
      assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
      assert.deepEqual(errors, []);
      await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-workflow-designer.png`, fullPage: true });
      completed.push(width);
    } catch (error) {
      failures.push({ width, error: error.message, url: page.url(), body: (await page.locator('body').innerText()).slice(0, 1200) });
    }
    await context.close();
  }
} finally {
  await browser.close();
  await fs.writeFile('.tmp-ui-audit/responsive/workflow-designer.json', JSON.stringify({ completed, failures }, null, 2));
}

console.log(JSON.stringify({ completed, failures }, null, 2));
if (failures.length) process.exitCode = 1;
