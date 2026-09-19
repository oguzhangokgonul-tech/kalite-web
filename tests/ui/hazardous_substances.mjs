import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5080';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];

const isoDate = (offset) => {
  const value = new Date();
  value.setDate(value.getDate() + offset);
  return value.toISOString().slice(0, 10);
};

try {
  for (const width of [390, 768]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: true, isMobile: width < 768 });
    await context.request.get(base + '/__ui/login/super_admin');
    const page = await context.newPage();
    const noOverflow = async () => assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth)), 0);
    await page.goto(base + '/tehlikeli-maddeler/yeni', { waitUntil: 'domcontentloaded' });
    await noOverflow();
    if (width === 390) {
      await page.locator('[name="name"]').fill('Mobil Test Kimyasalı');
      await page.locator('[name="cas_no"]').fill('67-64-1');
      await page.locator('[name="hazard_classes"][value="Alevlenir"]').check();
      await page.locator('[name="pictogram_codes"][value="GHS02"]').check();
      await page.locator('[name="usage_area"]').fill('Üretim');
      await page.locator('[name="storage_location"]').fill('Kimyasal Dolap A');
      await page.locator('[name="storage_group"]').selectOption({ label: 'Yanıcı' });
      await page.locator('[name="precautions"]').fill('Kıvılcımdan uzak tutun.');
      await page.locator('[name="ppe_requirements"]').fill('Eldiven ve gözlük.');
      await page.locator('[name="first_aid"]').fill('Bol suyla yıkayın.');
      await page.locator('[name="spill_response"]').fill('İnert emici kullanın.');
      await page.locator('[name="initial_quantity"]').fill('5');
      await page.locator('[name="expiry_date"]').fill(isoDate(90));
      await page.locator('[name="sds_revision_date"]').fill(isoDate(0));
      await page.locator('[name="sds_review_due_date"]').fill(isoDate(365));
      const users = await page.locator('[name="responsible_user_id"] option').evaluateAll(options => options.filter(item => item.value).map(item => item.value));
      assert.ok(users.length >= 2);
      await page.locator('[name="responsible_user_id"]').selectOption(users[0]);
      await page.locator('[name="reviewer_user_id"]').selectOption(users[1]);
      await page.locator('[name="sds_revision_no"]').fill('R1');
      await page.locator('[name="sds_file"]').setInputFiles({ name: 'gbf.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 mobile') });
      await page.getByRole('button', { name: 'Madde Kartını Oluştur' }).click();
      await page.waitForURL('**/tehlikeli-maddeler/*');
      assert.match(await page.locator('body').innerText(), /KIM-\d{4}-0001/);
      await noOverflow();
    }
    await page.screenshot({ path: `.tmp-ui-audit/responsive/${width}-hazardous-substances.png`, fullPage: true });
    completed.push(width);
    await context.close();
  }
} finally {
  await browser.close();
}

console.log(JSON.stringify({ completed, failures: [] }, null, 2));
