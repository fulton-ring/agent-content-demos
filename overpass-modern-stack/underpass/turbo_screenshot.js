// Opens overpass-turbo.eu with a query whose {{data:overpass,server=...}} points at the local Underpass-API.
const { chromium } = require('playwright');
(async () => {
  const [server, out] = process.argv.slice(2);
  const query = `{{data:overpass,server=${server}}}
[out:json][timeout:25];
area["name"="District of Columbia"]["admin_level"="4"]->.dc;
(
  nwr["power"="substation"](area.dc);
  way["power"="line"](area.dc);
);
out body;
>;
out skel qt;`;
  const browser = await chromium.launch({ args: ['--proxy-server=' + process.env.HTTPS_PROXY, '--proxy-bypass-list=127.0.0.1;localhost'] });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, ignoreHTTPSErrors: true });
  const calls = [];
  page.on('request', r => { if (r.url().includes('interpreter')) calls.push(r.url().slice(0, 60)); });
  page.on('response', r => { if (r.url().includes('interpreter')) calls.push(`status ${r.status()}`); });
  await page.goto('https://overpass-turbo.eu/?C=38.905;-77.02;13&R&Q=' + encodeURIComponent(query), { waitUntil: 'networkidle', timeout: 120000 });
  await page.waitForTimeout(15000);
  const status = await page.evaluate(() => document.querySelector('#map .stats, .stats')?.textContent || '');
  console.log(JSON.stringify({ calls, status }));
  await page.screenshot({ path: out });
  await browser.close();
})();
