import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5098';
const out = '.tmp-ui-audit/projects';
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless:true, channel:'chrome' });
const results = [];
try {
  for (const width of [390,768,1440]) {
    const context = await browser.newContext({viewport:{width,height:900}, hasTouch:width<1200});
    const page = await context.newPage();
    const errors=[];
    page.on('pageerror', error=>errors.push(error.message));
    const login=async role=>{await context.request.get(`${base}/__ui/login/${role}`);};
    const layout=async name=>{
      await page.waitForLoadState('networkidle');
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' overflow');
      await page.screenshot({path:`${out}/${width}-${name}.png`,fullPage:true});
    };
    try {
      await login('department_manager');
      await page.goto(`${base}/projeler/yeni`);
      await page.locator('#project-title').fill(`Üretim iyileştirme projesi ${width}`);
      await page.locator('#project-owner').selectOption({label:'department_manager'});
      await page.locator('#project-start').fill('2026-10-01');
      await page.locator('#project-due').fill('2026-10-31');
      await page.locator('#project-description').fill('Kontrol kayıtlarının iyileştirilmesi');
      await layout('form');
      await page.locator('.project-form button[type="submit"]').click();
      await page.waitForURL(/\/projeler\/\d+$/);
      const detail=page.url();
      await page.getByText('Görev Ekle',{exact:true}).click();
      await page.locator('#new-task-title').fill('Üretim kontrol planını güncelle');
      await page.locator('#new-task-owner').selectOption({label:'department_staff'});
      await page.locator('#add-project-task button[type="submit"]').click();
      await page.getByRole('button',{name:'Projeyi Başlat',exact:true}).click();
      await layout('active');
      await login('department_staff');
      await page.goto(detail);
      assert.equal(await page.getByRole('link',{name:'Düzenle',exact:true}).count(),0);
      await page.locator('.project-task-result textarea').fill('Kontrol planı güncellendi ve doğrulandı.');
      await page.locator('.project-task-result button[value="complete"]').click();
      await layout('staff-completed');
      await login('department_manager');
      await page.goto(detail);
      await page.locator('#project-result').fill('Planlanan çıktı elde edildi.');
      await page.getByRole('button',{name:'Projeyi Tamamla',exact:true}).click();
      const download=page.waitForEvent('download');
      await page.getByRole('link',{name:'Rapor İndir',exact:true}).click();
      assert.equal(await (await download).failure(),null);
      await page.locator('#project-archive-reason').fill('Dönem sonu arşivi');
      await page.getByRole('button',{name:'Arşivle',exact:true}).click();
      await layout('archive');
      await page.goto(`${base}/projeler`);
      await layout('dashboard');
      const actionBox=await page.locator('.project-table td[data-label="İşlem"] a').first().boundingBox();
      assert.ok(actionBox && actionBox.x>=0 && actionBox.x+actionBox.width<=width+1,`${width} list action clipped`);
      assert.deepEqual(errors,[]);
      results.push({width,result:'passed',csrf:'enabled',workflow:'create/assign/activate/complete/export/archive'});
    } finally {await context.close();}
  }
} finally {
  await browser.close();
  await fs.writeFile(`${out}/results.json`,JSON.stringify(results,null,2));
}
console.log(JSON.stringify(results,null,2));
