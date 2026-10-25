// Local HTML smoke test. Requires Playwright; no download, server, or network.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

const args = process.argv.slice(2);
const input = args.shift();
const options = {};
while (args.length) { const key = args.shift(); if (!key?.startsWith('--') || !args.length) throw new Error('Expected --option value'); options[key.slice(2)] = args.shift(); }
if (!input || !options.output) throw new Error('Usage: node qa_browser.mjs index.html --output qa [--modules /path/node_modules] [--browser /path/browser]');
const requireFrom = options.modules ? createRequire(path.join(path.resolve(options.modules), '__paper_qa__.cjs')) : createRequire(import.meta.url);
const {chromium} = requireFrom('playwright');
const output = path.resolve(options.output);
fs.mkdirSync(output, {recursive:true});
const browser = await chromium.launch({headless:true, ...(options.browser ? {executablePath:options.browser} : {})});
const report = {scope:'Browser structure and interaction; screenshots require visual inspection', checks:[], errors:[], screenshots:[]};
try {
  for (const viewport of [{name:'desktop', width:1440,height:1000},{name:'mobile',width:390,height:844}]) {
    const context = await browser.newContext({viewport:{width:viewport.width,height:viewport.height}, reducedMotion:'reduce'});
    const external = [];
    await context.route(/^https?:/, route => {external.push(route.request().url()); return route.abort();});
    const page = await context.newPage();
    page.on('pageerror', e => report.errors.push(viewport.name + ': ' + e.message));
    await page.goto(pathToFileURL(path.resolve(input)).href, {waitUntil:'load'});
    // Force all lazy images to load, without changing screenshots' final scroll.
    await page.evaluate(async () => {const images=[...document.images].filter(i=>i.getAttribute('src')); await Promise.all(images.map(async i=>{i.loading='eager'; try{await i.decode();}catch{}}));});
    const state = await page.evaluate(() => ({overflow:document.documentElement.scrollWidth>innerWidth+2, missingImages:[...document.images].filter(i=>i.getAttribute('src')&&(!i.complete||i.naturalWidth===0)).map(i=>i.getAttribute('src')), headings:document.querySelectorAll('h2').length}));
    if (state.overflow || state.missingImages.length || external.length) report.errors.push(`${viewport.name}: ${JSON.stringify({state,external})}`);
    report.checks.push({viewport:viewport.name, ...state, blockedExternalRequests:external});
    await page.screenshot({path:path.join(output,viewport.name+'-top.png')});
    report.screenshots.push(viewport.name+'-top.png');
    for(const anchor of ['method','experiment']) {
      const section=page.locator('#'+anchor);
      if(await section.count()) {await section.evaluate(e=>e.scrollIntoView({block:'start',behavior:'instant'})); await page.screenshot({path:path.join(output,viewport.name+'-'+anchor+'.png')}); report.screenshots.push(viewport.name+'-'+anchor+'.png');}
    }
    const zoom = page.locator('a.zoom').first();
    if(await zoom.count()) {
      await zoom.click();
      if(!await page.locator('#image-dialog').evaluate(d=>d.open)) report.errors.push(viewport.name+': image dialog failed');
      const originalSize=page.locator('#image-size');
      if(await originalSize.count()) {
        await page.locator('#image-large').evaluate(async img=>{await img.decode();});
        await originalSize.click();
        const actual=await page.locator('#image-large').evaluate(img=>({rendered:img.getBoundingClientRect().width,natural:img.naturalWidth}));
        if(Math.abs(actual.rendered-actual.natural)>1) report.errors.push(viewport.name+': original-size image failed');
        if(viewport.name==='mobile') {await page.screenshot({path:path.join(output,'mobile-image-original.png')});report.screenshots.push('mobile-image-original.png');}
        await originalSize.click();
      }
      await page.keyboard.press('Escape');
      if(await page.locator('#image-dialog').evaluate(d=>d.open)) report.errors.push(viewport.name+': Escape failed');
      const restored=await zoom.evaluate(e=>document.activeElement===e);
      if(!restored) report.errors.push(viewport.name+': focus did not return after lightbox');
    }
    const size = page.locator('#font-toggle');
    if(await size.count()) {await size.click(); if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)) report.errors.push(viewport.name+': large font overflow');}
    await page.locator('.toc a').first().click();
    if(!new URL(page.url()).hash) report.errors.push(viewport.name+': anchor navigation failed');
    await context.close();
  }
  const nojs = await browser.newContext({javaScriptEnabled:false,viewport:{width:1000,height:800}});
  await nojs.route(/^https?:/,r=>r.abort());
  const page = await nojs.newPage();
  await page.goto(pathToFileURL(path.resolve(input)).href);
  const textLength=await page.locator('main').innerText().then(s=>s.length);
  report.checks.push({javascriptDisabled:true,mainTextCharacters:textLength});
  if(textLength<500) report.errors.push('Main content missing without JavaScript');
  await nojs.close();
} finally {await browser.close();}
report.passed = report.errors.length===0;
fs.writeFileSync(path.join(output,'browser-report.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
if(!report.passed) process.exitCode=1;
