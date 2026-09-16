import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5067';
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const completed = [];
const failures = [];
try {
 for (const width of [360, 820, 1024]) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch:true, isMobile:width<768 });
  await context.request.get(base + '/__ui/login/super_admin');
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  const check = async (name, task) => {
   try { await task(); completed.push({width,name}); console.log('PASS',width,name); }
   catch (error) { failures.push({width,name,error:error.message}); console.log('FAIL',width,name,error.message); }
  };
  await check('dynamic table lifecycle, original input and sorting control',async()=>{
   await page.goto(base + '/insan-kaynaklari/personel-listesi',{waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>document.getElementById('dashboardMainContent').dataset.responsiveReady==='true');
   await page.evaluate(()=>{
    const wrapper=document.createElement('div');wrapper.className='table-responsive';
    wrapper.innerHTML='<table id="probe"><thead><tr><th>Ad</th><th>Puan <button type="button" title="Sırala">↑</button></th></tr></thead><tbody><tr><td>Türkçe</td><td><input value="17" aria-label="Deneme puanı"></td></tr><tr><td colspan="2"><div>Detay</div></td></tr></tbody></table>';
    document.getElementById('dashboardMainContent').append(wrapper);
    window.probeInput=wrapper.querySelector('input');
    window.probeClicks=0;wrapper.querySelector('button').addEventListener('click',()=>window.probeClicks++);
   });
   await page.waitForFunction(()=>document.getElementById('probe').classList.contains('vp-responsive-table'));
   const group=page.locator('#probe').locator('..').locator('..').locator('.vp-list-view-controls').last();
   await group.getByRole('button',{name:'Liste görünümü',exact:true}).click();
   await page.getByRole('textbox',{name:'Deneme puanı'}).fill('29');
   await page.locator('#probe [title="Sırala"]').click();
   await group.getByRole('button',{name:'Tablo görünümü',exact:true}).click();
   assert.deepEqual(await page.evaluate(()=>({same:probeInput===document.querySelector('#probe input'),value:probeInput.value,clicks:probeClicks})),{same:true,value:'29',clicks:1});
   assert.equal(await page.locator('#probe thead').evaluate(e=>getComputedStyle(e).display),'table-header-group');
   await page.evaluate(()=>document.querySelector('#probe th').textContent='İsim Soyisim');
   await page.waitForFunction(()=>document.querySelector('#probe tbody td').dataset.label==='İsim Soyisim');
   await page.evaluate(()=>{const table=document.getElementById('probe');table.classList.add('dof-dashboard-table');table.tBodies[0].rows[0].cells[0].colSpan=2;});
   await page.waitForFunction(()=>document.getElementById('probe').classList.contains('vp-scroll-table'));
   assert.equal(await page.locator('#probe thead').evaluate(e=>getComputedStyle(e).display),'table-header-group');
   await page.evaluate(()=>document.getElementById('probe').tBodies[0].rows[0].cells[0].colSpan=1);
   await page.waitForFunction(()=>document.getElementById('probe').classList.contains('vp-responsive-table'));
   await page.evaluate(()=>document.querySelector('#probe tbody tr td').remove());
   await page.waitForFunction(()=>!document.getElementById('probe').classList.contains('vp-responsive-table'));
   await page.evaluate(()=>{const cell=document.createElement('td');cell.textContent='Yeni';document.querySelector('#probe tbody tr').prepend(cell);});
   await page.waitForFunction(()=>document.getElementById('probe').classList.contains('vp-responsive-table'));
   await page.evaluate(()=>document.getElementById('probe').remove());
   await page.waitForFunction(()=>document.querySelectorAll('.vp-list-view-controls').length===1);
  });
  await check('document/IF/tasks actual table-mode reset',async()=>{
   for (const url of ['/documents/list','/dofs','/uzerime-atananlar']) {
    await page.goto(base+url,{waitUntil:'domcontentloaded'});
    const group=page.locator('.vp-list-view-controls').first();
    await group.getByRole('button',{name:'Tablo görünümü',exact:true}).click();
    assert.equal(await page.locator('.vp-responsive-table thead').first().evaluate(e=>getComputedStyle(e).display),'table-header-group');
    if(url==='/documents/list') {
     assert.ok(await page.locator('.vp-responsive-table tbody tr').first().evaluate(el=>el.getBoundingClientRect().height<180));
     await page.screenshot({path:`.tmp-ui-audit/responsive/${width}-documents-table-final.png`,fullPage:true});
    }
    await group.getByRole('button',{name:'Liste görünümü',exact:true}).click();
   }
  });
  await check('menu scroll, all submenus and reachable logout',async()=>{
   await page.goto(base+'/',{waitUntil:'domcontentloaded'});
   await page.getByRole('button',{name:'Menüyü aç'}).click();
   for(const button of await page.locator('#dashboardSidebar .dashboard-nav-toggle').all()) {
    await button.scrollIntoViewIfNeeded();
    if(await button.getAttribute('aria-expanded')==='false') await button.click();
   }
   const logout=page.locator('#dashboardSidebar').getByRole('button',{name:'Çıkış',exact:true});
   await logout.scrollIntoViewIfNeeded();
   assert.ok(await logout.evaluate(el=>{const b=el.getBoundingClientRect();return b.top>=0&&b.bottom<=innerHeight;}));
   await page.screenshot({path:`.tmp-ui-audit/responsive/${width}-menu-final.png`});
   await page.locator('#dashboardSidebar').getByRole('button',{name:'Kapat',exact:true}).click();
   await page.locator('.offcanvas-backdrop').waitFor({state:'detached'});
  });
  await check('concrete expand and save changed/deleted measurements',async()=>{
   await page.goto(base+'/kalite-deneyleri/beton-deneyi',{waitUntil:'domcontentloaded'});
   await page.locator('.table-disclosure-toggle').first().click();
   await page.locator('.concrete-row-detail-panel.show').waitFor();
   assert.equal(await page.locator('.concrete-action-buttons .btn-primary span').evaluate(el=>getComputedStyle(el).color),'rgb(255, 255, 255)');
   await page.waitForTimeout(250);
   assert.ok(await page.locator('.concrete-row-detail-panel').evaluate(el=>el.getBoundingClientRect().bottom<=el.closest('td').getBoundingClientRect().bottom+1));
   await page.screenshot({path:`.tmp-ui-audit/responsive/${width}-concrete-final.png`,fullPage:true});
   await page.getByRole('link',{name:'Düzenle',exact:true}).click();
   await page.locator('[name="strength_2_day"]').fill('18,5');
   await page.locator('[name="strength_7_day"]').fill('');
   await page.getByRole('button',{name:'Değişiklikleri Kaydet',exact:true}).click();
   await page.waitForURL('**/kalite-deneyleri/beton-deneyi');
   await page.locator('.table-disclosure-toggle').first().click();
   await page.locator('.concrete-row-detail-panel.show').waitFor();
   assert.match(await page.locator('.concrete-strength-metric').first().innerText(),/18,5/);
  });
  await check('personnel create, edit and report download',async()=>{
   await page.goto(base+'/insan-kaynaklari/personel-listesi/yeni',{waitUntil:'domcontentloaded'});
   const name=`Mobil Çalışan ${width}`;
   await page.locator('[name="full_name"]').fill(name);
   await page.locator('[name="phone"]').fill(`0532000${width}`);
   await page.locator('[name="title"]').fill('Kalite Sorumlusu');
   await page.locator('.app-form-actions button[type="submit"]').click();
   await page.waitForURL('**/personel-listesi');
   const row=page.locator('tr').filter({hasText:name});
   await row.getByRole('link',{name:'Düzenle',exact:true}).click();
   await page.locator('[name="title"]').fill('Güncel Kalite Sorumlusu');
   await page.locator('.app-form-actions button[type="submit"]').click();
   await page.waitForURL('**/personel-listesi');
   assert.match(await page.locator('tr').filter({hasText:name}).innerText(),/Güncel/);
   const download=page.waitForEvent('download');
   await page.getByRole('link',{name:'Rapor İndir',exact:true}).click();
   assert.match((await download).suggestedFilename(),/\.xlsx$/);
  });
  await check('audit dirty-answer guard and draft persistence',async()=>{
   await page.goto(base+'/ic-denetim/1/soru/1',{waitUntil:'domcontentloaded'});
   const note=page.locator('[data-audit-count]');
   if(await note.isDisabled()) throw new Error('Preview account is an observer, operator fixture required');
   await note.fill(`Kaydedilmemiş mobil bulgu ${width}`);
   let warning='';
   page.once('dialog', async dialog=>{warning=dialog.message();await dialog.accept();});
   await page.getByRole('button',{name:'Denetimi Bitir',exact:true}).click();
   assert.match(warning,/Kaydedilmemiş/);
   await page.getByRole('button',{name:'Taslak Kaydet',exact:true}).click();
   await page.waitForLoadState('domcontentloaded');
   assert.match(await page.locator('[data-audit-count]').inputValue(),/mobil bulgu/);
   await page.getByRole('button',{name:'Kaydet ve Sonraki Soru',exact:true}).click();
  });
  await context.close();
 }
} finally {await browser.close();await fs.writeFile('.tmp-ui-audit/responsive/interactions.json',JSON.stringify({completed,failures},null,2));}
console.log(JSON.stringify({completed:completed.length,failures},null,2));
if(failures.length)process.exitCode=1;
