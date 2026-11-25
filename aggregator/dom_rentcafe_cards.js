// Rebuild-owned DOM extractor (not synced from FML_Data; dom_extract.js must stay a byte copy).
// RENTCafe "oculus" theme (100 Park, Dwell at 1600, Southgate Village, Sundance; found 2026-11-25): the page has no
// window.ysi.floorplansList and no fee buttons, so FML_Data's rentcafe_ysi returns nothing. Each plan card's links
// carry data-floorplan-name / -size (beds) / -sqft ("696 -711") / -price ("1530 -1700").
// Plain HTTP gets a 403 bot wall; headless Chromium loads the page. Same launch options as dom_extract.js
// (DOM_PROFILE / DOM_HEADED / DOM_CHALLENGE_WAIT_S). Usage: node dom_rentcafe_cards.js <backend> <url> [paramsJSON]
// Prints one JSON line: {"status": ..., "rows": [...]}.
const { chromium } = require('playwright');

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';
const WALL = /just a moment|attention required|access denied/i;

function row(kw) {
  return Object.assign({
    unit_or_floorplan_label: '', beds: '', baths: '', sqft: '', base_rent: '', total_price_with_mandatory_fees: '',
    price_basis: '', concessions_raw: '', concessions_type: '', concessions_value: '', availability: '',
    layout_image_url: '', price_image_url: '', concessions_image_url: '', price_status: 'listed',
  }, kw);
}

(async () => {
  const [, url] = process.argv.slice(2);
  const prof = process.env.DOM_PROFILE;
  const headed = process.env.DOM_HEADED === '1';
  const opts = { userAgent: UA, viewport: { width: 1440, height: 900 } };
  const browser = prof
    ? await chromium.launchPersistentContext(prof, { headless: !headed, ...opts })
    : await chromium.launch({ headless: !headed });
  const ctx = prof ? browser : await browser.newContext(opts);
  const page = await ctx.newPage();
  let out = { status: 'ok', rows: [] };
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    if (WALL.test(await page.title())) {
      const ws = parseInt(process.env.DOM_CHALLENGE_WAIT_S || (headed ? '170' : '12'), 10);
      for (let w = 0; w < ws && WALL.test(await page.title()); w += 2) await page.waitForTimeout(2000);
      if (WALL.test(await page.title())) {
        console.log(JSON.stringify({ status: 'blocked_bot_wall', rows: [] }));
        await browser.close();
        return;
      }
    }
    try { await page.waitForSelector('a[data-floorplan-name]', { timeout: 20000 }); } catch (e) { /* none */ }
    await page.waitForTimeout(1500);
    const cards = await page.evaluate(() => {
      const seen = new Set();
      const res = [];
      const nudge = document.querySelector('.nudgeTop-title, [id^="nudgeTop-title"]');
      const banner = nudge ? nudge.textContent.replace(/\s+/g, ' ').trim() : '';
      document.querySelectorAll('a[data-floorplan-name][data-floorplan-price]').forEach((a) => {
        const name = (a.getAttribute('data-floorplan-name') || '').trim();
        if (!name || seen.has(name)) return;
        seen.add(name);
        const card = a.closest('.card') || a.closest('.fp-container');
        const txt = ((card || a).textContent || '').replace(/\s+/g, ' ');
        const img = card ? card.querySelector('img') : null;
        res.push({
          name,
          price: a.getAttribute('data-floorplan-price') || '',
          beds: a.getAttribute('data-floorplan-size') || '',
          sqft: a.getAttribute('data-floorplan-sqft') || '',
          baths: (txt.match(/([\d.]+)\s*Bath/i) || [])[1] || '',
          avail: (txt.match(/(\d+)\s*Available/i) || [])[1] || '',
          img: img ? (img.getAttribute('data-src') || img.getAttribute('data-original') || img.src || '') : '',
          banner,
        });
      });
      return res;
    });
    for (const c of cards) {
      const [lo, hi] = c.price.split('-').map((x) => parseFloat(x.replace(/[^\d.]/g, ''))).filter((x) => !Number.isNaN(x));
      const priced = lo !== undefined && lo >= 100;
      out.rows.push(row({
        unit_or_floorplan_label: c.name, beds: c.beds, baths: c.baths, sqft: c.sqft.split('-')[0].trim(),
        base_rent: priced ? lo : '', price_basis: priced ? 'base' : '',
        concessions_raw: c.banner,
        availability: [c.avail ? `${c.avail} available` : '', hi && hi !== lo ? `up to $${hi}` : ''].filter(Boolean).join(' — '),
        layout_image_url: c.img && !c.img.startsWith('data:') ? c.img : '',
        price_status: priced ? 'listed' : 'not_publicly_listed',
      }));
    }
    if (!out.rows.length) out.status = 'no_rows';
  } catch (e) {
    out = { status: `error: ${String(e.message || e).slice(0, 200)}`, rows: [] };
  }
  console.log(JSON.stringify(out));
  await browser.close();
})();
