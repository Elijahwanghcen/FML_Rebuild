// Playwright render fallback: node render.js <url> <out.html> [--headed]
const { chromium } = require('playwright');
(async () => {
  const [url, out, flag] = process.argv.slice(2);
  const browser = await chromium.launch({ headless: flag !== '--headed' });
  const ctx = await browser.newContext({ locale: 'en-US', viewport: { width: 1440, height: 900 },
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36' });
  const page = await ctx.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(3500);
    for (let i = 0; i < 4; i++) { await page.mouse.wheel(0, 2500); await page.waitForTimeout(500); }
    require('fs').writeFileSync(out, await page.content());
  } catch (e) { console.error('ERR', e.message); process.exitCode = 2; }
  await browser.close();
})();
