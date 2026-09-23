import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5084';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
const failures = [];

try {
  for (const width of [390, 768, 1440]) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      hasTouch: true,
      isMobile: width < 768,
    });
    await context.request.get(base + '/__ui/login/management_representative');
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    const name = `Parametrik Kontrol ${width}`;
    try {
      let response = await page.goto(base + '/dinamik-formlar', { waitUntil: 'domcontentloaded' });
      assert.equal(response.status(), 200);
      await page.getByRole('link', { name: 'Yeni Şablon', exact: true }).click();

      await page.locator('#name').fill(name);
      const fields = page.locator('.dynamic-field-row');
      await fields.nth(0).locator('.field-label').fill('Devam kararı');
      await fields.nth(0).locator('.field-type').selectOption('single_choice');
      await fields.nth(0).locator('[name="field_options"]').fill('Evet\nHayır');
      await fields.nth(0).locator('[name="field_layout_width"]').selectOption('6');

      await page.getByRole('button', { name: 'Alan Ekle', exact: true }).click();
      await fields.nth(1).locator('.field-label').fill('İletişim e-postası');
      await fields.nth(1).locator('.field-type').selectOption('email');
      await fields.nth(1).locator('.required-box').check();
      await fields.nth(1).locator('[name="field_layout_width"]').selectOption('6');
      await fields.nth(1).locator('summary').click();
      await fields.nth(1).locator('[name="field_min_length"]').fill('6');
      await fields.nth(1).locator('.condition-source').selectOption({ label: 'Devam kararı' });
      await fields.nth(1).locator('[name="field_condition_operator"]').selectOption('equals');
      await fields.nth(1).locator('[name="field_condition_value"]').fill('Evet');

      await page.getByRole('button', { name: 'Alan Ekle', exact: true }).click();
      await fields.nth(2).locator('.field-label').fill('Memnuniyet puanı');
      await fields.nth(2).locator('.field-type').selectOption('rating');
      await fields.nth(2).locator('.required-box').check();
      await fields.nth(2).locator('summary').click();
      await fields.nth(2).locator('[name="field_min_value"]').fill('1');
      await fields.nth(2).locator('[name="field_max_value"]').fill('10');
      await fields.nth(2).getByRole('button', { name: 'Yukarı taşı' }).click();
      assert.equal(await fields.nth(1).locator('.field-label').inputValue(), 'Memnuniyet puanı');
      await fields.nth(1).getByRole('button', { name: 'Aşağı taşı' }).click();

      await page.getByRole('button', { name: 'Taslağı Kaydet', exact: true }).click();
      await page.waitForURL('**/dinamik-formlar/surum/*/duzenle');
      await page.getByRole('link', { name: 'Dinamik Formlar', exact: true }).click();
      await page.waitForURL('**/dinamik-formlar');
      const templateRow = page.locator('tr', { hasText: name });
      page.once('dialog', dialog => dialog.accept());
      await templateRow.getByRole('button', { name: 'Yayınla', exact: true }).click();
      await page.waitForLoadState('domcontentloaded');
      await templateRow.getByRole('link', { name: 'Ata', exact: true }).click();
      await page.locator('#assigned_user_id').selectOption({ label: 'management_representative' });
      await page.getByRole('button', { name: 'Formu Ata', exact: true }).click();
      await page.waitForURL('**/dinamik-formlar');

      const assignmentRow = page.locator('tr', { hasText: name }).last();
      await assignmentRow.getByRole('link', { name: 'Doldur', exact: true }).click();
      const decision = page.locator('.dynamic-response-field', { hasText: 'Devam kararı' });
      const email = page.locator('.dynamic-response-field', { hasText: 'İletişim e-postası' });
      const rating = page.locator('.dynamic-response-field', { hasText: 'Memnuniyet puanı' });
      await email.waitFor({ state: 'hidden' });
      await decision.locator('select').selectOption('Evet');
      await email.waitFor({ state: 'visible' });
      await email.locator('input').fill('kalite@example.com');
      await rating.locator('select').selectOption('8');
      await page.getByRole('button', { name: 'Tamamla ve Gönder', exact: true }).click();
      await page.waitForURL('**/dinamik-formlar/sonuc/*');
      assert.match(await page.locator('body').innerText(), /kalite@example\.com/);
      assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
      assert.deepEqual(errors, []);
      await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-dynamic-forms.png`, fullPage: true });
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
} finally {
  await browser.close();
  await fs.writeFile(
    '.tmp-ui-audit/responsive/dynamic-forms.json',
    JSON.stringify({ completed, failures }, null, 2),
  );
}

console.log(JSON.stringify({ completed, failures }, null, 2));
if (failures.length) process.exitCode = 1;
