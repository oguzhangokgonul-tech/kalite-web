import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5118';
const output = '.tmp-ui-audit/user-profile';
await fs.mkdir(output, {recursive:true});
const browser = await chromium.launch({channel:'chrome', headless:true, args:['--disable-gpu']});
try {
  for (const width of [390,768,1440]) {
    const context = await browser.newContext({viewport:{width,height:960}});
    await context.request.get(base+'/__ui/login/super_admin');
    const page = await context.newPage();
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base+'/users');
    const row = page.locator('tbody tr').filter({hasText:'preview-department_staff'});
    const edit = await row.locator('a[href$="/edit"]').getAttribute('href');
    await page.goto(base+edit);
    const title = `Kalite Sorumlusu ${width}`;
    await page.locator('#title').fill(title);
    await page.locator('#email').fill(`profile-${width}@example.com`);
    await page.getByRole('button',{name:'Kaydet',exact:true}).click();
    await page.waitForURL(base+'/users');
    assert.ok((await page.locator('tbody').innerText()).includes(title));
    await page.goto(base+edit);
    assert.equal(await page.locator('#title').inputValue(),title);
    assert.equal(await page.locator('#email').inputValue(),`profile-${width}@example.com`);
    await page.locator('#title').fill('');
    await page.getByRole('button',{name:'Kaydet',exact:true}).click();
    await page.waitForURL(base+'/users');
    await page.goto(base+edit);
    assert.equal(await page.locator('#title').inputValue(),'');
    await page.locator('#title').fill(title);
    await page.locator('#username').fill('superadmin');
    // Reserved username is forbidden; use an existing ordinary username to trigger validation.
    await page.locator('#username').fill('preview-viewer');
    await page.getByRole('button',{name:'Kaydet',exact:true}).click();
    await page.waitForLoadState('domcontentloaded');
    assert.equal(await page.locator('#title').inputValue(),title);
    assert.equal(await page.locator('#username').inputValue(),'preview-viewer');
    assert.equal(await page.locator('#password').inputValue(),'');
    assert.ok(await page.locator('.alert-danger').isVisible());
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth),0);
    await page.screenshot({path:`${output}/${width}-validation.png`,fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('PASS',width,'save/readback/clear/validation/form-fit');
    await context.close();
  }
} finally {await browser.close();}
