// DOM extractors for backends that need a real browser (Cloudflare-fronted or client-rendered).
// Usage: NODE_PATH=$(npm root -g) node dom_extract.js <backend> <url>
// Prints a JSON array of partial rows to stdout. run.py fills property-level fields.
// Row fields produced here: unit_or_floorplan_label, beds, baths, sqft, base_rent,
// total_price_with_mandatory_fees, price_basis, concessions_raw, availability,
// layout_image_url, price_image_url, concessions_image_url, price_status
const { chromium } = require('playwright');

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';

function num(s) {
  if (s === null || s === undefined) return null;
  const m = String(s).replace(/,/g, '').match(/\d+(?:\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}

// Injected into the page alongside each parser (parsers run via page.evaluate and
// must stay self-contained; this is prepended to their scope at call time).
// Picks the best image URL: highest-res srcset > data-src (lazy) > src; absolute.
const IMG_HELPER = `const imgUrl = (im) => {
  if (!im) return '';
  let u = '';
  const ss = im.getAttribute('srcset') || im.getAttribute('data-srcset') || '';
  if (ss) {
    let bw = -1;
    ss.split(',').forEach((c) => {
      const p = c.trim().split(/\\s+/);
      const w = p[1] ? parseFloat(p[1]) : 0;
      if (w > bw) { bw = w; u = p[0]; }
    });
  }
  if (!u) u = im.getAttribute('data-src') || im.getAttribute('data-lazy-src') || '';
  if (!u) u = im.currentSrc || im.getAttribute('src') || '';
  if (u.startsWith('data:')) u = im.getAttribute('data-src') || im.getAttribute('data-lazy-src') || im.currentSrc || '';
  try { return u ? new URL(u, document.baseURI).href : ''; } catch (e) { return u; }
};`;

// ---- per-backend parse functions (run in page context; must be self-contained) ----

const PARSERS = {
  // Entrata ProspectPortal: variant A (.fp-card + options table) and variant B (.fp-data-wrapper radio rows)
  entrata_pp: () => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    // Entrata "splash" promo modal — usually an image-only popup (e.g. "$500 gift card, waived app fee").
    // Text isn't in the DOM, so record alt + image URL verbatim for the analyst.
    let splash = '';
    let splashImgUrl = '';
    const splashImg = document.querySelector('.splash-image-modal img, .modal-container.js-modal img');
    const splashIsLoader = splashImg && (/loader/i.test(splashImg.src || '') || /^loading\.{0,3}$/i.test((splashImg.alt || '').trim()));
    if (splashImg && !splashIsLoader) {
      const splashTxt = txt(document.querySelector('.splash-image-modal .modal-content'));
      splash = `promo splash popup${splashTxt && splashTxt.length < 200 ? ': ' + splashTxt : ''} [alt: ${splashImg.alt || 'n/a'}] ${splashImg.src}`;
      splashImgUrl = imgUrl(splashImg);
    }
    // Property-level marketing banner (bedroom pages), used only when a card has no special of its own.
    if (!splash) {
      const bannerTitle = txt(document.querySelector('.mrktng-space__title'));
      const bannerBody = txt(document.querySelector('.mrktng-space__content p'));
      const banner = [bannerTitle, bannerBody].filter(Boolean).join(' — ');
      if (banner && /free|special|\$|off|waive/i.test(banner)) splash = banner;
    }
    const cards = document.querySelectorAll('.fp-card');
    if (cards.length) {
      cards.forEach((card) => {
        const titleEl = card.querySelector('.fp-title');
        const soldOut = titleEl && titleEl.querySelector('.student-sold-out') ? txt(titleEl.querySelector('.student-sold-out')) : '';
        let title = txt(titleEl).replace(soldOut, '').trim();
        const bedbath = txt(card.querySelector('.fp-col.bed-bath'));
        const special = txt(card.querySelector('.fp-special-content'));
        const img = imgUrl(card.querySelector('img'));
        const optRows = card.querySelectorAll('.fp-options-table .option-row:not(.title)');
        if (!optRows.length) {
          rows.push({ label: title, bedbath, rent: '', lease: '', option: '', special, soldOut, img });
        }
        optRows.forEach((r) => {
          rows.push({
            label: title,
            bedbath,
            option: txt(r.querySelector('.detail p')) || txt(r.querySelector('.detail')),
            rent: txt(r.querySelector('.rent .fee-transparency-text')) || txt(r.querySelector('.rent')),
            lease: txt(r.querySelector('.lease-term-name')),
            special,
            soldOut: soldOut || (r.className.includes('student-sold-out') ? 'Sold-Out' : ''),
            img,
          });
        });
      });
      return { variant: 'A', rows, splash, splashImgUrl };
    }
    // variant B
    document.querySelectorAll('.fp-table-wrapper').forEach((wrap) => {
      const block = wrap.closest('.fp-col-wrapper') ? wrap.closest('.fp-col-wrapper').parentElement : wrap.parentElement;
      const h = block.querySelector('h4 a, h4');
      let title = txt(h);
      const soldOutTitle = /sold[\s-]?out$/i.test(title);
      title = title.replace(/sold[\s-]?out$/i, '').trim();
      let availNote = '';
      const pipe = title.match(/^(.*?)\s*\|\s*(.+)$/);
      if (pipe && /available|left|sold|waitlist|spot/i.test(pipe[2])) {
        title = pipe[1].trim();
        availNote = pipe[2].trim();
      }
      const bedbath = txt(block.querySelector('.fp-col.bed-bath .fp-col-text'));
      const sqft = txt(block.querySelector('.fp-col.sq-feet .fp-col-text'));
      const specialName = txt(block.querySelector('.fp-special-name'));
      const specialDesc = txt(block.querySelector('.fp-special-details .lease-desc, .lease-desc'));
      const special = [specialName, specialDesc].filter(Boolean).join(' — ');
      const soldOutBlock = soldOutTitle || (block.className && block.className.includes('student-sold-out')) ? 'Sold-Out' : '';
      const img = imgUrl(block.querySelector('img'));
      wrap.querySelectorAll('ul.fp-data-wrapper li.fp-row-wrapper').forEach((li) => {
        rows.push({
          label: title,
          bedbath,
          sqft,
          option: txt(li.querySelector('.radio-label')) || txt(li.querySelector('.room-type')),
          rent: txt(li.querySelector('.text.rent .fee-transparency-text')) || txt(li.querySelector('.text.rent')),
          lease: txt(li.querySelector('.lease-term-name')),
          special,
          soldOut: soldOutBlock || (txt(li).match(/sold[\s-]?out/i) ? 'Sold-Out' : '') || (/sold[\s-]?out/i.test(availNote) ? 'Sold-Out' : ''),
          avail: availNote,
          img,
        });
      });
    });
    if (rows.length) return { variant: 'B', rows, splash, splashImgUrl };
    // variant D: marketing grid (e.g. The Waller bedroom pages) — .fp-grid-item
    document.querySelectorAll('.fp-grid-item').forEach((card) => {
      const rentCol = card.querySelector('.details-col.rent');
      const rentTitle = txt(rentCol && rentCol.querySelector('.title'));
      let rentText = txt(card.querySelector('.details-col.rent .fee-transparency-text'))
        || txt(card.querySelector('.details-col.rent .value'));
      let totalText = '';
      card.querySelectorAll('.details-col').forEach((col) => {
        const title = txt(col.querySelector('.title'));
        if (/total monthly/i.test(title)) {
          totalText = txt(col.querySelector('.fee-transparency-text')) || txt(col.querySelector('.value'));
        }
      });
      if (/total monthly/i.test(rentTitle)) {
        totalText = totalText || rentText;
        rentText = '';
      }
      const avail = txt(card.querySelector('.available-units'));
      rows.push({
        label: txt(card.querySelector('.fp-name-link, .fp-name')),
        bedbath: txt(card.querySelector('.details-col.bed-bath .value')),
        sqft: txt(card.querySelector('.details-col.sq-feet .value')),
        option: '',
        rent: rentText,
        total: totalText,
        rentLabel: rentTitle,
        lease: txt(card.querySelector('.lease-term-name')),
        special: txt(card.querySelector('.fp-special-name')),
        soldOut: /sold[\s-]?out/i.test(avail),
        avail,
        img: imgUrl(card.querySelector('img')),
      });
    });
    if (rows.length) return { variant: 'D', rows, splash, splashImgUrl };
    // variant C: .floorplan-item list with inline text
    // "Studio Style 1 Iconic View Sold-Out Studio, 1 Bath - $2,459 Lease term: 12 Month (...)"
    document.querySelectorAll('.floorplan-item').forEach((li) => {
      const text = txt(li);
      if (!text) return;
      const img = imgUrl(li.querySelector('img'));
      const m = text.match(/^(.*?)(Sold-?Out)?\s*((?:Studio|\d+\s*Bed(?:room)?s?)\s*,\s*[\d\.]+\s*Bath[^$]*?)-\s*(\$[\d,]+|Call for Pricing)\s*(?:Lease term:\s*([^()]+\([^)]*\)))?/i);
      if (!m) { rows.push({ label: text.slice(0, 60), bedbath: '', option: '', rent: '', lease: '', special: '', soldOut: /sold-?out/i.test(text) ? 'Sold-Out' : '', img }); return; }
      rows.push({
        label: (m[1] || '').trim(),
        bedbath: (m[3] || '').trim(),
        option: '',
        rent: m[4] && m[4].startsWith('$') ? m[4] : '',
        lease: (m[5] || '').trim(),
        special: '',
        soldOut: m[2] ? 'Sold-Out' : '',
        img,
      });
    });
    return { variant: 'C', rows, splash, splashImgUrl };
  },

  landmark: () => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    document.querySelectorAll('.floorplan[id^="floorplan-"]').forEach((card) => {
      if (card.closest('.floorplan-modal')) return;
      const name = txt(card.querySelector('.floorplan__name'));
      const details = txt(card.querySelector('.floorplan__details'));
      const disclaimer = txt(card.querySelector('.floorplan__disclaimer'));
      const message = txt(card.querySelector('.floorplan__message'));
      const img = imgUrl(card.querySelector('img.floorplan__image, .floorplan__image img, img'));
      const prices = card.querySelectorAll(':scope > .floorplan__prices .floorplan__price');
      let pushed = false;
      prices.forEach((p) => {
        const label = txt(p.querySelector('.floorplan__price--label'));
        const valEl = p.querySelector('.floorplan__price--value');
        if (!valEl) return; // "Starting At" header block
        const value = txt(valEl);
        const base = txt(p.querySelector('.floorplan__price--base-rate'));
        const soldOut = valEl.className.includes('sold-out') || /sold\s*out/i.test(value);
        rows.push({ name, details, label, value, base, disclaimer, message, soldOut, img });
        pushed = true;
      });
      if (!pushed) rows.push({ name, details, label: '', value: '', base: '', disclaimer, message, soldOut: /sold\s*out/i.test(txt(card)), img });
    });
    return { rows };
  },

  rambler_lvbode: () => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    document.querySelectorAll('.card.floorplan').forEach((card) => {
      const name = txt(card.querySelector('.unit-type h3'));
      const meta = Array.from(card.querySelectorAll('.unit-type p')).map((p) => txt(p));
      const bedbath = meta.find((t) => /BR|BA|Bed|Bath/i.test(t)) || '';
      const soldOut = card.className.includes('sold-out') || meta.some((t) => /sold\s*out/i.test(t));
      const fpPrice = card.getAttribute('data-price');
      const sqft = card.getAttribute('data-sq-footage');
      const label = txt(card.querySelector('.card-custom-label'));
      const img = imgUrl(card.querySelector('img'));
      // group unit rows by (room type, price)
      const groups = {};
      card.querySelectorAll('.units ul.unit').forEach((u) => {
        const price = u.getAttribute('data-price');
        const avDate = u.getAttribute('data-available-date') || '';
        const avail = u.getAttribute('data-available');
        const cols = Array.from(u.querySelectorAll('li')).map((li) => txt(li)).filter(Boolean);
        const room = cols.find((c) => /private|shared|double|single/i.test(c)) || '';
        const key = room + '|' + price;
        if (!groups[key]) groups[key] = { room, price, n: 0, dates: [], anyAvail: false };
        groups[key].n += 1;
        if (avDate) groups[key].dates.push(avDate);
        if (avail === 'true') groups[key].anyAvail = true;
      });
      const gvals = Object.values(groups);
      if (!gvals.length) {
        rows.push({ name, bedbath, sqft, price: fpPrice, room: '', nUnits: 0, dates: [], soldOut, label, img });
      } else {
        gvals.forEach((g) => rows.push({ name, bedbath, sqft, price: g.price, room: g.room, nUnits: g.n, dates: g.dates.slice(0, 3), soldOut: soldOut && !g.anyAvail, label, img }));
      }
    });
    return { rows };
  },

  sinclair_wp: () => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    document.querySelectorAll('.element-item').forEach((card) => {
      const name = card.getAttribute('data-name') || txt(card.querySelector('.floor-title'));
      const status = card.getAttribute('data-status') || card.getAttribute('data-av-status') || '';
      const banner = txt(card.querySelector('.unit-status span, .unit-status'));
      const detail = txt(card.querySelector('.unit-detail .bedroom-num')) || txt(card.querySelector('.unit-detail'));
      const disclaimer = txt(card.querySelector('.fp-full-disclaimer'));
      // first non-icon image (bed/bath glyphs share the card)
      const img = imgUrl(Array.from(card.querySelectorAll('img'))
        .find((i) => !/bed|bath/i.test(i.className) && !/^(bed|bath)$/i.test(i.alt || '')));
      const rtContents = card.querySelectorAll('.room-type-content');
      const parsePricing = (scope, roomType) => {
        const primary = scope.querySelector('.primary-price');
        const secondary = scope.querySelector('.secondary-price');
        const cur = (line) => {
          if (!line) return { cur: '', old: '' };
          const vals = Array.from(line.querySelectorAll('.fp-price-value'));
          const old = vals.find((v) => v.className.includes('old-price-value'));
          const curV = vals.filter((v) => !v.className.includes('old-price-value')).pop();
          return { cur: txt(curV), old: txt(old) };
        };
        const p = cur(primary), s = cur(secondary);
        rows.push({ name, roomType, status, banner, detail, disclaimer, total: p.cur, totalOld: p.old, base: s.cur, baseOld: s.old, img });
      };
      if (rtContents.length) {
        rtContents.forEach((rc) => {
          const rt = rc.getAttribute('data-room-type') || '';
          const btn = card.querySelector('.room-type-btn[data-room-type="' + rt + '"]');
          parsePricing(rc, txt(btn) || rt);
        });
      } else {
        parsePricing(card, '');
      }
    });
    return { rows };
  },

  repli360: () => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    // sitewide "SPECIAL OFFERS" slide-out banner (e.g. "ONE MONTH FREE RENT SAVINGS*")
    let banner = '';
    const slide = document.querySelector('#slideit .wrap');
    if (slide) {
      banner = [txt(slide.querySelector('.title')), txt(slide.querySelector('.description')), txt(slide.querySelector('.copyright'))]
        .filter(Boolean).join(' — ');
    }
    document.querySelectorAll('.rracFloorplan').forEach((card) => {
      const h2 = txt(card.querySelector('h2'));
      const p = txt(card.querySelector('.decp p'));
      const price = txt(card.querySelector('.rrac-price'));
      const callForPricing = !!card.querySelector('.call-for-pricing') && !price;
      const availMsg = txt(card.querySelector('.avail_msg'));
      rows.push({
        name: h2 || card.getAttribute('data-fpname') || '',
        detail: p,
        img: imgUrl(card.querySelector('img')),
        beds: card.getAttribute('data-bed'),
        sqft: card.getAttribute('data-size'),
        minPrice: card.getAttribute('data-min-price'),
        maxPrice: card.getAttribute('data-max-price'),
        availDates: card.getAttribute('data-available-date') || '',
        price, callForPricing, availMsg,
        available: card.className.includes('available'),
      });
    });
    return { rows, banner };
  },

  jonah_fp: () => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    document.querySelectorAll('.jd-fp-floorplan-card').forEach((card) => {
      const aria = card.getAttribute('aria-label') || '';
      const name = (aria.match(/details:\s*(.+)$/i) || [])[1] || txt(card.querySelector('[class*="__title"], h2, h3'));
      const body = txt(card);
      rows.push({ name, body, img: imgUrl(card.querySelector('img')) });
    });
    return { rows };
  },

  yugo: (params) => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    const gtmName = (params && params.gtm_name) || '';
    document.querySelectorAll('.product-tile').forEach((t) => {
      const tileGtm = (t.getAttribute('data-gtm-name') || '').trim();
      if (gtmName && tileGtm && tileGtm !== gtmName.trim()) return; // cross-sell tiles for other cities
      const name = txt(t.querySelector('.product-tile__title'));
      const subEl = t.querySelector('.product-tile__subtitle');
      const sub = txt(subEl);
      const oldPrice = subEl ? txt(subEl.querySelector('s')) : '';
      const discount = subEl ? txt(subEl.querySelector('.discount-price')) : '';
      const urgency = txt(t.querySelector('.product__image-urgency-message'));
      const label = txt(t.querySelector('.product-tile__label'));
      const gtmCat = t.getAttribute('data-gtm-category') || '';
      if (!name) return;
      // tile image is item.imageLink — a room/marketing photo, never a plan diagram
      rows.push({ name, sub, oldPrice, discount, urgency, label, gtmCat });
    });
    // de-dup (carousel repeats tiles)
    const seen = new Set();
    return { rows: rows.filter((r) => { const k = r.name + '|' + r.sub; if (seen.has(k)) return false; seen.add(k); return true; }) };
  },

  ion_wp: () => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    const panel = document.querySelector('#standard') || document;
    const term = txt(document.querySelector('.tab1-label p'));
    const special = txt(document.querySelector('#special-banner'));
    panel.querySelectorAll('.floorplan').forEach((fp) => {
      const name = txt(fp.querySelector('h2'));
      // plan images are named per option (e.g. ...NoLabels-D1.png); match by option code
      const imgs = Array.from(fp.querySelectorAll('img')).map((i) => imgUrl(i)).filter(Boolean);
      fp.querySelectorAll('.floorplan-options .upgrade').forEach((up) => {
        const opt = txt(up.querySelector('.fp-option'));
        const ratesEl = up.querySelector('.fp-option-rates');
        const statusEl = up.querySelector('.tier-contracts');
        const status = txt(statusEl);
        let rate = txt(ratesEl);
        if (status) rate = rate.replace(status, '').trim();
        if (!name || !opt) return;
        const code = (opt.match(/[A-Z]+\d+/i) || [opt])[0].replace(/[^\w]/g, '');
        const img = imgs.find((u) => new RegExp('[-_]' + code + '\\.', 'i').test(u)) || imgs[0] || '';
        rows.push({ name, opt, rate, status, term, special, img });
      });
    });
    return { rows };
  },

  rentcafe_ysi: () => {
    // RENTCafe: prefer window.ysi.floorplansList/unitsList; some sites omit it and
    // instead put base/total charges on the fee-breakdown buttons in each card.
    const y = window.ysi || {};
    const fps = y.floorplansList || [];
    const units = y.unitsList || [];
    const names = {};
    units.forEach((u) => { if (u.FloorplanId) names[u.FloorplanId] = u.FloorplanName; });
    // sitewide promo "nudge" banner (e.g. "4 Weeks Free on Select Apartment Homes")
    const nudgeEl = document.querySelector('.nudgeTop-title, [id^="nudgeTop-title"]');
    const banner = nudgeEl ? nudgeEl.textContent.replace(/\s+/g, ' ').trim() : '';
    // card <img> alts read like "… A1 Floor Plan" — lets ysi rows match an image by plan name
    const fpImgs = Array.from(document.querySelectorAll('img'))
      .filter((i) => /floor ?plan/i.test(i.alt || ''))
      .map((i) => ({ alt: i.alt || '', url: imgUrl(i) }));
    const domCards = [];
    if (!fps.length) {
      document.querySelectorAll('a.show-inclusive-fee-button').forEach((btn) => {
        const aria = btn.getAttribute('aria-label') || '';
        const nameM = aria.match(/for floor plan\s+(.+?),/i) || aria.match(/floor plan\s+(\S+)/i);
        const onclick = btn.getAttribute('onclick') || '';
        const bedsM = onclick.match(/'floorplan_size':'(\d+)/);
        const sqftM = onclick.match(/'square_footage':'([\d,]+)'/);
        const card = btn.closest('.card') || btn.closest('.card-body') || document;
        const avail = (card.textContent.match(/(\d+)\s*Available/i) || [])[1] || '';
        domCards.push({
          name: nameM ? nameM[1].trim() : '',
          base: btn.getAttribute('data-fp_base_charge') || '',
          fee: btn.getAttribute('data-fp_inclusive_charge') || '',
          total: btn.getAttribute('data-fp_total_charge') || '',
          beds: bedsM ? bedsM[1] : '',
          sqft: sqftM ? sqftM[1].replace(/,/g, '') : '',
          avail,
          img: imgUrl(card.querySelector('img')),
        });
      });
    }
    return { fps, names, domCards, banner, fpImgs };
  },

  rise_units: () => {
    // Rise at West Campus: unit-detail modals carry unit number + plan + beds,
    // but the site publishes no prices anywhere (leasing flow only).
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    document.querySelectorAll('.unit-detail-modal').forEach((m) => {
      const id = m.id || '';
      const unitM = id.match(/unit-([\w-]+)/i);
      // the .unit-detail-modal anchor is empty; unit text, plan code, and the
      // plan diagrams (/upload/FloorPlans/) live in the enclosing .item-result.
      // Prefer the clean noHighlights image over the -ALL highlighted overlay.
      const scope = m.closest('.item-result') || m.parentElement || m;
      const body = [m.getAttribute('data-fcode') || '', txt(scope)].filter(Boolean).join(' | ');
      const imgs = Array.from(scope.querySelectorAll('img')).map((i) => imgUrl(i)).filter(Boolean);
      const img = imgs.find((u) => /noHighlights/i.test(u)) || imgs.find((u) => /FloorPlans/i.test(u)) || '';
      rows.push({ unit: unitM ? unitM[1] : id, body, img });
    });
    return { rows };
  },

  villas_wp: () => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    const json = (s, dflt) => { try { return s ? JSON.parse(s) : dflt; } catch (e) { return dflt; } };
    // LeaseLeads plugin (current markup): each [data-ll-floor-plan-card] carries its
    // lease terms as JSON in data-ll-floor-plan-lease-terms and filter facets
    // (bedrooms, size, move-in date, marketing labels) in data-filters.
    const llCards = document.querySelectorAll('[data-ll-floor-plan-card]');
    if (llCards.length) {
      // sitewide specials: announcement bar details + timed "nudge" popup
      const specials = [];
      const ann = document.querySelector('[data-ll-announcement-details-title]');
      if (ann) specials.push([txt(ann), txt(document.querySelector('[data-ll-announcement-details-description]'))].filter(Boolean).join(' — '));
      const nudge = document.querySelector('[data-ll-nudge-title]');
      if (nudge) specials.push([txt(nudge), txt(document.querySelector('[data-ll-nudge-description]'))].filter(Boolean).join(' — '));
      const seen = new Set();
      llCards.forEach((card) => {
        const id = card.getAttribute('data-ll-floor-plan-id') || '';
        if (id && seen.has(id)) return;
        seen.add(id);
        const filters = json(card.getAttribute('data-filters'), {});
        const availEl = card.querySelector('[data-ll-floor-plan-card-availability]');
        rows.push({
          ll: true,
          name: txt(card.querySelector('[data-ll-floor-plan-name]')),
          details: txt(card.querySelector('[data-ll-floor-plan-details]')).replace(txt(availEl), '').trim(),
          terms: json(card.getAttribute('data-ll-floor-plan-lease-terms'), []),
          filters,
          price: txt(card.querySelector('[data-ll-floor-plan-card-price-value]')),
          baseText: txt(card.querySelector('[data-ll-floor-plan-card-base-rent-value]')),
          priceLabel: txt(card.querySelector('[data-ll-floor-plan-card-price-label]')),
          availState: availEl ? availEl.getAttribute('data-state') || '' : '',
          availText: txt(availEl),
          units: txt(card.querySelector('[data-ll-floor-plan-card-units-available]')),
          labels: Array.from(card.querySelectorAll('[data-ll-floor-plan-card-marketing-labels] span')).map((s) => txt(s)).filter(Boolean),
          img: imgUrl(card.querySelector('[data-ll-floor-plan-images] img, img')),
          specials,
        });
      });
      return { rows };
    }
    // legacy markup (.floor-plan-card) — sitewide promo bar (e.g. "APPLY FOR FREE TODAY AND SAVE UP TO $4,236 FOR THE YEAR!")
    const bannerEl = document.querySelector('.leaseleads-banner, .promo-bar, .top-bar, header .banner, .announcement');
    let banner = bannerEl ? txt(bannerEl) : '';
    if (!banner) {
      const cand = Array.from(document.querySelectorAll('header a, header p, header div'))
        .map((e) => txt(e)).find((t) => t.length < 120 && /save|free|special|\$\d/i.test(t) && /apply|save|special|free/i.test(t));
      banner = cand || '';
    }
    document.querySelectorAll('.floor-plan-card').forEach((card) => {
      const struck = txt(card.querySelector('.leaseleads-price-stroke, s, .strike, del'));
      let current = '';
      const strokeEl = card.querySelector('.leaseleads-price-stroke');
      if (strokeEl && strokeEl.nextElementSibling) current = txt(strokeEl.nextElementSibling);
      rows.push({
        img: imgUrl(card.querySelector('img')),
        name: txt(card.querySelector('.floor-plan-card__title')),
        beds: txt(card.querySelector('.floor-plan-card__beds')),
        baths: txt(card.querySelector('.floor-plan-card__bath')),
        size: txt(card.querySelector('.floor-plan-card__size')),
        details: Array.from(card.querySelectorAll('.floor-plan-card__details-item')).map((d) => txt(d)),
        body: txt(card),
        struck, current, banner,
      });
    });
    return { rows };
  },

  // Gogetter Network / WooCommerce floorplan cards (Noble 2500). Listing is
  // SiteGround-walled for curl; Playwright gets the rendered .floorplan-cards.
  gogetter_wc_floorplans: () => {
    const rows = [];
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
    const seen = new Set();
    document.querySelectorAll('.floorplan-cards').forEach((card) => {
      const name = txt(card.querySelector('.floorplan-title'));
      if (!name || seen.has(name)) return;
      seen.add(name);
      const href = (card.querySelector('.cta-btn-primary a, a[href*="/rates-floorplans/"]') || {}).href || '';
      rows.push({
        name,
        beds: txt(card.querySelector('.bed-count, .detail-item.bed-count')),
        baths: txt(card.querySelector('.bath-count, .detail-item.bath-count')),
        price: txt(card.querySelector('.current-price, .price-section')),
        term: txt(card.querySelector('.fp-card-term-date')),
        img: imgUrl(card.querySelector('img.floorplan-image, .floorplan-cards-header img')),
        href,
        body: txt(card),
      });
    });
    return { rows };
  },
};

// ---- normalization to output row fragments (runs in Node) ----

function parseConcession(raw) {
  if (!raw) return { type: '', value: '' };
  const words = { one: '1', two: '2', three: '3', four: '4', 'half a': '0.5' };
  const r = raw.toLowerCase().replace(/\b(one|two|three|four|half a)\b(?=\s*(?:month|week)s?\s*free)/g, (w) => words[w]);
  let m;
  if ((m = r.match(/(\d+(?:\.\d+)?)\s*(?:months?)\s*free/))) return { type: 'months_free', value: m[1] };
  if ((m = r.match(/(\d+(?:\.\d+)?)\s*(?:weeks?)\s*free/))) return { type: 'weeks_free', value: m[1] };
  if ((m = r.match(/\$\s*([\d,]+)\s*(?:off|discount)/))) return { type: 'flat_discount', value: m[1].replace(/,/g, '') };
  if ((m = r.match(/save\s*\$\s*([\d,]+)/))) return { type: 'flat_discount', value: m[1].replace(/,/g, '') };
  if ((m = r.match(/\$\s*([\d,]+)\s*(?:gift\s*card|credit)/))) return { type: 'gift_card_or_credit', value: m[1].replace(/,/g, '') };
  if (/waive[ds]?/.test(r)) return { type: 'waived_fee', value: '' };
  if (/free|special|sale|% off|perk/.test(r)) return { type: 'other', value: '' };
  return { type: 'other', value: '' };
}

function bedsBathsFromText(t) {
  if (!t) return { beds: '', baths: '' };
  const s = t.replace(/\s+/g, ' ');
  let beds = '', baths = '';
  if (/studio|efficiency/i.test(s)) beds = '0';
  let m = s.match(/(\d+)\s*(?:bed|br|bd|bedroom)/i); if (m) beds = m[1];
  m = s.match(/(\d+(?:\.\d+)?)\s*(?:bath|ba(?!l)|bathroom)/i); if (m) baths = m[1];
  return { beds, baths };
}

function sqftFromText(t) {
  if (!t) return '';
  const m = String(t).replace(/,/g, '').match(/(\d{3,5})\s*(?:-|–|to)?\s*(\d{3,5})?\s*sq/i);
  if (m) return m[2] ? `${m[1]}-${m[2]}` : m[1];
  return '';
}

function normalize(backend, data) {
  const out = [];
  const push = (o) => out.push(Object.assign({
    unit_or_floorplan_label: '', beds: '', baths: '', sqft: '',
    base_rent: '', total_price_with_mandatory_fees: '', price_basis: '',
    concessions_raw: '', concessions_type: '', concessions_value: '',
    availability: '', layout_image_url: '', price_image_url: '',
    concessions_image_url: '', price_status: 'listed',
  }, o));

  if (backend === 'entrata_pp') {
    for (const r of data.rows) {
      const bb = bedsBathsFromText(r.bedbath);
      const sqft = r.sqft ? String(num(r.sqft) || r.sqft) : sqftFromText(r.bedbath);
      // property-level splash popup applies when the floorplan has no special of its own
      const special = r.special || data.splash || '';
      const cc = parseConcession(special);
      const rent = num(r.rent);
      const total = num(r.total);
      const labelSaysTotal = /total monthly/i.test(r.rentLabel || '');
      const baseRent = labelSaysTotal ? '' : (rent ?? '');
      const totalRent = total != null ? total : (labelSaysTotal ? (rent ?? '') : '');
      const availLabel = (r.avail || '').replace(/\s+/g, ' ').trim();
      const leaseLabel = (r.lease || '').replace(/\s+/g, ' ').trim();
      push({
        unit_or_floorplan_label: r.option && !/private/i.test(r.option) ? `${r.label} (${r.option})` : (r.option ? `${r.label} (${r.option})` : r.label),
        beds: bb.beds, baths: bb.baths, sqft,
        base_rent: baseRent,
        total_price_with_mandatory_fees: totalRent,
        price_basis: totalRent !== '' ? 'total' : (baseRent !== '' ? 'base' : ''),
        concessions_raw: special, concessions_type: special ? cc.type : '', concessions_value: special ? cc.value : '',
        availability: r.soldOut ? 'Sold Out' : (
          availLabel ? [availLabel, leaseLabel].filter(Boolean).join(' — ')
                     : (leaseLabel ? `Available — ${leaseLabel}` : 'Available')
        ),
        layout_image_url: r.img || '',
        // splash promos are image-only popups; attach the image when the splash is the row's concession
        concessions_image_url: !r.special && data.splash && data.splashImgUrl ? data.splashImgUrl : '',
        price_status: (baseRent !== '' || totalRent !== '') ? 'listed' : 'not_publicly_listed',
      });
    }
  } else if (backend === 'landmark') {
    for (const r of data.rows) {
      const bb = bedsBathsFromText(r.details + ' ' + r.name);
      const total = num(r.value);
      const baseM = (r.base || '').replace(/,/g, '').match(/\$?\s*(\d+(?:\.\d+)?)/);
      push({
        unit_or_floorplan_label: r.label ? `${r.name} (${r.label})` : r.name,
        beds: bb.beds, baths: bb.baths, sqft: sqftFromText(r.details),
        base_rent: baseM ? parseFloat(baseM[1]) : '',
        total_price_with_mandatory_fees: total ?? '',
        price_basis: total != null ? 'total' : (baseM ? 'base' : ''),
        concessions_raw: r.message && /\$|off|free|save|special|sale|waive|gift/i.test(r.message) ? r.message : '',
        availability: r.soldOut ? 'Sold Out' : (r.message || 'Available'),
        layout_image_url: r.img || '',
        price_status: total != null || baseM ? 'listed' : 'not_publicly_listed',
      });
    }
  } else if (backend === 'rambler_lvbode') {
    for (const r of data.rows) {
      const bb = bedsBathsFromText(r.bedbath);
      const promoish = r.label && /\$|% ?off|free|save|special|sale|waive|gift/i.test(r.label) && !/sold\s*out/i.test(r.label);
      const cc = parseConcession(promoish ? r.label : '');
      const price = num(r.price);
      push({
        unit_or_floorplan_label: r.room ? `${r.name} (${r.room})` : r.name,
        beds: bb.beds, baths: bb.baths, sqft: r.sqft ? String(num(r.sqft)) : '',
        base_rent: price ?? '',
        price_basis: price != null ? 'base' : '',
        concessions_raw: promoish ? r.label : '', concessions_type: promoish ? cc.type : '', concessions_value: promoish ? cc.value : '',
        availability: r.soldOut ? 'Sold Out' : (r.nUnits ? `${r.nUnits} unit(s); earliest ${r.dates[0] || 'n/a'}` : 'See site'),
        layout_image_url: r.img || '',
        price_status: price != null ? 'listed' : 'not_publicly_listed',
      });
    }
  } else if (backend === 'sinclair_wp') {
    for (const r of data.rows) {
      const bb = bedsBathsFromText(r.detail);
      if (!bb.beds || !bb.baths) {
        // detail renders as "4 | 4 | 1339-1358 SQ.FT" (bed/bath icons carry the meaning)
        const m = (r.detail || '').match(/^\s*(\d+)\s*\|\s*(\d+)/);
        if (m) { bb.beds = bb.beds || m[1]; bb.baths = bb.baths || m[2]; }
      }
      // banner mixes promo + availability; split on '|'
      const parts = (r.banner || '').split('|').map((s) => s.trim()).filter(Boolean);
      const promoParts = parts.filter((p) => /\$|off|save|free|sale|special/i.test(p));
      const availParts = parts.filter((p) => !promoParts.includes(p));
      const cc = parseConcession(promoParts.join(' | '));
      const total = num(r.total);
      const base = num(r.base);
      push({
        unit_or_floorplan_label: r.roomType ? `${r.name} (${r.roomType})` : r.name,
        beds: bb.beds, baths: bb.baths, sqft: sqftFromText(r.detail),
        base_rent: base ?? '',
        total_price_with_mandatory_fees: total ?? '',
        price_basis: total != null ? 'total' : (base != null ? 'base' : ''),
        concessions_raw: r.banner || '',
        concessions_type: promoParts.length ? cc.type : '', concessions_value: promoParts.length ? cc.value : '',
        availability: [r.status, availParts.join(' | ')].filter(Boolean).join(' — '),
        layout_image_url: r.img || '',
        price_status: total != null || base != null ? 'listed' : 'not_publicly_listed',
      });
    }
  } else if (backend === 'repli360') {
    const banner = data.banner || '';
    const bcc = parseConcession(banner);
    for (const r of data.rows) {
      const bb = bedsBathsFromText(r.detail || '');
      if (!bb.beds && r.beds != null && r.beds !== '') bb.beds = String(num(r.beds) ?? '');
      const minP = num(r.minPrice), maxP = num(r.maxPrice);
      const price = num(r.price) ?? minP;
      let dates = '';
      try { dates = JSON.parse(r.availDates || '[]').slice(0, 3).join(', '); } catch (e) { dates = r.availDates; }
      push({
        unit_or_floorplan_label: r.name,
        beds: bb.beds, baths: bb.baths, sqft: r.sqft ? String(num(r.sqft)) : '',
        base_rent: r.callForPricing ? '' : (price ?? ''),
        price_basis: r.callForPricing || price == null ? '' : 'base',
        concessions_raw: banner, concessions_type: banner ? bcc.type : '', concessions_value: banner ? bcc.value : '',
        availability: [r.available ? 'Available' : 'Unavailable', r.availMsg, dates && `move-in: ${dates}`,
          minP != null && maxP != null && maxP > minP ? `advertised range $${minP}-$${maxP}` : ''].filter(Boolean).join(' — '),
        layout_image_url: r.img || '',
        price_status: r.callForPricing || price == null ? 'not_publicly_listed' : 'listed',
      });
    }
  } else if (backend === 'jonah_fp') {
    for (const r of data.rows) {
      const bb = bedsBathsFromText(r.body);
      const priceM = r.body.replace(/,/g, '').match(/\$\s*(\d{3,5})/);
      push({
        unit_or_floorplan_label: r.name,
        beds: bb.beds, baths: bb.baths, sqft: sqftFromText(r.body),
        base_rent: priceM ? parseFloat(priceM[1]) : '',
        price_basis: priceM ? 'base' : '',
        availability: /sold\s*out|unavailable|waitlist/i.test(r.body) ? (r.body.match(/sold\s*out|waitlist/i) || [''])[0] : 'See site',
        layout_image_url: r.img || '',
        price_status: priceM ? 'listed' : 'not_publicly_listed',
      });
    }
  } else if (backend === 'yugo') {
    for (const r of data.rows) {
      const bb = bedsBathsFromText(r.name);
      const disc = num(r.discount);
      const base = num(r.oldPrice) ?? num(r.sub);
      const effective = disc ?? base;
      const cc = parseConcession(r.urgency);
      push({
        unit_or_floorplan_label: r.name,
        beds: bb.beds, baths: bb.baths,
        base_rent: effective ?? '',
        price_basis: effective != null ? 'base' : '',
        concessions_raw: [r.oldPrice && disc ? `was ${r.oldPrice}, now ${r.discount}` : '', r.urgency].filter(Boolean).join(' | '),
        concessions_type: r.urgency || disc ? (cc.type || 'flat_discount') : '',
        concessions_value: base != null && disc != null ? String(Math.round((base - disc) * 100) / 100) : cc.value,
        availability: r.label || (effective != null ? 'Available' : 'See site'),
        price_status: effective != null ? 'listed' : 'not_publicly_listed',
      });
    }
  } else if (backend === 'ion_wp') {
    for (const r of data.rows) {
      const bb = bedsBathsFromText(r.name);
      const rate = num(r.rate);
      const cc = parseConcession(r.special);
      push({
        unit_or_floorplan_label: `${r.name} (${r.opt})`,
        beds: bb.beds, baths: bb.baths,
        base_rent: rate ?? '',
        price_basis: rate != null ? 'base' : '',
        concessions_raw: r.special || '', concessions_type: r.special ? cc.type : '', concessions_value: r.special ? cc.value : '',
        availability: [r.status, r.term].filter(Boolean).join(' — '),
        layout_image_url: r.img || '',
        price_status: rate != null ? 'listed' : 'not_publicly_listed',
      });
    }
  } else if (backend === 'rentcafe_ysi') {
    const banner = data.banner || '';
    const bcc = parseConcession(banner);
    for (const c of data.domCards || []) {
      const base = num(c.base);
      const total = num(c.total);
      push({
        unit_or_floorplan_label: c.name,
        beds: c.beds, baths: '',
        sqft: c.sqft,
        base_rent: base ?? '',
        total_price_with_mandatory_fees: total ?? '',
        price_basis: total != null ? 'total' : (base != null ? 'base' : ''),
        concessions_raw: banner, concessions_type: banner ? bcc.type : '', concessions_value: banner ? bcc.value : '',
        availability: [c.avail ? c.avail + ' available' : '', c.fee ? `mandatory monthly fees ${c.fee}` : ''].filter(Boolean).join(' — '),
        layout_image_url: c.img || '',
        price_status: base != null || total != null ? 'listed' : 'not_publicly_listed',
      });
    }
    for (const fp of data.fps || []) {
      if (fp.isCommercial) continue;
      const name = data.names[fp.Id] || ('Floorplan ' + fp.Id);
      const sqft = fp.MinSqFt ? (fp.MaxSqFt && fp.MaxSqFt !== fp.MinSqFt ? `${fp.MinSqFt}-${fp.MaxSqFt}` : String(fp.MinSqFt)) : '';
      const minRent = fp.MinRent || null;
      // match a page floorplan image by plan name in its alt text; ysi names may carry
      // suffixes the alt lacks (e.g. "A1-Chickadee 80%"), so fall back to the first token
      const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      let fpImg = [name, name.split(/\s+/)[0]].reduce((hit, cand) => {
        if (hit || !cand) return hit;
        const re = new RegExp('(^|\\s)' + esc(cand) + '(\\s|$)', 'i');
        return (data.fpImgs || []).find((i) => re.test(i.alt));
      }, null);
      if (!fpImg) {
        // last resort: plan code (e.g. "E1" of "E1-Mockingbird") at the start of the image filename
        const code = (name.match(/^[A-Za-z]+\d+/) || [])[0];
        if (code) {
          const re = new RegExp('/' + esc(code) + '[@\\-._]', 'i');
          fpImg = (data.fpImgs || []).find((i) => re.test(i.url));
        }
      }
      push({
        unit_or_floorplan_label: name,
        beds: fp.Beds != null ? String(fp.Beds) : '',
        baths: fp.Baths != null ? String(fp.Baths) : '',
        sqft: sqft.replace(/\.0(?=-|$)/g, ''),
        base_rent: minRent ?? '',
        price_basis: minRent != null ? 'base' : '',
        concessions_raw: [banner, fp.HasSpecials ? 'floorplan HasSpecials=true' : ''].filter(Boolean).join(' | '),
        concessions_type: banner ? bcc.type : (fp.HasSpecials ? 'other' : ''),
        concessions_value: banner ? bcc.value : '',
        availability: [fp.AvailableCount ? `${fp.AvailableCount} available` : 'none available',
          fp.AvailableDate ? 'from ' + String(fp.AvailableDate).slice(0, 10) : '',
          fp.MaxRent && fp.MaxRent !== fp.MinRent ? `advertised range $${fp.MinRent}-$${fp.MaxRent}` : ''].filter(Boolean).join(' — '),
        layout_image_url: fpImg ? fpImg.url : '',
        price_status: minRent != null ? 'listed' : 'not_publicly_listed',
      });
    }
  } else if (backend === 'rise_units') {
    for (const r of data.rows) {
      const bb = bedsBathsFromText(r.body);
      const planM = r.body.match(/([A-Za-z0-9x]{2,10}(?:\s[A-Za-z]{1,10})?)\s+\d+\s*bedroom/i);
      push({
        unit_or_floorplan_label: `${planM ? planM[1] + ' — ' : ''}Unit ${r.unit}`,
        beds: bb.beds || (/studio|sx/i.test(r.body) ? '0' : ''), baths: bb.baths,
        sqft: sqftFromText(r.body),
        availability: 'unit advertised; pricing only via leasing flow',
        layout_image_url: r.img || '',
        price_status: 'not_publicly_listed',
      });
    }
  } else if (backend === 'villas_wp') {
    const promoRe = /\$|% ?off|free|save|special|discount|waive|gift/i;
    for (const r of data.rows) {
      if (r.ll) {
        // LeaseLeads card: one row per floor plan at its lowest advertised term
        // (the price the card itself shows); other term prices go to availability.
        const f = r.filters || {};
        const bb = bedsBathsFromText(r.details);
        const beds = f.bedrooms != null && f.bedrooms !== '' ? String(num(f.bedrooms)) : (bb.beds || bedsBathsFromText(r.name).beds);
        const sMin = num(f.size_min), sMax = num(f.size_max);
        const sqft = sMin ? (sMax && sMax !== sMin ? `${sMin}-${sMax}` : String(sMin)) : sqftFromText(r.details);
        const terms = (Array.isArray(r.terms) ? r.terms : [])
          .map((t) => ({ name: t.name || '', total: num(t.price_with_fees ?? t.price), base: num(t.base_rent) }))
          .filter((t) => t.total != null || t.base != null);
        terms.sort((a, b) => (a.total ?? a.base) - (b.total ?? b.base));
        const best = terms[0] || { name: '', total: num(r.price), base: num(r.baseText) };
        const total = best.total ?? null;
        const base = best.base ?? null;
        const labels = (r.labels && r.labels.length) ? r.labels : (Array.isArray(f.marketing_label) ? f.marketing_label : []);
        const promoLabels = labels.filter((l) => promoRe.test(l));
        const infoLabels = labels.filter((l) => !promoLabels.includes(l));
        const siteSpecials = (r.specials || []).filter((s) => promoRe.test(s));
        const conc = [...promoLabels, ...siteSpecials].join(' | ');
        // type the card's own special first; sitewide specials only when it has none
        const cc = parseConcession((promoLabels.length ? promoLabels : siteSpecials).join(' | '));
        const soldOut = /sold[\s-]?out/i.test(r.availState) || /sold\s*out/i.test(r.availText);
        const prices = terms.map((t) => t.total ?? t.base);
        const range = prices.length > 1 && Math.max(...prices) > Math.min(...prices)
          ? `advertised range $${Math.min(...prices)}-$${Math.max(...prices)}` : '';
        push({
          unit_or_floorplan_label: r.name,
          beds, baths: bb.baths, sqft,
          base_rent: base ?? '',
          total_price_with_mandatory_fees: total ?? '',
          price_basis: total != null ? 'total' : (base != null ? 'base' : ''),
          concessions_raw: conc,
          concessions_type: conc ? cc.type : '', concessions_value: conc ? cc.value : '',
          availability: soldOut ? 'Sold Out' : [r.availText || 'Available', r.units, best.name, range, ...infoLabels].filter(Boolean).join(' — '),
          layout_image_url: r.img || '',
          price_status: total != null || base != null ? 'listed' : 'not_publicly_listed',
        });
        continue;
      }
      const bb = bedsBathsFromText(`${r.beds} ${r.baths}`);
      const struck = num(r.struck);
      const current = num(r.current);
      const priceM = r.body.replace(/,/g, '').match(/\$\s*(\d{3,5})/);
      const price = current ?? (priceM ? parseFloat(priceM[1]) : null);
      const discRaw = struck != null && current != null ? `was $${struck}, now $${current}` : '';
      const conc = [discRaw, r.banner || ''].filter(Boolean).join(' | ');
      const cc = parseConcession(conc);
      push({
        unit_or_floorplan_label: r.name,
        beds: bb.beds || bedsBathsFromText(r.name).beds, baths: bb.baths,
        sqft: sqftFromText(r.size || r.body),
        base_rent: price ?? '',
        price_basis: price != null ? 'base' : '',
        concessions_raw: conc,
        concessions_type: conc ? (discRaw ? 'flat_discount' : cc.type) : '',
        concessions_value: struck != null && current != null ? String(struck - current) : cc.value,
        availability: /sold\s*out|waitlist/i.test(r.body) ? (r.body.match(/sold\s*out|waitlist/i) || [''])[0] : 'See site',
        layout_image_url: r.img || '',
        price_status: price != null ? 'listed' : 'not_publicly_listed',
      });
    }
  } else if (backend === 'gogetter_wc_floorplans') {
    for (const r of data.rows) {
      const bb = bedsBathsFromText(`${r.beds || ''} ${r.baths || ''} ${r.name || ''}`);
      const contact = /contact us for rate|call for|n\/a|nan/i.test(r.price || '');
      const rent = contact ? null : num(r.price);
      push({
        unit_or_floorplan_label: (r.name || '').replace(/\*+$/, '').trim(),
        beds: bb.beds, baths: bb.baths,
        sqft: sqftFromText(r.body || ''),
        base_rent: rent ?? '',
        price_basis: rent != null ? 'base' : '',
        availability: [r.term, contact ? (r.price || 'Contact us for rate') : ''].filter(Boolean).join(' — '),
        layout_image_url: r.img || '',
        price_status: rent != null ? 'listed' : 'not_publicly_listed',
      });
    }
  }
  return out;
}

// Backends whose data arrives via XHR the page makes itself: capture matching
// responses instead of parsing the DOM.
const SNIFFERS = {
  g5_sniff: {
    pattern: /inventory\.g5marketingcloud\.com\/graphql/,
    normalize: (bodies) => {
      const out = [];
      const plans = {};   // floorplan info from ApartmentComplex query
      const unitsByPlan = {};
      for (const b of bodies) {
        let j; try { j = JSON.parse(b); } catch (e) { continue; }
        const d = j.data || {};
        if (d.apartmentComplex && d.apartmentComplex.floorplans) {
          for (const fp of d.apartmentComplex.floorplans) plans[fp.id] = fp;
        }
        if (d.units) {
          for (const u of d.units) {
            const fpName = (u.floorplan && u.floorplan.name) || 'unknown';
            (unitsByPlan[fpName] = unitsByPlan[fpName] || []).push(u);
          }
        }
      }
      const planImgByName = {};
      for (const fp of Object.values(plans)) {
        if (fp.name) planImgByName[fp.name] = fp.imageUrl || (fp.imageUrls || [])[0] || '';
      }
      for (const [fpName, units] of Object.entries(unitsByPlan)) {
        for (const u of units) {
          const minPrice = (u.prices || []).find((p) => p.priceType === 'min_rent');
          const val = minPrice ? parseFloat(minPrice.value) : null;
          out.push({
            unit_or_floorplan_label: `${fpName} — Unit ${u.displayName || u.name}`,
            beds: u.floorplan && u.floorplan.beds != null ? String(u.floorplan.beds) : '',
            baths: u.floorplan && u.floorplan.baths != null ? String(parseFloat(u.floorplan.baths)) : '',
            sqft: u.sqftDisplay || '',
            base_rent: val ?? '', total_price_with_mandatory_fees: '',
            price_basis: val != null ? 'base' : '',
            concessions_raw: '', concessions_type: '', concessions_value: '',
            availability: u.availabilityDate ? 'available ' + u.availabilityDate : '',
            layout_image_url: (u.floorplan && u.floorplan.imageUrl) || planImgByName[fpName] || '',
            price_image_url: '', concessions_image_url: '',
            price_status: val != null ? 'listed' : 'not_publicly_listed',
          });
        }
      }
      return out;
    },
  },
  realpage_sniff: {
    pattern: /api\.ws\.realpage\.com\/v2\/property\/\d+\/(floorplans|units)/,
    normalize: (bodies) => {
      const out = [];
      let plans = [], units = [];
      for (const b of bodies) {
        let j; try { j = JSON.parse(b); } catch (e) { continue; }
        const resp = j.response || j;
        if (Array.isArray(resp.floorplans)) plans = plans.concat(resp.floorplans);
        if (Array.isArray(resp.units)) units = units.concat(resp.units);
      }
      const planName = {};
      const planImg = {};
      const rpImg = (p) => {
        // dimg URLs carry a %s size-token slot; native WxH works (tested)
        const ims = (p.floorPlanImages || []).slice().sort((a, b) =>
          ((/2D|Diagram/i.test(String(a.tag)) ? 0 : 1) - (/2D|Diagram/i.test(String(b.tag)) ? 0 : 1))
          || ((a.displaySequence || 0) - (b.displaySequence || 0)));
        if (!ims.length) return '';
        let src = ims[0].httpsSrc || ims[0].httpSrc || ims[0].src || '';
        if (src.includes('%s')) src = src.replace('%s', `${ims[0].maxWidth || 700}x${ims[0].maxHeight || 700}`);
        return src;
      };
      plans.forEach((p) => { planName[String(p.id)] = p.name; planImg[String(p.id)] = rpImg(p); });
      for (const u of units) {
        if (u.displayed === false || u.active === false) continue;
        const val = u.rent != null ? parseFloat(u.rent) : null;
        out.push({
          unit_or_floorplan_label: `${planName[String(u.floorplanId)] || 'Floorplan ' + u.floorplanId} — Unit ${u.unitNumber || u.name || ''}`.trim(),
          beds: u.numberOfBeds != null ? String(u.numberOfBeds) : '',
          baths: u.numberOfBaths != null ? String(u.numberOfBaths) : '',
          sqft: u.squareFeet || '',
          base_rent: val ?? '', total_price_with_mandatory_fees: '',
          price_basis: val != null ? 'base' : '',
          concessions_raw: '', concessions_type: '', concessions_value: '',
          availability: [u.leaseStatus, u.vacantDate ? 'vacant ' + String(u.vacantDate).slice(0, 10) : ''].filter(Boolean).join(' — '),
          layout_image_url: planImg[String(u.floorplanId)] || '',
          price_image_url: '', concessions_image_url: '',
          price_status: val != null ? 'listed' : 'not_publicly_listed',
        });
      }
      const covered = new Set(units.map((u) => String(u.floorplanId)));
      for (const p of plans) {
        if (covered.has(String(p.id))) continue;
        const val = p.rentMin != null ? parseFloat(p.rentMin) : (p.rent != null ? parseFloat(p.rent) : null);
        out.push({
          unit_or_floorplan_label: (p.name || '') + ' [floorplan]',
          beds: p.bedRooms != null ? String(p.bedRooms) : '',
          baths: p.bathRooms != null ? String(p.bathRooms) : '',
          sqft: p.squareFeet || p.minSquareFeet || '',
          base_rent: val ?? '', total_price_with_mandatory_fees: '',
          price_basis: val != null ? 'base' : '',
          concessions_raw: '', concessions_type: '', concessions_value: '',
          availability: 'no available units listed',
          layout_image_url: rpImg(p),
          price_image_url: '', concessions_image_url: '',
          price_status: val != null ? 'listed' : 'not_publicly_listed',
        });
      }
      return out;
    },
  },
  jonah_chunk: {
    pattern: /_fp-renderable\/params/,
    normalize: (bodies) => {
      const out = [];
      const html = bodies.join('\n');
      const cardRe = /jd-fp-card-info__title">([^<]+)<[\s\S]{0,600}?jd-fp-card-info__text">([\s\S]{0,400}?)<\/p>/g;
      let m;
      while ((m = cardRe.exec(html)) !== null) {
        const name = m[1].trim();
        // card image sits shortly before the title in the chunk markup
        const pre = html.slice(Math.max(0, m.index - 1200), m.index);
        const imgM = pre.match(/<img[^>]+(?:data-src|src)="([^"]+)"[^>]*>(?![\s\S]*<img)/);
        const text = m[2].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
        const priceM = text.replace(/,/g, '').match(/\$\s*(\d{3,5})/);
        const bedM = text.match(/(\d+)\s*(?:bed|br)/i);
        const beds = bedM ? bedM[1] : (/studio/i.test(text) ? '0' : '');
        const bathM = text.match(/(\d+(?:\.\d+)?)\s*(?:bath|ba)/i);
        const sqftM = text.replace(/,/g, '').match(/(\d{3,5})\s*sq/i);
        out.push({
          unit_or_floorplan_label: name,
          beds, baths: bathM ? bathM[1] : '',
          sqft: sqftM ? sqftM[1] : '',
          base_rent: priceM ? parseFloat(priceM[1]) : '', total_price_with_mandatory_fees: '',
          price_basis: priceM ? 'base' : '',
          concessions_raw: '', concessions_type: '', concessions_value: '',
          availability: /sold\s*out|waitlist/i.test(text) ? (text.match(/sold\s*out|waitlist/i) || [''])[0] : 'pricing not shown on site; contact form only',
          layout_image_url: imgM ? imgM[1] : '',
          price_image_url: '', concessions_image_url: '',
          price_status: priceM ? 'listed' : 'not_publicly_listed',
        });
      }
      return out;
    },
  },
};

const WAIT_SELECTORS = {
  entrata_pp: '.fp-card, .fp-data-wrapper, .fp-grid-item, .floorplan-item',
  landmark: '.floorplan[id^="floorplan-"]',
  rambler_lvbode: '.card.floorplan',
  sinclair_wp: '.element-item',
  repli360: '.rracFloorplan',
  jonah_fp: '.jd-fp-floorplan-card:not(.jd-fp-floorplan-card--preload)',
  yugo: '.product-tile',
  ion_wp: '.floorplan .fp-option-rates',
  villas_wp: '[data-ll-floor-plan-card], .floor-plan-card',
  rentcafe_ysi: '#fp-container',
  rise_units: '.unit-detail-modal',
  gogetter_wc_floorplans: '.floorplan-cards .floorplan-title',
};

(async () => {
  const [backend, url, paramsJson] = process.argv.slice(2);
  if ((!PARSERS[backend] && !SNIFFERS[backend]) || !url) {
    console.error('usage: dom_extract.js <backend> <url> [paramsJSON]; backends: ' + Object.keys(PARSERS).join(','));
    process.exit(1);
  }
  const params = paramsJson ? JSON.parse(paramsJson) : {};
  // Rebuild addition. Default off: with DOM_PROFILE, DOM_HEADED and DOM_CHALLENGE_WAIT_S
  // unset, launch and context match FML_Data (headless chromium.launch + newContext).
  const domOptsOn = !!(process.env.DOM_PROFILE || process.env.DOM_HEADED === '1' || process.env.DOM_CHALLENGE_WAIT_S);
  const opts = { userAgent: UA, viewport: { width: 1440, height: 900 } };
  let browser, ctx;
  if (!domOptsOn) {
    browser = await chromium.launch();
    ctx = await browser.newContext(opts);
  } else {
    const prof = process.env.DOM_PROFILE;
    const headed = process.env.DOM_HEADED === '1';
    browser = prof
      ? await chromium.launchPersistentContext(prof, { headless: !headed, ...opts })
      : await chromium.launch({ headless: !headed });
    ctx = prof ? browser : await browser.newContext(opts);
  }
  const page = await ctx.newPage();
  let status = 'ok', rows = [];
  const sniffer = SNIFFERS[backend];
  const sniffed = [];
  if (sniffer) {
    page.on('response', async (resp) => {
      try {
        if (sniffer.pattern.test(resp.url()) && resp.status() === 200) sniffed.push(await resp.text());
      } catch (e) { /* body unavailable */ }
    });
  }
  const extraUrls = (!sniffer && Array.isArray(params.extra_urls))
    ? params.extra_urls.filter((u) => typeof u === 'string' && u && u !== url)
    : [];
  const evalParser = () => page.evaluate(
    `((params) => { ${IMG_HELPER} return (${PARSERS[backend].toString()})(params); })(${JSON.stringify(params)})`);
  try {
    if (extraUrls.length) {
      // Several public bedroom URLs per property. A cold navigation often stops
      // on Cloudflare's interstitial; once any public page in this session has
      // loaded, revisit the blocked URLs once. This does not solve a challenge.
      const seen = new Set();
      const absorb = (part) => {
        for (const r of part) {
          const key = [r.unit_or_floorplan_label, r.beds, r.baths, r.sqft,
            r.base_rent, r.total_price_with_mandatory_fees].join('|');
          if (seen.has(key)) continue;
          seen.add(key);
          rows.push(r);
        }
      };
      const visit = async (one) => {
        await page.goto(one, { waitUntil: 'domcontentloaded', timeout: 60000 });
        const title = await page.title();
        if (/just a moment|attention required|access denied/i.test(title)) {
          if (process.env.DOM_PROFILE || process.env.DOM_HEADED === '1' || process.env.DOM_CHALLENGE_WAIT_S) {
            const ws = parseInt(process.env.DOM_CHALLENGE_WAIT_S || (process.env.DOM_HEADED === '1' ? '170' : '8'), 10);
            for (let w = 0; w < ws; w += 2) {
              await page.waitForTimeout(2000);
              if (!/just a moment|attention required|access denied/i.test(await page.title())) break;
            }
          } else {
            await page.waitForTimeout(8000);
          }
          const t2 = await page.title();
          if (/just a moment|attention required|access denied/i.test(t2)) return 'blocked';
        }
        try {
          await page.waitForSelector(WAIT_SELECTORS[backend], { timeout: 20000 });
        } catch (e) { /* server-rendered pages may already have the nodes */ }
        await page.waitForTimeout(2000);
        absorb(normalize(backend, await evalParser()));
        return 'loaded';
      };
      const blocked = [];
      let loaded = 0;
      for (const one of [url, ...extraUrls]) {
        const result = await visit(one);
        if (result === 'blocked') blocked.push(one);
        else loaded += 1;
      }
      if (loaded && blocked.length) {
        for (const one of blocked) {
          const result = await visit(one);
          if (result === 'loaded') loaded += 1;
        }
      }
      if (!rows.length) status = loaded ? 'no_rows' : 'blocked_bot_wall';
    } else {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const title = await page.title();
    if (/just a moment|attention required|access denied/i.test(title)) {
      // give the Cloudflare managed (non-interactive) check a chance to clear
      if (process.env.DOM_PROFILE || process.env.DOM_HEADED === '1' || process.env.DOM_CHALLENGE_WAIT_S) {
        const ws = parseInt(process.env.DOM_CHALLENGE_WAIT_S || (process.env.DOM_HEADED === '1' ? '170' : '8'), 10);
        for (let w = 0; w < ws; w += 2) {
          await page.waitForTimeout(2000);
          if (!/just a moment|attention required|access denied/i.test(await page.title())) break;
        }
      } else {
        await page.waitForTimeout(12000);
      }
      const t2 = await page.title();
      if (/just a moment|attention required|access denied/i.test(t2)) {
        console.log(JSON.stringify({ status: 'blocked_bot_wall', rows: [] }));
        await browser.close();
        return;
      }
    }
    if (sniffer) {
      // let the page finish its XHR traffic
      await page.waitForTimeout(12000);
      if (!sniffed.length) await page.waitForTimeout(10000);
      rows = sniffer.normalize(sniffed);
      if (!rows.length) status = sniffed.length ? 'sniffed_but_unparsed' : 'no_matching_xhr';
    } else {
      try {
        await page.waitForSelector(WAIT_SELECTORS[backend], { timeout: 25000 });
      } catch (e) { /* fall through; parser may still find server-rendered content */ }
      await page.waitForTimeout(3000);
      const data = await evalParser();
      rows = normalize(backend, data);
      if (!rows.length) status = 'no_rows';
    }
    }
  } catch (e) {
    status = 'error: ' + e.message.slice(0, 200);
  }
  console.log(JSON.stringify({ status, rows }));
  await browser.close();
})();
