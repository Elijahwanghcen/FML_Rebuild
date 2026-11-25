# Austin lease scraper migration

Read-only comparison of the Austin lease scrapers in [FML_Data](https://github.com/Elijahwanghcen/FML_Data) (`austin_leases_units/scraper`, commit on `main` as of 2026-11-25) and this repo, FML_Rebuild (`main` at `effa13a`). Nothing in either repo's `main` was modified. No Algolia or Rate My Rent call was made. No CAPTCHA or Cloudflare challenge was bypassed. Playwright is not installed in this environment, so browser extractors were not executed. HTTP extractors were called for ten buildings that answer without a browser.

The data contract is `austin_leases_units/scraper/output/csv outputs/advertised_prices_2026-11-17.csv`: **2,661 rows, 20 columns, 140 distinct `property_name` values**. `properties_config.json` lists **145 properties**. The two lists are not the same set. The CSV also contains French House Co-op and Arrakis Co-op (2 rows each), which are not in the 145. Six config names are missing from the CSV because the export uses a shorter name (`Haus 535`, `Ballpark East`, `Lantern Lane Condominiums`, `Preservation Square Apartment Homes`). Six more config buildings have no rows in the file at all (Town Lake Condos, Town Lake Apartments, Town Lake at Austin, Venue on Guadalupe, Texan 26, Tower View Apartments). A lossless migration has to reproduce the file, including those extra co-op rows.

`http_extractors.py` is byte-identical in both repos. `dom_extract.js` differs only in how long a Cloudflare interstitial is allowed to sit, and in an optional persistent browser profile. That wait does not solve a challenge. `run.py` in FML_Data has `clean_dedupe_rows`; the vendored copy in `reference/legacy_ut_scraper/run.py` does not. `properties_config.json` differs only on Torre's `force_not_listed` flag, Icon's `clean_labels` flag, and the Quarters, GrandMarc, and Inspire URLs.

## 1. How FML_Rebuild works

### Architecture

Listings are the last stage of a campus pipeline (`aggregator/run_campus.sh`). Discovery, address resolution, and roster selection run first. Then:

| Stage | Script | What it does |
|---|---|---|
| Crawl | `aggregator/enrich_site.py` | Saves HTML under `data/<campus>/raw/<slug>/` and tags platforms with a regex fingerprint |
| Build | `aggregator/enrich_listings.py` | Calls `listing_adapters.extract()`, keeps the candidate with the most priced rows, writes `listing_config.json` |
| Publish | `aggregator/build_json.py` | Flattens winners into `data/<campus>/out/units.json` and sets a building-level `price_status` |
| Weekly | `aggregator/refresh_listings.py` | Re-runs only the frozen config. No detection, no LLM, one fetch per `source_id`, 4 second delay per host, failure stub if a building returns nothing |

The same scripts run for UT Austin and Texas A&M. Campus files live in `campuses/<slug>.json` and `data/<slug>/`. There is no scraper manager, no shard coordinator, and no CSV writer. Checked-in UT output is 150 buildings and 2,219 unit rows. The frozen listing config has 103 properties.

### Extractors

`aggregator/listing_adapters.py` imports the vendored extractors at `reference/legacy_ut_scraper/extractors/` and adds its own. `detect()` builds an ordered candidate list:

1. `HOST_ADAPTERS` (and a campus `listing_adapters` map, empty today) by registrable host.
2. HTML markers: ACC lightning id, wp-json Entrata, RealPage CMS callback, SightMap, Knock, Jonah `jd-fp`, AppFolio, Duda, Webflow, Repli360 script, RentCafe, JSON-LD, Elementor, university `.edu` rate tables, Entrata portal links and iframes, plus DOM layout markers (`entrata_pp`, `landmark`, `yugo`, `villas_wp`, `ion_wp`, `g5_sniff`, `realpage_sniff`, and the rest of `DOM_BACKENDS`).
3. If nothing matched, `aggregator/fingerprint.js` records XHR URLs and `NET_RULES` maps them to `sightmap`, `knock_doorway`, `acc_lightning`, `wp_entrata_json`, `realpage_cms_proxy`, `g5_sniff`, `cg_synergy`, or `realpage_sniff`.
4. `text_plan_list` reads plan lines out of the saved HTML.
5. A hand-saved `data/<campus>/rescues/<slug>.json` competes as `headed_rescue`.

The winner is the candidate with the most priced rows, then the most rows. DOM candidates are skipped once any candidate already has a priced row. `convert()` turns a legacy row into a Rebuild unit row.

HTTP backends call `http_extractors.EXTRACTORS`. DOM backends shell out to `node dom_extract.js`. Rebuild-only backends are `appfolio_smart`, `rentcafe_inline`, `repli360_feed`, `text_plan_list`, `jsonld_offers`, `jsonld_floorplans`, `elementor_fp_posts`, `university_rates`, `advertised_range`, `cg_synergy`, `buildium_search`, and `headed_rescue`.

These FML_Data backends exist in the vendored file and are **not** selected by `detect()` or `HOST_ADAPTERS`: `ut_housing_nueces`, `ut_housing_dobie`, `ut_rates_table`, `collegehouses_rates`, `ut_offcampus_directory`, `no_public_pricing`. `jonah_chunk` is a DOM sniffer with no property using it. Campus-directory URLs are skipped on purpose (`common.is_ils`).

### Fingerprints

Three different fingerprints exist, and only one of them routes a building:

- `aggregator/fingerprint.js` watches network calls. Platform ids: `entrata`, `realpage`, `rentcafe`, `appfolio`, `funnel`, `knock`, `peak`, `americancampus`, `landmark`, `cardinal`, `greystar`, `sightmap`, `engrain`, `anyonehome`, `udr`, `buildium`, `rentmanager`, `wordpress`, plus `entrata_embed`. Routing uses `NET_RULES`, not these ids directly.
- `enrich_site.py` stores a smaller regex platform list on `meta.json`. That list is informational.
- `FEED_MARKERS` in `listing_adapters.py` flags "a feed was visible and no adapter returned rows" in the QC report.

FML_Data's `scraper/fingerprints/*.json` files are the old batch captures used to pick a backend by hand. Rebuild runs the ported script only when HTML markers miss.

### Output schema

A unit row in `out/units.json` has `objectID` (`{slug}__{index}`), `property_objectID`, `name`, `beds`, `baths`, `sqft`, `price_min`, `price_max`, `price_label`, `rent_basis` (`per_bed` or `per_unit`), `availability`, `concession`, `base_rent`, `total_price_with_mandatory_fees`, `price_basis`, `concessions_type`, `concessions_value`, `price_image_url`, `concessions_image_url`, `layout_image_url`, `source_url`, `source_type` (always `first_party_site`), `adapter`, and `scraped_at` (date only on refresh). Building name, address, and `price_status` live on `buildings.json`. A failed refresh writes one stub row whose `name` is `(extraction failed)` and whose `price_status` is `not_publicly_listed`.

### How a building is added

1. Discovery or `apply_resolutions.py` puts the building on the roster, with an optional `floorplans_url` or `appfolio_portal`.
2. `enrich_site.py` crawls it.
3. `enrich_listings.py` lets `detect()` choose the backend and freezes `listing_config.json` (`objectID`, `property_name`, `address`, `building_type`, `source_id`, `backend`, `url`, `params`).
4. After that, `refresh_listings.py <campus>` is the weekly path.

A new platform is a marker in `detect()` plus an extractor. A one-off manager site is a host entry in `HOST_ADAPTERS` or `campuses/<slug>.json` under `listing_adapters`. There is no hand-written per-building file equivalent to `properties_config.json` on the weekly path. The frozen config is whatever won the last build.

### Bot walls

`solve_blocked.py` opens a visible Chromium window and waits for a person. `rescue_from_page.py` re-parses HTML saved by the Chrome extension. `dom_extract.js` reports `blocked_bot_wall` when the title stays on "Just a moment", "Attention required", or "Access denied". The code does not solve a challenge. Rescues are raw row JSON. They do not apply FML_Data's `split_total`, `base_only`, `installment`, `promo_current`, `unpriced`, or `empty` price modes.

## 2. How FML_Data's scraper works

### Architecture

`python3 run.py` in `austin_leases_units/scraper/`:

1. Loads `properties_config.json` (`backends` + `properties`, 145 entries, 41 backends).
2. For each property, dispatches on `backends[id].type`. `http` calls `http_extractors.EXTRACTORS[backend](url, params)`. `dom` runs `node extractors/dom_extract.js`.
3. DOM work is cached per `source_id` so sister buildings share one browser session. HTTP GETs are cached by URL.
4. Same host as the previous property waits 4 seconds.
5. If `params.clean_labels` is set, `clean_dedupe_rows()` merges overlapping Entrata cards. Only Icon at Austin sets this.
6. A failure or an empty extract becomes one placeholder row with `price_status=not_publicly_listed`.
7. Every row is stamped with `property_name`, `address`, `source_url` (the config URL), `source_type` (default `first_party`), and `scraped_at` (full ISO timestamp).
8. Writes `output/advertised_prices_YYYY-MM-DD.json` and `output/csv outputs/advertised_prices_YYYY-MM-DD.csv`.

The backend is chosen by hand and stored on the property. Fingerprints under `scraper/fingerprints/` were a one-time aid for that choice. They are not consulted at run time.

### Extractors

41 backends. HTTP: `acc_lightning`, `wp_entrata_json`, `ut_housing_nueces`, `ut_housing_dobie`, `appfolio_listings`, `sightmap`, `webflow_product7`, `webflow_cms_floorplans`, `knock_doorway`, `duda_appfolio_feed`, `ut_offcampus_directory`, `spearhead_static`, `resolute_static`, `ninehundred_static`, `sgs_static`, `mmc_ajax`, `vsg_static`, `fp_units_modal_v2`, `vnue_grid_static`, `no_public_pricing`, `jonah_detail_json`, `realpage_cms_proxy`, `ut_rates_table`, `collegehouses_rates`, `ballpark_static`, `westside_prose`, `uptown_realty`.

DOM parsers: `entrata_pp`, `landmark`, `rambler_lvbode`, `sinclair_wp`, `repli360`, `yugo`, `ion_wp`, `villas_wp`, `rentcafe_ysi`, `gogetter_wc_floorplans`, `rise_units`. DOM sniffers: `g5_sniff`, `realpage_sniff`, `jonah_chunk` (defined, unused by the 145).

`villas_wp` reads `.floor-plan-card`, `.floor-plan-card__title`, and `.leaseleads-price-stroke`. That markup is gone. See section 5.

### Output schema

The CSV header, in order:

`property_name`, `address`, `unit_or_floorplan_label`, `beds`, `baths`, `sqft`, `base_rent`, `total_price_with_mandatory_fees`, `price_basis`, `concessions_raw`, `concessions_type`, `concessions_value`, `availability`, `layout_image_url`, `price_image_url`, `concessions_image_url`, `source_url`, `source_type`, `price_status`, `scraped_at`.

Filled cells in the 2026-11-17 file: every row has property, address, label, source URL, and timestamp. `beds` 2,650, `baths` 2,594, `sqft` 2,249, `base_rent` 2,314, `availability` 2,655, `layout_image_url` 2,412. `price_basis` 1,730 (`base` 1,382, `total` 348). `total_price_with_mandatory_fees` 348. `concessions_type` 429, `concessions_value` 259, `concessions_raw` 0. `price_image_url` 0, `concessions_image_url` 0. `source_type` and `price_status` are filled on 2,180 rows and blank on 481. `source_type` values: `first_party` 2,054, blank 481, `managing_broker_site` 116, `third_party_directory` 10. `price_status`: `listed` 1,730, blank 481, `not_publicly_listed` 450. `price_basis` is `base`, `total`, or empty. No rent in the file is under $100 (`MIN_PLAUSIBLE_RENT`).

A fresh `run.py` stamps `price_status` and `source_type` on every row, including failures. The 481 blank rows are a property of this file. `docs/SUPER_REBUILD_PLAN.md` describes the file as a live-catalog export with team edits on top of the last full scrape (2026-09-29). The blank statuses and the Quarters URLs (below) match that description. The migration still has to reproduce the file as it sits.

### How a building is added

Add an object to `properties`: `property_name`, `address`, `source_id`, `url`, `backend`, `params`, optional `source_type`. Reuse a backend when the page matches one. A new platform needs a `backends` entry and an extractor function. `source_id` is the shared-fetch key.

### Downstream feeds

`tools/rmr-discrepancy-updater/discrepancy_updater.py` does not read the CSV. It reads an Algolia-shaped unit JSON (`--scrape`, typically `austin_leases_units/master/algolia_units_*.json`) plus `output/run_log.txt`. Matching uses `unit_label`, `beds`, `baths`, `sqft`, `base_rent`, `availability`, `layout_image_url`, `price_status`, and `objectID`. `austin_leases_units/master/austin_leases_algolia_push.py` builds that JSON from `advertised_prices_*.json`. Its `objectID` is `{property-slug}__{label-slug}` with an optional sqft suffix. Rebuild's `objectID` is `{slug}__{row-index}`. Those ids are not interchangeable. This comparison did not run either publisher.

### Rescue

`ingest_headed_rescues.py` does not scrape. It maps already-saved rescue JSON onto a snapshot. Modes: `split_total` (prefer the monthly total), `base_only`, `installment`, `promo_current` (struck price becomes a `flat_discount`), `unpriced`, and `empty` (Quarters bot-wall inventories become a single unpriced stub). `dom_extract.js` also retries a blocked URL once inside the same browser session after another page has loaded. A title that stays on a challenge returns `blocked_bot_wall` and stops.

## 3. Per-building coverage

145 rows from `properties_config.json`. Columns are the building, the FML_Data backend, the Rebuild extractor that current routing would use, confidence, and risk of losing rows or fields relative to the 2026-11-17 file.

Confidence:

- **high** — the same extractor is selected by `detect()` or `HOST_ADAPTERS`, and nothing in this review shows it returning empty.
- **medium** — a wired substitute (`appfolio_smart`, `rentcafe_inline`, `repli360_feed`) or the same DOM parser with a bot wall or a filter that is not copied from `params`.
- **low** — the dedicated parser is not routed, the URL or flag has drifted, or the selector returns no rows.

Risk:

- **low** — row shape should match the current extractor.
- **medium** — which units survive can change (shared ACC filter, AppFolio address filter, Repli360 feed vs DOM, Uptown pages absent from the 150-building roster).
- **high** — rows or prices can disappear, or the wrong page is scraped.

Confidence counts: **81 high, 37 medium, 27 low**. Risk counts: **40 low, 77 medium, 28 high**. **114** would keep the same backend name. **20** would be handed to a substitute. **11** have no rent extractor (`none`). A weekly run of today's `data/ut_austin/listing_config.json` is a smaller set: 103 frozen properties, of which 64 names match this roster and 42 froze the same backend. Code that *can* route a building is not the same thing as a building already on the weekly refresh.

| Building | FML_Data backend | Rebuild extractor | Confidence | Risk of data loss |
|---|---|---|---|---|
| The Block on 25th East | `acc_lightning` | `acc_lightning` | high | medium |
| The Block on 25th West | `acc_lightning` | `acc_lightning` | high | medium |
| The Block on 28th | `acc_lightning` | `acc_lightning` | high | medium |
| The Block on Pearl North | `acc_lightning` | `acc_lightning` | high | medium |
| The Block on Pearl South | `acc_lightning` | `acc_lightning` | high | medium |
| The Block 23 | `acc_lightning` | `acc_lightning` | high | medium |
| 26 West | `acc_lightning` | `acc_lightning` | high | low |
| Crest at Pearl | `acc_lightning` | `acc_lightning` | high | low |
| The Castilian | `acc_lightning` | `acc_lightning` | high | low |
| Callaway House | `acc_lightning` | `acc_lightning` | high | low |
| Quarters on Campus – Grayson | `entrata_pp` | `entrata_pp` | low | high |
| Quarters on Campus – Nueces | `entrata_pp` | `entrata_pp` | low | high |
| Quarters on Campus – Karnes House | `entrata_pp` | `entrata_pp` | low | high |
| Quarters on Campus – Sterling House | `entrata_pp` | `entrata_pp` | low | high |
| Skyloft Austin | `fp_units_modal_v2` | `fp_units_modal_v2` | high | low |
| 1883 at Cameron House | `entrata_pp` | `entrata_pp` | medium | high |
| 21 Rio | `wp_entrata_json` | `wp_entrata_json` | high | low |
| 2400 Nueces | `ut_housing_nueces` | `university_rates` | low | high |
| Dobie Twenty21 | `ut_housing_dobie` | `university_rates` | low | high |
| The Standard | `landmark` | `landmark` | high | low |
| The Nine at West Campus | `landmark` | `landmark` | high | low |
| Rambler Apartments | `rambler_lvbode` | `rambler_lvbode` | high | low |
| The Sinclair | `sinclair_wp` | `sinclair_wp` | high | low |
| Marq on Burnet | `repli360` | `repli360_feed` | medium | medium |
| Sabina Condominiums | `repli360` | `repli360_feed` | medium | medium |
| The Sondery | `sightmap` | `sightmap` | high | low |
| Yugo Austin Rio | `yugo` | `yugo` | medium | medium |
| Villas on Guadalupe | `villas_wp` | `villas_wp` | low | high |
| Montage Apartments | `appfolio_listings` | `appfolio_smart` | medium | medium |
| Oak Grove Apartments | `spearhead_static` | `spearhead_static` | high | low |
| Avon at 22nd | `appfolio_listings` | `appfolio_smart` | medium | medium |
| The Marian Condominiums | `resolute_static` | `resolute_static` | high | low |
| 9HUNDRED | `ninehundred_static` | `ninehundred_static` | high | low |
| West Campus Elloras | `ut_offcampus_directory` | none | low | high |
| Penthouse Apartments | `duda_appfolio_feed` | `duda_appfolio_feed` | medium | medium |
| Point North | `entrata_pp` | `entrata_pp` | medium | high |
| Aura Thirty2 | `rentcafe_ysi` | `rentcafe_inline` | medium | medium |
| Troubadour | `jonah_detail_json` | `jonah_detail_json` | high | low |
| Presidium Tech Ridge Apartments | `sightmap` | `sightmap` | high | low |
| High Point Preserve | `rentcafe_ysi` | `rentcafe_inline` | medium | medium |
| The Waller | `entrata_pp` | `entrata_pp` | medium | high |
| Promontory Point | `g5_sniff` | `g5_sniff` | medium | medium |
| Hillside Creek | `rentcafe_ysi` | `rentcafe_inline` | medium | medium |
| Keystone Apartments | `knock_doorway` | `knock_doorway` | high | low |
| Preserve at Wells Branch | `knock_doorway` | `knock_doorway` | high | low |
| Oaks at Chisholm Trail | `realpage_sniff` | `realpage_sniff` | medium | medium |
| Redpoint San Marcos | `ion_wp` | `ion_wp` | medium | medium |
| VEER Apartments | `appfolio_listings` | `appfolio_smart` | medium | medium |
| San Gabriel Square | `sgs_static` | `sgs_static` | high | low |
| Duval Villas | `rentcafe_ysi` | `rentcafe_inline` | medium | medium |
| Estates at East Riverside | `jonah_detail_json` | `jonah_detail_json` | high | low |
| Ballpark East (Collective on Riverside) | `rentcafe_ysi` | `rentcafe_inline` | medium | medium |
| Town Lake Condos | `no_public_pricing` | none | low | medium |
| 24 Longview | `webflow_product7` | `webflow_product7` | high | low |
| 21 Pearl | `villas_wp` | `villas_wp` | low | high |
| Axis West Campus | `villas_wp` | `villas_wp` | low | high |
| Elan East Apartments | `realpage_cms_proxy` | `realpage_cms_proxy` | high | low |
| GrandMarc Austin | `entrata_pp` | `entrata_pp` | low | high |
| Haus 535 (Haus 5350) | `jonah_detail_json` | `jonah_detail_json` | high | low |
| Ion Austin | `ion_wp` | `ion_wp` | medium | medium |
| The Mark Austin | `landmark` | `landmark` | high | low |
| Moontower | `landmark` | `landmark` | high | low |
| Regents West at 24th | `repli360` | `repli360_feed` | medium | medium |
| Regents West at 26th | `repli360` | `repli360_feed` | medium | medium |
| The Nine at Rio | `landmark` | `landmark` | high | low |
| Signature 1909 | `villas_wp` | `villas_wp` | low | high |
| Rise at West Campus | `rise_units` | `rise_units` | high | low |
| Torre | `wp_entrata_json` | `wp_entrata_json` | low | high |
| Twenty Two15 | `entrata_pp` | `entrata_pp` | medium | high |
| Union on 24th | `entrata_pp` | `entrata_pp` | medium | high |
| Union on San Antonio | `entrata_pp` | `entrata_pp` | medium | high |
| Venue on Guadalupe | `no_public_pricing` | none | low | medium |
| Villas on 24th | `wp_entrata_json` | `wp_entrata_json` | high | low |
| Villas on 26th | `vnue_grid_static` | `vnue_grid_static` | high | low |
| Villas on Nueces | `mmc_ajax` | `mmc_ajax` | high | low |
| Villas on Rio | `sinclair_wp` | `sinclair_wp` | high | low |
| Villas at San Gabriel | `vsg_static` | `vsg_static` | high | low |
| Yugo Austin Corner | `yugo` | `yugo` | medium | medium |
| Yugo Austin Nueces | `yugo` | `yugo` | medium | medium |
| Yugo Austin Waterloo | `yugo` | `yugo` | medium | medium |
| Inspire on 22nd | `entrata_pp` | `entrata_pp` | low | high |
| Lark Austin | `ion_wp` | `ion_wp` | medium | medium |
| Lone Star Lofts | `appfolio_listings` | `appfolio_smart` | medium | medium |
| Tradition on Rio | `landmark` | `landmark` | high | low |
| Texan Pearl | `duda_appfolio_feed` | `duda_appfolio_feed` | medium | medium |
| Noble 2500 | `gogetter_wc_floorplans` | `gogetter_wc_floorplans` | medium | medium |
| Sparq on Rio | `webflow_cms_floorplans` | `webflow_cms_floorplans` | high | low |
| Texan & Vintage West Campus | `acc_lightning` | `acc_lightning` | high | low |
| Buena Vista Condominiums | `ut_offcampus_directory` | none | low | high |
| Texan 26 | `no_public_pricing` | none | low | medium |
| Envoy Apartments | `westside_prose` | `westside_prose` | medium | medium |
| Camino Flats | `realpage_cms_proxy` | `realpage_cms_proxy` | high | low |
| East Campus Graduate Apartments | `ut_rates_table` | `university_rates` | low | high |
| Leon Place Condominiums | `appfolio_listings` | `appfolio_smart` | medium | medium |
| Legacy on Rio | `landmark` | `landmark` | high | low |
| Hilltop | `wp_entrata_json` | `wp_entrata_json` | high | low |
| The Block on Rio | `acc_lightning` | `acc_lightning` | high | medium |
| The Block on Leon | `acc_lightning` | `acc_lightning` | high | medium |
| Icon at Austin | `entrata_pp` | `entrata_pp` | low | high |
| Town Lake Apartments | `no_public_pricing` | none | low | medium |
| 1883 at Montgomery House | `entrata_pp` | `entrata_pp` | medium | high |
| Marq Uptown | `repli360` | `repli360_feed` | medium | medium |
| Hyde Park Court | `westside_prose` | `westside_prose` | medium | medium |
| Ballpark North | `ballpark_static` | `ballpark_static` | high | low |
| Village at East Riverside | `jonah_detail_json` | `jonah_detail_json` | high | low |
| Town Lake at Austin | `no_public_pricing` | none | low | medium |
| Gateway Apartments | `ut_rates_table` | `university_rates` | low | high |
| Laurel House Co-op | `collegehouses_rates` | none | low | high |
| Nueces Co-op | `collegehouses_rates` | none | low | high |
| Halstead Co-op | `collegehouses_rates` | none | low | high |
| Vanderbilt Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Texan Shoal Creek Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Escala Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Dos Rios | `uptown_realty` | `uptown_realty` | high | medium |
| Treehouse Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Pecan Square Apartments | `uptown_realty` | `uptown_realty` | high | medium |
| Landmark Square | `uptown_realty` | `uptown_realty` | high | medium |
| Wedgewood Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Piazza Navona Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Greenwood Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| West Campus Flats | `uptown_realty` | `uptown_realty` | high | medium |
| 1907 Robbins Place Apartments | `uptown_realty` | `uptown_realty` | high | medium |
| Lantern Lane Condominiums (Unit 302) | `uptown_realty` | `uptown_realty` | high | medium |
| Lantern Lane Condominiums (Unit 203) | `uptown_realty` | `uptown_realty` | high | medium |
| Littlefield Apartments | `uptown_realty` | `uptown_realty` | high | medium |
| Galileo Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| San Pedro Flats | `uptown_realty` | `uptown_realty` | high | medium |
| Tom Green Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Park Place Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Centennial Condos | `uptown_realty` | `uptown_realty` | high | medium |
| Waterford Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Pecan Walks | `uptown_realty` | `uptown_realty` | high | medium |
| Orange Tree Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Gables Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Speedway Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| 3000 Guadalupe St | `uptown_realty` | `uptown_realty` | high | medium |
| Croix Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Palmetto Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Parapet Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Texan Tower | `uptown_realty` | `uptown_realty` | high | medium |
| Delphi Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Windtree Condominiums | `uptown_realty` | `uptown_realty` | high | medium |
| Nueces Corner Condos | `uptown_realty` | `uptown_realty` | high | medium |
| Tower View Apartments | `no_public_pricing` | none | low | medium |
| Preservation Square | `appfolio_listings` | `appfolio_smart` | medium | medium |

## 4. Field mapping

`listing_adapters.convert()` is the only bridge from a legacy row to a Rebuild unit. HTTP extractors being identical means the loss is in this function, in the missing CSV writer, and in the Algolia id, not in the HTTP parsers.

| FML_Data CSV column | Rebuild field | What happens |
|---|---|---|
| `property_name` | `buildings.json` `canonical_name` | Moved off the unit row. A CSV export has to join it back. |
| `address` | `buildings.json` `address` | Moved off the unit row. |
| `unit_or_floorplan_label` | `name` | Renamed. Empty labels and labels starting with `(` are dropped before convert. |
| `beds` | `beds` | Kept, coerced to a number. The 11-17 file has no non-numeric bed counts other than 11 blanks. |
| `baths` | `baths` | Kept, coerced to a number. |
| `sqft` | `sqft` | Kept. A range that is not a single number stays a string. |
| `base_rent` | `base_rent` and `price_min` | Kept. Values under $100 become null. This file has none. |
| `total_price_with_mandatory_fees` | same field, also appended into `price_label` | Kept. 348 rows use it. |
| `price_basis` | `price_basis` | Kept (`base` or `total`). `rent_basis` is an extra `per_bed` / `per_unit` tag. It does not replace `price_basis`. |
| `concessions_raw` | `concession` | Renamed. The column is empty in this CSV (0 cells) and still has to round-trip. |
| `concessions_type` | `concessions_type` | Kept. |
| `concessions_value` | `concessions_value` | Kept, coerced to a number. |
| `availability` | `availability` | Kept. A phrase `advertised range $a-$b` also sets `price_max`. |
| `layout_image_url` | `layout_image_url` | Kept. `plan_images.py` can fill gaps from saved HTML. |
| `price_image_url` | `price_image_url` | Kept by convert. Empty in this CSV. |
| `concessions_image_url` | `concessions_image_url` | Kept by convert. Empty in this CSV. Entrata splash images are the historical source. |
| `source_url` | `source_url` | Kept, but it becomes the adapter URL. Detection can point it at a different page than the config URL. |
| `source_type` | `source_type` | **Lossy.** Always written as `first_party_site`. The file uses `first_party` (2,054), blank (481), `managing_broker_site` (116), and `third_party_directory` (10). |
| `price_status` | absent on a successful unit row | **Dropped.** `convert()` does not copy it. Failure stubs and `buildings.json` have it. The file has `listed` 1,730, blank 481, `not_publicly_listed` 450. The discrepancy updater reads this field. |
| `scraped_at` | `scraped_at` | Precision loss. The CSV has a full ISO timestamp with offset. Refresh writes `YYYY-MM-DD`. |

Fields Rebuild adds, which the CSV writer must not require consumers to understand: `objectID`, `property_objectID`, `price_min`, `price_max`, `price_label`, `rent_basis`, `adapter`.

The Algolia `objectID` (`{property-slug}__{label-slug}`) is not produced. Publishing Rebuild's `{slug}__{index}` ids would make the discrepancy updater treat existing units as new.

## 5. Gaps FML_Data handles and Rebuild does not

### Torre `force_not_listed`

Both copies of `wp_entrata_json` honor `params.force_not_listed` by clearing `base_rent` and `price_basis` and setting `price_status` to `not_publicly_listed`. FML_Data's live Torre entry calls `https://torreatx.com/wp-json/gmh-student/floorplans/categories` and does **not** set the flag. The vendored config still sets `force_not_listed: true`, which would blank the rents. The 11-17 file has 47 Torre rows, every one `not_publicly_listed`, and every one still has a `base_rent` (sample 3015, 2750, 1420). Neither current code path produces that combination: the flag clears the rent, and omitting the flag marks the row `listed`.

`detect()` only probes `/wp-json/theme/entrata/v1/floor-plans`. It will not find the GMH categories URL, so Torre is not actually auto-routed.

Lossless behavior for this file is "keep the rent and keep `not_publicly_listed`". That wants an explicit policy, not a silent re-scrape.

### Icon `clean_labels`

`clean_dedupe_rows()` in FML_Data `run.py` strips glued card text (`Studio`, `N Beds`, `Call for Pricing`) and merges copies of the same plan, keeping whichever copy has the image. Icon at Austin is the only property with `params.clean_labels: true`. The vendored `run.py` deleted the function, and the vendored config deleted the flag. `convert()` does not merge rows. The 11-17 file has 33 Icon rows, all `not_publicly_listed`, none priced. A fresh Entrata scrape without the merge can emit the same plan two or three times.

### Moved Quarters, GrandMarc, and Inspire URLs

| Building | FML_Data config now | Vendored Rebuild config | URL on the 11-17 rows | Frozen UT listing config |
|---|---|---|---|---|
| Quarters Grayson | `quartersoncampus.com/austin/grayson/student/` | `.../graysonhouse/austin/grayson/student/` | graysonhouse path | not pinned to the new path |
| Quarters Nueces | `/austin/nueces/student/` | `/nueceshouse/austin/nueces/student/` | nueceshouse path | not pinned |
| Quarters Sterling | `/austin/sterling/student/` | `/sterlinghouse/austin/sterling/student/` | sterlinghouse path | not pinned |
| Quarters Karnes | `/karneshouse/austin/karnes/student/` | same karneshouse path | karneshouse path | not pinned |
| GrandMarc Austin | `entrata.grandmarcaustin.com/.../student/` via `entrata_pp` | `www.grandmarcaustin.com/floor-plans` via `webflow_cms_floorplans` | entrata host | not pinned to the portal |
| Inspire on 22nd | `entrata.inspire22nd.com/.../student/` via `entrata_pp` | `www.inspire22nd.com/.../student/` via `entrata_pp` | `www.inspire22nd.com/.../student/` | `text_plan_list` on `inspire22nd.com/floor-plans/` |

Karnes did not move. Grayson, Nueces, and Sterling moved in FML_Data only. GrandMarc's live backend went back to the Entrata portal; the vendored snapshot still has the September Webflow URL. Inspire's live URL is the `entrata.` portal; the frozen Rebuild result is a text fallback on the marketing floor-plans page. The September rescue log recorded all four Quarters inventories as `empty` after a real page load, and Inspire as a `base_only` rescue of 23 priced rows. Those rescue price modes are not in Rebuild.

### Bot-wall tiered rescue

FML_Data has two layers. Inside `dom_extract.js`, a blocked URL is retried once after a sister page in the same session has loaded, then the run stops with `blocked_bot_wall`. After the run, `ingest_headed_rescues.py` applies the six price modes above to JSON a person already saved. Rebuild has `solve_blocked.py` (visible window, human solves the challenge), `rescue_from_page.py`, and `headed_rescue`. It stores rows. It does not apply `split_total`, `promo_current`, `installment`, or `empty`. `entrata_pp` is still the right parser for 14 properties, and it is also the parser most likely to stop on a bot wall and lose the priced rows the CSV still holds (Quarters alone is 88 priced rows with blank `price_status`).

### `villas_wp` returns no rows

Confirmed on 2026-11-25 with a plain HTTP GET. No browser, no challenge wait. All four pages returned HTTP 200 and a normal title, not a Cloudflare interstitial.

The parser selects `.floor-plan-card`, `.floor-plan-card__title`, `.floor-plan-card__beds`, and `.leaseleads-price-stroke`. Those strings occur **zero** times on each page. The plans are now `data-ll-floor-plan-card` nodes. Each card carries `data-ll-floor-plan-lease-terms` JSON with `price`, `base_rent`, and `price_with_fees`. Card counts from that attribute: Villas on Guadalupe 45 (36 with a price), 21 Pearl 15 (13 priced), Axis West Campus 15 (7 priced), Signature 1909 18 (17 priced). Those counts match the CSV row counts (45, 15, 15, 18). `querySelectorAll('.floor-plan-card')` matches nothing, so the extractor returns no rows and a refresh would replace the frozen rows with a failure stub.

The frozen UT config still records a successful `villas_wp` pass on 2026-11-18 (45, 15, 15, and 18 rows). The template changed after that. A LeaseLeads attribute parser can read the new JSON without a browser. That is the smallest fix that recovers these four buildings.

### Other holes

- `collegehouses_rates` (Laurel, Nueces, Halstead) is never selected. French House and Arrakis are in the CSV and not in the 145.
- `ut_housing_nueces`, `ut_housing_dobie`, and `ut_rates_table` (East Campus Graduate, Gateway) are not selected. `university_rates` is a different, name-sectioned reader.
- `ut_offcampus_directory` (West Campus Elloras, Buena Vista) is refused as a directory source. The CSV still has rows for those names.
- `no_public_pricing` (six buildings) has no route. Four of them have zero CSV rows; the stub is the product.
- `repli360_feed` can beat DOM `repli360` on priced-row count while returning fewer plans (the November audit saw Sabina 78 vs 34 and Marq Uptown 70 vs 30).
- `appfolio_smart` rebuilds the address filter from the roster instead of `params.address_match`.
- Yugo's `gtm_name` is taken from the page title, not the config param.
- Shared ACC feeds depend on `acc_pick_location`. A missed `LocationFilter` mixes The Block buildings. The 11-17 file splits them by hand.

## 6. Phased migration

Acceptance for every phase: **zero lost rows and zero lost fields against `advertised_prices_2026-11-17.csv`**, after the renames in section 4 are applied in the comparison. A row present in the CSV and absent from the new output is a failure. A field that was filled and comes back empty is a failure. Extra rows are allowed only when the diff names them and a person accepts them. Blank `price_status` / `source_type` in the CSV count as values to preserve, not as permission to invent `listed`. Buildings whose live site has moved since 11-17 (the HTTP sample below) are called out as drift, not silently overwritten.

### Phase 0 — parity harness

A script, run by hand, that:

1. Takes a building list.
2. Runs the FML_Data extractor with that building's `url` and `params` (the pinned contract).
3. Runs Rebuild's `extract()` / `refresh` path for the same building.
4. Projects both sides onto the 20 CSV columns using the section 4 map, including a join for name and address and a real `price_status`.
5. Diffs row identity `(property_name, unit_or_floorplan_label, beds, baths, sqft)` and then each field.
6. Writes a markdown diff. It does not push anywhere.

The harness treats `blocked_bot_wall` as a skip, not as a success with zero rows. It must not launch a challenge solver. HTTP buildings can run in CI. DOM buildings run only where a browser profile already exists.

Phase 0 is done for a building when the diff is empty, or every remaining line is tagged `accepted-drift` with the old value and the new value.

### Order

1. **Pin and refresh the 81 high-confidence buildings**, HTTP and host-static first. The ten-building sample in the appendix is the seed. Shared ACC feeds stay one shard so `location_filter` is tested, not assumed.
2. **LeaseLeads attribute parser** for Villas on Guadalupe, 21 Pearl, Axis West Campus, Signature 1909. The prices are already in the HTML.
3. **Route the unrouted HTTP parsers** by host: `housing.utexas.edu` → `ut_housing_nueces` / `ut_housing_dobie` / `ut_rates_table`, `collegehouses.org` → `collegehouses_rates`. Pin `params.house`. Add French House and Arrakis if the rates page still lists them, because the CSV has them.
4. **Port `clean_labels` and decide Torre.** Apply the dedupe before convert. For Torre, pin the GMH URL and record an explicit rule for "rent present, status `not_publicly_listed`" so the flag cannot blank the file.
5. **Substitutes that can drop rows:** DOM `repli360` when `repli360_feed` returns fewer plans; copy `address_match` into AppFolio and Duda; copy Yugo `gtm_name`.
6. **Entrata and other bot walls last:** Quarters, GrandMarc, Inspire, Icon, Unions, 1883, Point North, The Waller. Pin the FML_Data URL. Port the rescue price modes. A bot wall stays a failure stub plus a rescue queue. It is never filled with `text_plan_list` rows if those rows fail the diff.
7. **Publisher.** Emit the 20-column CSV at the current path shape, and emit Algolia-shaped JSON whose `objectID` matches today's push script, for the discrepancy updater. The updater stays a dry run until a person approves a building.

### How to add a building after this

Add it once, in a pinned source file: `property_name`, `address`, `source_id`, `url`, `backend`, `params`. The manager tries that pin first. `detect()` and the network fingerprint still run, and they win only when the diff shows they gained priced rows without dropping a pinned field. A brand-new platform is a marker plus an extractor, then one building through the harness before the backend is reused. Discovery may propose a building. It does not enter the weekly set until the pin exists and the harness is clean.

## 7. End state: one manager, many bots

One process owns the roster and the output. Worker bots only scrape the shard they are given. They do not write the public files.

### Shards

Shard key is `(source_id, host)`, which is what `run.py` and `refresh_listings.py` already cache.

- One ACC `list_id` is one shard. The bot fetches the lightning payload once and fans out `location_filter` locally.
- One Entrata portal host is one shard, so the session cookie is reused and the in-session retry still works.
- Uptown, AppFolio portals, and college-houses rates are one shard per host.
- HTTP shards and DOM shards are separate pools. DOM concurrency stays at one browser per profile so two bots do not share `~/.fml_dom_profile`.

A shard is a JSON file: the property pins, the backend, the URL, and the params. The manager writes it. The bot returns rows in the legacy 20-field shape plus `adapter` and `status`.

### Routing

For each building the manager asks, in order:

1. The pinned backend and URL.
2. `detect()` markers.
3. `fingerprint.js` + `NET_RULES`, only if the pin returned nothing and the page is not a challenge.
4. A rescue file, if one is present.

The pin wins ties. A fingerprint route replaces the pin only when the harness shows more priced rows and no filled field went empty. `text_plan_list` is a candidate, never a silent replacement for `entrata_pp` or `villas_wp`.

### Merge

The manager is the only writer. It groups bot rows by `property_name`, applies `clean_labels` when the pin says so, applies Torre's status rule, and projects the section 4 schema. Sister buildings that share a fetch stay separate rows. Identity for the diff is `(property_name, label, beds, baths, sqft)`. Identity for Algolia stays `{property-slug}__{label-slug}`.

### Failures and bot walls

| Status | Manager action |
|---|---|
| `ok` with rows | Merge. Diff against the last accepted file. |
| `ok` with zero rows | Keep the previous rows. Flag the building. Do not write a stub over priced history. |
| `blocked_bot_wall` | Keep the previous rows. Put the building on the rescue queue. |
| Rescue file present | Apply the price mode (`split_total`, `base_only`, `installment`, `promo_current`, `unpriced`, `empty`) and then the same diff. |
| Exception | Same as a bot wall: previous rows stand, building is listed in `run_log.txt`. |

The rescue queue is a visible browser or a saved page (`solve_blocked.py`, `rescue_from_page.py`). Nobody automates the challenge.

### Outputs

Same two downstream artifacts as today, written by the manager after the merge:

- CSV at `output/csv outputs/advertised_prices_YYYY-MM-DD.csv` with the 20 columns, including `price_status` and the original `source_type` strings.
- Algolia-shaped JSON consumed by `discrepancy_updater.py --scrape`, with the current `objectID` formula, plus a `run_log.txt` of failures so the updater leaves those buildings unchanged.

Rebuild's `out/units.json` can keep the richer fields (`rent_basis`, `adapter`, `price_min`). It is not the feed the updater reads. The manager does not call Algolia and does not call Rate My Rent.

## 8. Work streams that can run in parallel

Each stream owns files the others do not edit.

| Stream | Owns | Does not touch | Done when |
|---|---|---|---|
| A. Parity harness | New `aggregator/parity_harness.py` and its tests | Extractors, `listing_adapters.py`, configs | The appendix's 10 buildings reproduce this diff, and a bot wall is reported as a skip |
| B. LeaseLeads parser | New function in `reference/legacy_ut_scraper/extractors/http_extractors.py`, plus the single `detect()` branch that calls it | `HOST_ADAPTERS`, `refresh_listings.py`, rescue code | The four villas buildings match CSV row counts on the attribute JSON, without Playwright |
| C. Pins for housing and college houses | New `data/ut_austin/pinned_sources.json` only | `listing_adapters.py` | `ut_housing_*`, `ut_rates_table`, and `collegehouses_rates` are pins the harness can run. French House and Arrakis are either pinned or listed as CSV-only |
| D. Row post-process | New `aggregator/listing_post.py` (`clean_labels`, Torre status rule) | `dom_extract.js`, `detect()` | Icon's merge is unit-tested on duplicated labels. Torre's 47 rents survive and stay `not_publicly_listed` if that is the accepted rule |
| E. Legacy publisher | New `aggregator/publish_legacy_feeds.py` | The updater in FML_Data, any network client | A fixture of Rebuild rows writes the 20-column CSV and Algolia ids of the form `{property}__{label}` |
| F. Rescue price modes | New `aggregator/rescue_prices.py` porting the six modes | `solve_blocked.py` (it keeps the human-in-the-loop behavior) | GrandMarc `promo_current` and Quarters `empty` map the way `ingest_headed_rescues.py` maps them, on fixture JSON |
| G. Manager | New `aggregator/scrape_manager.py`, after A–F have stable function names | Extractor internals | It shards a fixture roster, calls the pin first, merges, and writes through E. It has no Algolia client |

Stream B is the only one that edits `listing_adapters.py`, and only to add the LeaseLeads marker. Stream C expresses routing as pins so it does not need that file. Stream G starts after the function names in A, D, E, and F are fixed, so it is not parallel with their first landing. A, B, C, D, E, and F can land together.

## Appendix: live HTTP parity, 2026-11-25

Ten buildings, FML_Data HTTP extractor (identical bytes to the vendored copy) against `advertised_prices_2026-11-17.csv`. `convert()` was then applied. No browser. No Algolia. Price agreement is on labels that exist on both sides and have a rent on both sides.

| Building | Backend | Live rows (priced) | CSV rows (priced) | Shared labels | Rents equal | Notes |
|---|---|---|---|---|---|---|
| Crest at Pearl | `acc_lightning` | 26 (26) | 26 (26) | 26 | 24/26 | 4x4 B 1159→1184, 4x4 C 1129→1154 |
| 21 Rio | `wp_entrata_json` | 84 (84) | 85 (85) | 81 | 74/81 | One CSV row has no live label. Sample A1 City 2120→2170 |
| The Sondery | `sightmap` | 70 (44) | 82 (56) | 63 | 29/38 | Inventory moved. Sample A8 unit 146 1734→1675 |
| Keystone Apartments | `knock_doorway` | 22 (21) | 30 (28) | 15 | 0/14 | Same units, lower rents. Unit 140 827→797 |
| Sparq on Rio | `webflow_cms_floorplans` | 6 (6) | 7 (6) | 6 | 6/6 | One CSV label absent live |
| Elan East Apartments | `realpage_cms_proxy` | 251 (248) | 251 (248) | 251 | 239/248 | Labels match; a handful of rents moved |
| 2400 Nueces | `ut_housing_nueces` | 23 (23) | 23 (23) | 23 | 23/23 | Exact. This parser is not auto-routed |
| Skyloft Austin | `fp_units_modal_v2` | 36 (36) | 36 (36) | 36 | 36/36 | Exact |
| Ballpark North | `ballpark_static` | 6 (6) | 6 (6) | 6 | 6/6 | Exact |
| Oak Grove Apartments | `spearhead_static` | 3 (3) | 3 (3) | 3 | 3/3 | Exact |

On every live row, `convert()` dropped `price_status` and set `source_type` to `first_party_site`. `concessions_raw` is copied to `concession`. `name`, `base_rent`, and `price_min` matched the extractor label and rent. Crest's sample row `2 Bed - 2 Bath G [Per Installment/Person]` at 1424 stayed intact, with `rent_basis=per_bed`.

Rent mismatches above are the sites moving since the November file. They are not an extractor fork: both repos share one HTTP file. A cutover that overwrites the CSV with today's rents is drift and has to be accepted per building. A cutover that drops `price_status` is data loss and is not accepted.

`villas_wp` was not run in Playwright. The HTTP check in section 5 is the evidence that the selector matches nothing while the lease-term JSON is present.
