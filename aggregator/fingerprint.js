// Fingerprint each unique scrape source: detect backend platform + capture JSON/XHR endpoints.
// Usage: NODE_PATH=$(npm root -g) node fingerprint.js <url> <src_id> <out_dir>
// Ported from FML_scraper/austin_leases_units/scraper/scripts/fingerprint.js: watch the page's own XHR/JSON calls to
// find the floor-plan feed when the HTML has no marker (widgets load data after the page opens).
// Writes fingerprints/<src_id>.json with markers, network captures, and candidate pricing links.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 apartment-research/1.0';
let OUT_DIR = path.join(__dirname, '..', 'fingerprints');

const PLATFORM_MARKERS = {
  entrata: [/entrata/i, /prospectportal/i, /myentrata/i],
  realpage: [/realpage/i, /onesite/i, /rpwebservices/i, /g5search/i],
  rentcafe: [/rentcafe/i, /securecafe/i, /yardi/i],
  appfolio: [/appfolio/i],
  funnel: [/funnelleasing/i, /nestiolistings/i],
  knock: [/knockrentals/i],
  peak: [/peakmade/i],
  americancampus: [/americancampus/i],
  landmark: [/landmark-properties/i],
  cardinal: [/cardinalgroup/i],
  greystar: [/greystar/i],
  sightmap: [/sightmap/i],
  engrain: [/engrain/i],
  anyonehome: [/anyonehome/i],
  udr: [/udr\.com/i],
  buildium: [/buildium/i],
  rentmanager: [/rentmanager/i],
  wordpress: [/wp-content/i],
};

(async () => {
  const [url, srcId, outDir] = process.argv.slice(2);
  if (outDir) OUT_DIR = outDir;
  fs.mkdirSync(OUT_DIR, { recursive: true });
  if (!url || !srcId) { console.error('usage: fingerprint.js <url> <src_id>'); process.exit(1); }

  const result = { src_id: srcId, url, final_url: null, platforms: {}, network: [], pricing_links: [], title: null, error: null };
  const prof = process.env.DOM_PROFILE, headed = process.env.DOM_HEADED === '1';
  const opts = { userAgent: UA, viewport: { width: 1440, height: 900 } };
  const browser = prof ? await chromium.launchPersistentContext(prof, { headless: !headed, ...opts }) : await chromium.launch({ headless: !headed });
  const ctx = prof ? browser : await browser.newContext(opts);
  const page = await ctx.newPage();

  const captures = [];
  page.on('response', async (resp) => {
    try {
      const req = resp.request();
      const rt = req.resourceType();
      const ct = (resp.headers()['content-type'] || '');
      if (rt === 'xhr' || rt === 'fetch' || ct.includes('json')) {
        let bodyPreview = '';
        try {
          const body = await resp.text();
          bodyPreview = body.slice(0, 600);
          if (body.length > 200 && /rent|price|bed|bath|floorplan|floor_plan|sqft|unit/i.test(body)) {
            captures.push({ url: resp.url(), method: req.method(), status: resp.status(), ct, len: body.length, interesting: true, preview: body.slice(0, 1500), postData: req.postData() ? req.postData().slice(0, 500) : null });
            return;
          }
        } catch (e) { /* body unavailable */ }
        captures.push({ url: resp.url(), method: req.method(), status: resp.status(), ct, len: bodyPreview.length, interesting: false });
      }
    } catch (e) { /* ignore */ }
  });

  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(6000);
    if (/just a moment|attention required/i.test(await page.title())) await page.waitForTimeout(12000);
    result.final_url = page.url();
    result.title = await page.title();
    const html = await page.content();

    // platform markers in HTML + all network URLs
    const netUrls = captures.map(c => c.url).join('\n');
    const haystack = html + '\n' + netUrls + '\n' + result.final_url;
    for (const [name, pats] of Object.entries(PLATFORM_MARKERS)) {
      const hits = pats.filter(p => p.test(haystack)).length;
      if (hits) result.platforms[name] = hits;
    }

    // candidate pricing/floorplan links
    const links = await page.$$eval('a[href]', as => as.map(a => ({ href: a.href, text: (a.textContent || '').trim().slice(0, 60) })));
    const seen = new Set();
    for (const l of links) {
      if (/floor|plan|price|pricing|rate|avail|lease/i.test(l.href + ' ' + l.text) && !seen.has(l.href)) {
        seen.add(l.href);
        result.pricing_links.push(l);
      }
    }
    result.pricing_links = result.pricing_links.slice(0, 25);

    // Entrata print_r-style embed check
    if (/\[FloorplanId\]|\[floorplan_id\]|print_r|\[MinimumRent\]/i.test(html)) result.platforms.entrata_embed = 1;
    result.html_len = html.length;
    fs.writeFileSync(path.join(OUT_DIR, srcId + '.html'), html);
  } catch (e) {
    result.error = e.message;
  }

  result.network = captures.filter(c => c.interesting).concat(captures.filter(c => !c.interesting).slice(0, 30));
  fs.writeFileSync(path.join(OUT_DIR, srcId + '.json'), JSON.stringify(result, null, 2));
  console.log(srcId, '=>', result.error ? 'ERROR: ' + result.error : Object.keys(result.platforms).join(',') + ' | interesting_endpoints=' + captures.filter(c => c.interesting).length);
  await browser.close();
})();
