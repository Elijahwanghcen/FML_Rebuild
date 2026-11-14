// Reddit corpus fetch through a real, user-logged-in browser window (Reddit blocks every unattended route:
// script 403, headless -> "prove your humanity", .json endpoints 403 even when logged in).
// node reddit_fetch.js <out.json> <subreddit,subreddit> <query|query|...> [maxThreads]
// First run: a Chrome window opens on the login page; the USER logs in (profile persists in ~/.fml_reddit_profile).
// The script then reads old.reddit.com search pages + threads as rendered HTML, slowly.
const { chromium } = require('playwright');
const fs = require('fs'), os = require('os'), path = require('path');
(async () => {
  const [out, subs, queries, maxT] = process.argv.slice(2);
  const ctx = await chromium.launchPersistentContext(path.join(os.homedir(), '.fml_reddit_profile'),
    { headless: false, channel: 'chrome', viewport: { width: 1100, height: 800 } });
  const page = ctx.pages()[0] || await ctx.newPage();
  const go = async (u) => { await page.goto(u, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {}); await page.waitForTimeout(1800); };
  const logged = async () => (await ctx.cookies('https://www.reddit.com')).some(c => c.name === 'reddit_session');
  if (!(await logged())) {
    await go('https://www.reddit.com/login/');
    for (let i = 0; i < 180 && !(await logged()); i++) await page.waitForTimeout(5000);
    if (!(await logged())) { console.log('NOT_LOGGED_IN'); await ctx.close(); process.exit(3); }
  }
  console.log('LOGGED_IN');
  const posts = fs.existsSync(out) ? Object.fromEntries(JSON.parse(fs.readFileSync(out)).map(p => [p.id, p])) : {};
  for (const sub of subs.split(',')) for (const q of queries.split('|')) {
    await go(`https://old.reddit.com/r/${sub}/search?q=${encodeURIComponent(q)}&restrict_sr=on&sort=relevance&t=all&limit=100`);
    const res = await page.evaluate(() => [...document.querySelectorAll('.search-result-link')].map(d => {
      const a = d.querySelector('a.search-title'); const c = d.querySelector('a.search-comments');
      return a && { title: a.textContent, url: a.href, n: parseInt((c && c.textContent || '0').replace(/[^0-9]/g, '')) || 0,
        body: (d.querySelector('.search-result-body') || {}).textContent || '', time: (d.querySelector('time') || {}).dateTime || '' };
    }).filter(Boolean));
    for (const r of res) { const m = r.url.match(/comments\/(\w+)/); if (!m) continue; posts[m[1]] = posts[m[1]] || { id: m[1], sub, ...r, q: [] }; posts[m[1]].q.push(q); }
    console.log(sub, '|', q, '|', res.length, 'total', Object.keys(posts).length, res.length ? '' : (await page.title()));
  }
  const top = Object.values(posts).filter(p => !p.comments).sort((a, b) => b.n - a.n).slice(0, parseInt(maxT || '120'));
  for (const p of top) {
    await go(p.url.replace('www.reddit.com', 'old.reddit.com') + '?limit=500');
    const d = await page.evaluate(() => ({ body: (document.querySelector('.expando .usertext-body') || {}).innerText || '',
      comments: [...document.querySelectorAll('.commentarea .usertext-body')].map(e => e.innerText.trim()).filter(Boolean) }));
    p.body = d.body || p.body; p.comments = d.comments;
    fs.writeFileSync(out, JSON.stringify(Object.values(posts)));
  }
  fs.writeFileSync(out, JSON.stringify(Object.values(posts)));
  console.log('DONE', Object.keys(posts).length);
  await ctx.close();
})();
