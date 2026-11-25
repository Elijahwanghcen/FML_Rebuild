# CLAUDE.md — UT Austin Apartment Pricing Scraper

## What this project is
This builds the "what landlords currently advertise" dataset for a student apartment-listing aggregator for the UT Austin market (West Campus + the greater off-campus student-housing area). A separate crowdsourced dataset holds what students actually paid; this scraper produces the advertised side so the app can compare them.

## Your job (read this carefully)
You are building **reusable scrapers**, not scraping everything by hand once. The deliverable is:
1. A small set of **per-backend extractors** (one per property-management platform), each tested against 2–3 real properties.
2. A **`properties_config`** (CSV or JSON) mapping each property → its resolved official website → its detected backend platform (e.g. RealPage, Entrata) → the extractor + the endpoint/URL to hit. This is the enrichment of the seed list: names in, website + platform + how-to-get-the-data out.
3. A **`run.py`** that executes the extractors against the config and writes the output CSV.
4. The output **CSV** itself.

The weekly refresh must run `run.py` with **no or minimal LLM calls** — plain deterministic code. Your expensive reasoning is spent now, during the build, so the weekly job stays cheap. Do not design anything that requires an LLM to process every property every week.

## Inputs
- Seed list at `/mnt/user-data/uploads/`. It contains **property names and coordinates (lat/long)**, and may or may not include official website URLs.
- If a property already has a website URL, use it. If it only has a name + coordinates, resolve the official website first (see Methodology step 0). A `GOOGLE_MAPS_API_KEY` is available in the environment for this.
- Treat the seed list as the complete scope. Do not go hunting for additional properties.

## Methodology — per property, in this order
0. **Resolve the official website (if not already provided).** Use the Google Places API (Text Search / Place Details) with the property name and its coordinates as location bias, and read the `websiteUri` field. **Verify** the result actually looks like that property's own leasing site (name matches, located in Austin) — search results and even Places sometimes return an aggregator page, a management-company umbrella site, or the wrong same-named property. If you can't confidently resolve it, flag it for me rather than guessing.
1. **Fingerprint the backend.** Determine which property-management / listing platform the site runs on (e.g., Entrata, Yardi RENTCafé, RealPage/OneSite, AppFolio, Funnel, or a custom site). Use URL patterns, page source, and network calls.
   - **The homepage is usually not enough.** Pricing data typically lives on a dedicated sub-page (commonly `/floor-plans/`, `/floorplans`, `/availability`, or `/pricing`) — the agent should locate this page (via nav links or a site search) rather than assume the root URL exposes it, and should record which page it found the data on.
2. **Find the data endpoint.** Open that pricing/floor-plans page in the browser, watch the network tab, and locate the JSON/XHR request that returns floor plans, units, availability, and pricing. **Prefer hitting that structured endpoint directly** over parsing rendered HTML — it's cheaper, cleaner, and more stable.
   - Note: some platforms (e.g., Entrata) embed this as a PHP `print_r`-style text dump inside the HTML rather than clean JSON. Write a small parser per format as needed — don't assume `json.loads()` will always work.
   - **Capture data per floor-plan / unit-type, not just per-property.** The same base floor plan often has multiple variants (e.g., "B1" vs. "B1-SHARED") with different prices, availability, and comments — each is a distinct row in the output.
   - **Treat each floor plan's status/comment field as first-class data, not noise.** These fields often mix availability status (e.g., "SOLD OUT," "1 spot left") with pricing promos (e.g., "FLASH SALE — LIMITED TIME"). Preserve the raw text in `concessions_raw` and attempt to separate the promo portion from the pure availability portion.
3. **Fall back to the rendered DOM** only if no clean endpoint exists.
4. **If no price is publicly shown**, set `price_status = not_publicly_listed` and stop. Do NOT fall back to Apartments.com / Zillow / Rent.com / RentCollegePads or any campus directory (rebuild rule, 2026-11-18). A local realtor / property-manager firm's own page for the building (e.g. Uptown Realty) is a valid source. Never scrape Reddit, Craigslist, or Facebook.

## Fields to capture (CSV schema)
`property_name, address, unit_or_floorplan_label, beds, baths, sqft, base_rent, total_price_with_mandatory_fees, price_basis, concessions_raw, concessions_type, concessions_value, availability, layout_image_url, price_image_url, concessions_image_url, source_url, source_type, price_status, scraped_at`

- **base_rent vs total_price_with_mandatory_fees:** capture both when both are shown; `price_basis` records which a given number represents (`base` or `total`). (Context: an FTC order requires Greystar-managed properties to show the total including mandatory fees, but other managers may show base rent only, and aggregators often show base rent.)
- **Image columns** (`layout_image_url`, `price_image_url`, `concessions_image_url`): see "Image handling" below.
- **Concessions/specials push price DOWN and are separate from fees, which push it UP.** Capture advertised discounts/specials — including ones in pop-ups, banners, or "X weeks free" text — as `concessions_raw` (verbatim), `concessions_type` (e.g. `months_free`, `flat_discount`, `waived_fee`), and `concessions_value` (parsed number where possible).
- `price_status` = `listed` or `not_publicly_listed`.

## Image handling
Three URL columns, captured per row (blank when the site exposes nothing):
- **`layout_image_url`** — the floor-plan/layout image for that unit or floor plan. Prefer image fields in the JSON payload (e.g. ACC `Attributes[].ImageURL`, SightMap `floor_plans[].image_url`, Knock `layouts[].images[].url`, RealPage `floorPlanImages[]`, WP-Entrata `thumbnail.url` / GMH `image.url`). For DOM/static-HTML backends, read the plan card's `<img>`: highest-res `srcset` candidate first, then `data-src` (lazy loaders), then `src`; always resolve to an absolute URL. Where a listing feed has only unit photos (AppFolio/Duda), the first listing photo is used. Static sites that name plan images after the plan (Resolute `A1Floorplan.png`, VSG `4B2.webp`, 9HUNDRED, ion `…-D1.png`, SGS `_bedsxbathsxsqft`, Spearhead sqft-in-filename) are matched by filename token.
- **`price_image_url`** — populated only when a backend renders the price itself as an image rather than DOM text (Westside pages were the known case; their extractor matches content images named `price|rent|rate|month`). As of 2026-07 the Westside pages (Envoy, Hyde Park Court) were redesigned and prices are now DOM text in elementor icon-lists (without a `$`, so the prose regex misses them — the `image_price_note` config entries are stale). Column stays blank until a price-as-image case reappears.
- **`concessions_image_url`** — populated when a promo/concession is image-only. Known case: Entrata ProspectPortal "splash" popups (image-only promo modals); the splash image URL is attached to rows whose concession comes from the splash (rows with their own floor-plan special keep it blank).
- RealPage `dimg` CDN URLs embed a `%s` size-token slot; substitute `{maxWidth}x{maxHeight}` (verified working, e.g. `/api/v1/dimg/700x700/...`).
- Weekly runs stay deterministic: no vision/LLM calls; image URLs are captured, never OCR'd.

## Build discipline
- **Before writing any new extractor, check what already exists.** If `properties_config.json` and `extractors/` already exist in this project (from a prior batch), read them first. If a new property's site fingerprints as a backend you've already built (e.g. Entrata, an ACC-style JSON API, SightMap, AppFolio), **reuse the existing extractor** — just add the property as a new entry in `properties_config.json`. Only write a new extractor for a genuinely new backend you haven't seen before. Do not create a second, near-duplicate extractor for a backend that already has one.
- Cluster the seed list by backend and build **one extractor per backend**, verified against a few examples, before generalizing. Do not write 150 one-off scripts.
- Work **incrementally**: process one property at a time and append results to the CSV/disk as you go, so a long run can resume after interruption. Log each property's detected backend and any failures.
- After building an extractor, **verify**: pull a few extracted prices and check them against what's visibly on the page (use a screenshot to self-check), then report a short QC summary (counts, backends found, failures, low-confidence rows).
- After each batch, report whether any properties reused an existing extractor vs. needed a new one, so I can spot accidental duplication.

## Compliance & politeness (hard rules)
- Capture only **publicly displayed** data.
- Respect robots.txt. Rate-limit (low concurrency + short delays). Use a real, honest User-Agent.
- **Do not attempt to bypass CAPTCHAs, bot walls, or login/auth screens.** If you hit one, stop and ask me to handle it.

## When to stop and ask me
- A CAPTCHA, bot wall, or login blocks you.
- A property's correct website is ambiguous or missing a URL.
- An extractor's verification shows prices that don't match the page.

## Output
Write the final CSV and the `properties_config` to `/mnt/user-data/outputs/` (or the project's `output/` folder). Keep `run.py` runnable standalone for the weekly job.
