import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5067';
const port = new URL(base).port;
const tenant = `http://firma-ui-preview.volkaportal.com:${port}`;
const browser = await chromium.launch({headless:true,channel:'chrome',args:[
 '--host-resolver-rules=MAP firma-ui-preview.volkaportal.com 127.0.0.1', '--no-proxy-server'
]});
const completed=[];const failures=[];
const image=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a4k8AAAAASUVORK5CYII=','base64');
try {
 const manifest=await(await fetch(base+'/__ui/manifest')).json();
 for(const width of [390,768,1024]) {
  const context=await browser.newContext({viewport:{width,height:900},hasTouch:true,isMobile:width<768});
  const page=await context.newPage();page.setDefaultTimeout(15000);
  const run=async(name,task)=>{try{await task();completed.push({width,name});console.log('PASS',width,name);}catch(error){failures.push({width,name,error:error.message});console.log('FAIL',width,name,error.message);}};
  await run('real login, remember me and logout',async()=>{
   await page.goto(base+'/login',{waitUntil:'domcontentloaded'});
   await page.locator('[name="identity"]').fill('superadmin');
   await page.locator('[name="password"]').fill(manifest.preview_password);
   await page.locator('[for="remember_me"]').click();
   assert.ok(await page.locator('[name="remember_me"]').isChecked());
   await page.locator('.login-button').click();
   await page.waitForURL(url=>url.pathname!=='/login',{waitUntil:'domcontentloaded'});
   assert.ok((await context.cookies()).find(cookie=>cookie.name==='session'&&cookie.expires>0));
   await page.getByRole('button',{name:'Menüyü aç'}).click();
   await page.locator('#dashboardSidebar').getByRole('button',{name:'Çıkış',exact:true}).click();
   await page.waitForURL('**/login',{waitUntil:'domcontentloaded'});
  });
  await context.request.get(base+'/__ui/login/department_staff');
  await run('action assignee closure request with evidence upload',async()=>{
   await page.goto(base+'/actions/1',{waitUntil:'domcontentloaded'});
   const note=page.locator('[name="closure_evidence_note"]');
   if(await note.count()===0){assert.match(await page.locator('body').innerText(),/Onay|onay|Kapatma/);return;}
   await note.fill('Mobil aksiyon sorumlusu kapanış kanıtı');
   await page.locator('[name="closure_files"]').setInputFiles({name:'kanit.png',mimeType:'image/png',buffer:image});
   await page.getByRole('button',{name:'Kapatma Onayı Gönder',exact:true}).click();
   await page.waitForLoadState('domcontentloaded');
   assert.match(await page.locator('body').innerText(),/Mobil aksiyon sorumlusu/);
  });
  await context.request.get(base+'/__ui/login/management_representative');
  await run('suggestion scoring form submission',async()=>{
   await page.goto(base+'/oneri-sikayet/oneri/1',{waitUntil:'domcontentloaded'});
   const ratings=page.locator('select[name^="rating_"]');
   assert.equal(await ratings.count(),3);
   for(const rating of await ratings.all())await rating.selectOption('5');
   await page.locator('[name="evaluation_comment"]').fill('Mobil ve tablet değerlendirmesi');
   await page.getByRole('button',{name:'Değerlendirmeyi Kaydet',exact:true}).click();
   await page.waitForLoadState('domcontentloaded');
   assert.match(await page.locator('.suggestion-score-list-v2').innerText(),/Değerlendirme Yaptı/);
  });
  await run('assigned dynamic form draft keeps selected values',async()=>{
   await page.goto(base+'/dinamik-formlar/atama/1/doldur',{waitUntil:'domcontentloaded'});
   await page.locator('select[name^="field_"]').first().selectOption('Evet');
   await page.locator('textarea[name^="field_"]').fill(`Mobil form notu ${width}`);
   await page.getByRole('button',{name:'Taslak Kaydet',exact:true}).click();
   await page.waitForLoadState('domcontentloaded');
   assert.equal(await page.locator('select[name^="field_"]').first().inputValue(),'Evet');
   assert.match(await page.locator('textarea[name^="field_"]').inputValue(),/Mobil form notu/);
  });
  await run('inspection form draft with results',async()=>{
   await page.goto(base+'/saha-kontrol/1/uygula',{waitUntil:'domcontentloaded'});
   await page.locator('select[name^="answer_"]').selectOption('Evet');
   for(const result of await page.locator('select[name^="result_"]').all())await result.selectOption('Uygun');
   await page.getByRole('button',{name:'Taslak Kaydet',exact:true}).click();
   await page.waitForLoadState('domcontentloaded');
   assert.equal(await page.locator('select[name^="answer_"]').inputValue(),'Evet');
  });
  await context.request.get(base+'/__ui/login/department_staff');
  await run('document reader acknowledgement and revision request',async()=>{
   await page.goto(base+'/documents/1',{waitUntil:'domcontentloaded'});
   const acknowledge=page.getByRole('button',{name:'Okudum ve Onayladım',exact:true});
   if(await acknowledge.count()) {await acknowledge.click();await page.waitForLoadState('domcontentloaded');}
   assert.match(await page.locator('.documents-ack-card').innerText(),/onaylandı/);
   await page.getByRole('button',{name:'Doküman işlemleri',exact:true}).click();
   await page.getByRole('link',{name:'Revizyon Talep Et',exact:true}).first().click();
   await page.locator('[name="explanation"]').fill(`Mobil doküman revizyon talebi ${width}`);
   await page.locator('[name="document_files"]').setInputFiles({name:'revizyon.png',mimeType:'image/png',buffer:image});
   await page.getByRole('button',{name:'Talebi Gönder',exact:true}).click();
   await page.waitForLoadState('domcontentloaded');
   assert.match(await page.locator('body').innerText(),/talebi|Talebi|talebiniz|Talebiniz/);
  });
  const publicContext=await browser.newContext({viewport:{width,height:900},hasTouch:true,isMobile:width<768});
  const publicPage=await publicContext.newPage();publicPage.setDefaultTimeout(15000);
  await run('anonymous complaint verification and tracking message',async()=>{
   const response=await publicPage.goto(tenant+'/musteri-portali',{waitUntil:'domcontentloaded'});
   assert.equal(response.status(),200);
   assert.equal(await publicPage.locator('[name="contact_phone"]').getAttribute('type'),'tel');
   await publicPage.locator('[name="record_type"]').selectOption('Şikayet');
   for(const[name,value]of Object.entries({customer_name:'Mobil Müşteri',contact_name:'Ayşe Yılmaz',contact_email:`mobil${width}@example.test`,contact_phone:'0555 111 22 33',customer_reference:`MUS-${width}`,product_reference:'PRJ-001',subject:'Mobil kalite bildirimi',description:'Ürün yüzey kontrolü için mobil geri bildirim.'}))await publicPage.locator(`[name="${name}"]`).fill(value);
   await publicPage.locator('[name="consent"]').check();
   await publicPage.locator('button[type="submit"]').click();
   const verify=publicPage.locator('a[href*="/musteri-portali/dogrula/"]');
   await verify.waitFor();
   // Production tenant links have no preview port; retain the test-only loopback port.
   await publicPage.goto(tenant+new URL(await verify.getAttribute('href')).pathname,{waitUntil:'domcontentloaded'});
   await publicPage.waitForURL('**/musteri-portali/takip/**',{waitUntil:'domcontentloaded'});
   await publicPage.locator('[name="message"]').fill(`Mobil takip mesajı ${width}`);
   await publicPage.getByRole('button',{name:'Mesajı Gönder',exact:true}).click();
   await publicPage.waitForLoadState('domcontentloaded');
   assert.match(await publicPage.locator('body').innerText(),/Mobil takip mesajı/);
   assert.equal(await publicPage.evaluate(()=>Math.max(0,document.documentElement.scrollWidth-innerWidth)),0);
   await publicPage.screenshot({path:`.tmp-ui-audit/responsive/${width}-public-tracking.png`,fullPage:true});
  });
  await publicContext.close();await context.close();
 }
}finally{await browser.close();await fs.writeFile('.tmp-ui-audit/responsive/workflows.json',JSON.stringify({completed,failures},null,2));}
console.log(JSON.stringify({completed:completed.length,failures},null,2));
if(failures.length)process.exitCode=1;
