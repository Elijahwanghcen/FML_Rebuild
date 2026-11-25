# Super rebuild: what to take from FML_scraper (FML_Data) and FML_rebuild

Audit 2026-11-18. Inputs: FML_Data @ 2026-11-17 (`git pull`, includes `advertised_prices_2026-11-17.csv`), FML_rebuild
working tree (UT output built 11-18 17:42, `listing_adapters.py` VERSION 9, uncommitted). UT only.

Note: the 11-17 CSV is an export of **live Rate My Rent** (commit #22), so it includes team edits. The scraper's last
real scrape is still 2026-09-29.

## Side by side (UT)

| | FML_scraper / FML_Data | FML_rebuild |
|---|---|---|
| Buildings | 143 roster (+3 added on live → 146; live catalog 145) | 150 picked from 732 ranked (830 merged) |
| Listing rows | 2,661 (2,314 priced, 1,730 `listed`, 481 blank status) | 2,219 (1,804 priced) |
| Buildings with rows / priced | 140 / ~120 | 113 / 99 |
| Layout images / sqft | 2,412 / 2,249 | 1,774 / 1,747 |
| Concessions captured | 0 in 11-17 CSV (sidecar exists, Aug only) | 194 rows |
| Extractors | 41 backends, assigned by hand per building | the same 41 code (copy in `reference/legacy_ut_scraper`) + 10 new: `appfolio_smart`, `rentcafe_inline`, `repli360_feed`, `text_plan_list`, `jsonld_offers`, `university_rates`, `advertised_range`, `cg_synergy`, `buildium_search`, `headed_rescue` |
| Extractors actually used | 40 | 26 (25 in `listing_config.json`) |
| How a backend is chosen | hand-written `properties_config.json` (exact floor-plan URL + params) | markers in crawled HTML → network fingerprint → printed plan lines → rescue file → AI page read; keeps the one with most priced rows; result frozen into `listing_config.json` |
| Fingerprints | 91 files from `scripts/fingerprint.js`, run once in batches (b2/b3/b4) to pick backends by hand | same `fingerprint.js` ported, run automatically only when no marker matches (cached `raw/<slug>/fingerprint.json`) |
| Bot walls | headed-browser rescues ingested by hand (`ingest_headed_rescues.py`) | `solve_blocked.py` (visible window, saved cookie) + `recv_pages.py`/`rescue_from_page.py` (Chrome page → same parser) |
| Weekly refresh | `run.py` + `CLAUDE_WEEKLY.md` (no debugging in a refresh) | `refresh_listings.py`, ported from the same rules (one fetch per source, polite delay, failure stubs, 15% rent-swing flag) |
| Publish to live | Algolia push scripts + `tools/rmr-discrepancy-updater` (dry run → review.md → per-building approval → guarded MCP writes, never removes) | none |
| Building facts | Google Places (rating, reviews, photos), walk time, hand-curated pins, cover photo on all 143 | address point + building outline coords, website ladder, manager, Reddit threads, student score; **0 photos** |
| Amenities | phase 0–7 pipeline, LLM normalize, scored tiers + rent premium (`phase7_score.py`) | evidence-quoted amenities, same taxonomy; no scoring step |
| Campus | UT only | campus-agnostic (UT, A&M) |

## How alike the shared data is (89 live buildings matched)

- Row count: identical on 40, within 20% on 53.
- Same backend chosen: 47 of 89.
- Median rent (66 buildings priced on both sides): within 5% on 53, within 15% on 58. Big gaps: Gables (900 vs 2,581),
  Texan Shoal Creek (1,000 vs 1,895), Centennial (2,095 vs 1,115), Buena Vista (1,900 vs 1,250), West Campus Flats.
  All are realtor/condo pages where per-unit and per-bed rents get mixed.
- Address street number agrees 75/88; website domain 66/88; type 59/88 (condo vs apartment labels).
- Coordinates: median 25 m apart, 44 within 25 m, 8 more than 100 m.
- Amenities (same taxonomy): median overlap (Jaccard) 0.55; 33 of 72 buildings at 0.6 or more, 13 below 0.3.

## Where each one wins

**Scraper wins**
1. Hand-verified source per building. Exact `/student/` page or `entrata.` subdomain plus params, e.g. the 11-17 Quarters,
   GrandMarc, Inspire fixes. The rebuild starts from Google's home page link and misses these.
2. `entrata_pp`. Works in the scraper (14 buildings). In the rebuild it still returns 0 rows: Quarters Grayson, Sterling,
   Karnes and GrandMarc have 0 rows; Inspire falls to `text_plan_list`.
3. DOM `repli360` gives full rows (Sabina 78, Marq Uptown 70). The rebuild's `repli360_feed` gives 34 and 30.
4. Multi-building ACC sites. The Block 23, 25th West and Pearl South are split by `LocationFilter`. The rebuild never found 23, 25th West and Pearl South as separate buildings.
5. Edge parsers the rebuild never routes to: `ut_housing_nueces` (2400 Nueces), `ut_housing_dobie`, `rise_units` (Rise, 34 rows),
   `collegehouses_rates`, `ut_rates_table`.
6. Photos, Google reviews and ratings, walk times, amenity scores. These already power the live site.
7. Safe publishing: the discrepancy updater.

**Rebuild wins**
1. Discovery. It finds 55 buildings the live site lacks (see `NEW_BUILDINGS_FOR_RMR.md`). It also finds most scraper
   buildings, but ranks them out of the top 150: Dobie Twenty21 #168, Twenty Two 15 #179, Troubadour #195, The Waller #199,
   Point North #235, Icon #356 (score 2.5).
2. Unit-level feeds. SightMap gives Union on 24th 239 rows and Union on San Antonio 191 (scraper 45 / 34 floor plans).
   `jonah_detail_json` gives Gables 156 rows.
3. Auto-detection + network fingerprint. New buildings need no hand config.
4. Prices where the scraper has none: Venue on Guadalupe (scraper `no_public_pricing`, rebuild 20 rows via `villas_wp`),
   Villas on 26th, Tower View.
5. Concessions (194 rows), per-bed vs per-unit tagging, and the QC coverage flags. Each building records every adapter it tried.
6. Better coordinates method; repeatable bot-wall rescue; campus-agnostic config.

**Both are weak**
- Rebuild creates duplicates from leasing-office addresses ("Grayson" at 2222 Rio Grande Ste D200, "Nueces"), double Buena Vista,
  and an org office (College Houses Cooperatives).
- Rebuild ranking keeps far apartments (Avana 2.9 km, Mosaic 3 km, Waterloo Flats 5.1 km) and drops big student towers.
- Scraper roster is frozen; 481 rows have no price status; no concessions since August.

## Merge plan

The rebuild framework is the base: it is campus-agnostic and already imports the scraper's extractors. Add the scraper's
verified knowledge as locked inputs.

1. **Sync the extractor code.** Copy FML_Data `austin_leases_units/scraper/{run.py, properties_config.json, extractors/}`
   into `reference/legacy_ut_scraper/`. That brings `clean_labels` and the 11-17 URL fixes. Better: import it as a git
   submodule so it can't drift again.
2. **Pinned sources first.** For UT, seed `listing_config.json` from `properties_config.json` (backend, url, params,
   source_id). Pinned entries are tried before detection. Detection, net fingerprint, `text_plan_list` and rescue still
   run, and the result with the most priced rows wins (`extract()` already does this). New campuses work as today.
3. **Fix the 3 adapter gaps.** Debug `entrata_pp` on the rebuild path (profile and headed mode). Use DOM `repli360` when
   `repli360_feed` returns fewer rows. Route `ut_housing_*`, `rise_units`, `collegehouses_rates` and `ut_rates_table`
   by host in `HOST_ADAPTERS`.
4. **Roster = union, locked.** Live catalog (145) is always included. Rebuild discovery only adds. Ranking must not
   drop a live building; also force-include `student_housing` within 1.5 km. Treat more than 2.5 km as opt-in.
5. **Dedupe step** before output. Merge on the same Google place_id, the same street number + street, or within 30 m
   with name overlap. Drop rows whose address has "Suite"/"Ste" or matches a known leasing office (Quarters, College
   Houses, Uptown).
6. **Rent sanity check.** Compare each building's median to the last live value. Flag swings over 25% and realtor pages
   that mix per-unit and per-bed (Gables, Texan Shoal Creek, Centennial) for a human before publishing.
7. **Building facts:** keep live photos, Google rating and reviews, walk time and hand pins. Use rebuild coords only where
   live has none or is more than 100 m off and flagged. Run `reference/photo_pass` for new buildings.
8. **Amenities:** union both feature lists (rebuild keeps evidence quotes), then run the scraper's `phase7_score.py`
   for tiers and rent premium.
9. **Weekly:** `refresh_listings.py` (config-driven, no LLM) → `discrepancy_updater.py` dry run → review.md →
   approve per building → guarded MCP writes. The updater becomes the only write path to live.
10. **New buildings:** go through the RMR MCP by hand from `NEW_BUILDINGS_FOR_RMR.md`, not by bulk push.
