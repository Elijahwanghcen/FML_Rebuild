# FML_Rebuild Operator & Troubleshooting Guide (`difficulties.md`)

Field notes from running `FML_Data` (`402b54a` + `a953774`) and `FML_Rebuild` (`0e2981b`, Phase 0) for UT Austin and Texas A&M on the Linux box (2026-11-25). Written so a new Grok bot can run clean campus refreshes, diagnose hangs/failures, and onboard or update a campus without repeating these traps.

---

## 1. Quick-Start Checklist for Running a Refresh on the Box

1. **Read repo docs first:** `README.md`, `docs/PARITY_PHASE0.md`, `docs/SUPER_REBUILD_PLAN.md`, `docs/PLAYBOOK_1_DISCOVERY.md`, `docs/PLAYBOOK_2_ENRICHMENT.md`.
2. **Never run refreshes directly inside your clean reference clone if you want git untouched** (or copy/clone into a scratch working dir like `/workspace/fml-scrape/work-rebuild`), because `refresh_listings.py` writes into `data/<campus>/out/` and `legacy_emit.py` creates `csv outputs/`.
3. **Set Playwright + non-stalling wait env vars:**
   ```bash
   export FML_SOLVE_WAIT_S=25
   python3 -u aggregator/refresh_listings.py ut_austin
   ```
   - Always pass `-u` (`python3 -u`) so stdout streams line-by-line to your log instead of buffering until completion.
   - Expect **exit code `2`** whenever any entry in `listing_config.json` triggers `saved_html_banned` (see #5 below). Use `; RC=$?` rather than `&&` after `refresh_listings.py`, and verify `units_YYYY-MM-DD.json` / `advertised_prices_YYYY-MM-DD.json` were written.
4. **Hard safety rules:**
   - Never bypass CAPTCHAs or Cloudflare challenges (no solver services, no cookie theft, no evasion tricks).
   - Never push to Algolia, write to live Rate My Rent, or commit/push to repos unless explicitly authorized.
   - Never print Algolia/RMR/API keys.

---

## 2. Difficulties Encountered & Exact Fixes

### 1. Private GitHub Repos + No `gh` Auth on the Box
- **Symptom:** Cloning `FML_Rebuild` or `FML_Data` directly on the box fails (`404` / auth required); the box has no `gh` credentials.
- **Fix:** Pull `origin/main` on the user's MacBook Air (which has `gh` logged in), create git bundles or a tarball inside an allowed directory, and transfer via `CopyToBox`.

### 2. `CopyToBox` Rejects `/tmp` on the Mac
- **Symptom:** `CopyToBox` fails with `Path is outside the allowed local-exec root` when staging a tarball in `/tmp/` on macOS.
- **Fix:** Stage transfer archives inside the user's home/project workspace (e.g., `~/fml-migration/fml_repos_main.tar.gz`) before calling `CopyToBox`.

### 3. `git bundle create ... origin/main` Clones an Empty Repo
- **Symptom:** `git clone repo.bundle dest` creates an empty `master` branch with no files because `git bundle create <file> origin/main` omits `HEAD`.
- **Fix:** Unpack bundles explicitly:
  ```bash
  git init /workspace/FML_Rebuild
  git -C /workspace/FML_Rebuild fetch /path/to/rebuild.bundle '+refs/*:refs/*'
  git -C /workspace/FML_Rebuild checkout -b main <commit_sha>
  ```
  (Or include `HEAD` when creating the bundle: `git bundle create repo.bundle HEAD origin/main`.)

### 4. Playwright Resolution & Xvfb Display on the Box
- **Symptom:** DOM extractors (`entrata_pp`, `rentcafe_ysi`, `yugo`, `repli360`, `villas_wp`, `landmark`, `sinclair_wp`, `ion_wp`, `rambler_lvbode`, `g5_sniff`, `realpage_sniff`, `rise_units`, `gogetter_wc_floorplans` — 49 UT buildings / 1,354 rows) fail or silently fall back if Node cannot resolve `playwright` or Chromium cannot find Xvfb.
- **Fix:**
  - Verify Playwright exists at `/workspace/pwdeps/node_modules/playwright` and is linked at `npm root -g` (`/home/box/.local/lib/node_modules/playwright`), with Chromium cached in `~/.cache/ms-playwright/`.
  - If `DOM_HEADED=1` is used for non-CAPTCHA JS checks, ensure `DISPLAY=:4` (Xvfb) is running.
  - On `FML_Data` (`run.py`), run from a directory or with `NODE_PATH=/workspace/pwdeps/node_modules` so `dom_extract.js` finds Playwright.

### 5. `saved_html_banned` Causes Exit Code `2` (Even When Everything Else Succeeded)
- **Symptom:** `refresh_listings.py` prints `ERROR saved-html adapter banned for production: ...`, logs `error: saved_html_banned` for those properties, and raises `SystemExit(2)` at the very end (`refresh_listings.py:138`).
- **Scope today:**
  - `ut_austin`: **9** unlocked properties (`6 text_plan_list`, `3 rentcafe_inline` with `params.html_files`). All **145** locked properties run cleanly without `saved_html_banned`.
  - `texas_am`: **54** of 113 properties (`36 text_plan_list`, `8 rentcafe_inline`, `8 jsonld_offers`, `2 university_rates`).
- **Root cause:** `listing_post.saved_html_banned()` intentionally refuses `backend == "text_plan_list"` and any config entry carrying `params.html_files` (which point to gitignored `/Users/elijahwangchen/FML_rebuild/data/<campus>/raw/...` HTML snapshots that do not exist on Linux or in production).
- **Fix / Workaround:**
  - Do **not** wrap `refresh_listings.py` in `&&` assuming exit code `0`; capture exit code `2` cleanly and verify the output files (`write_legacy()` and `units_YYYY-MM-DD.json` both finish *before* `raise SystemExit(2)`).
  - For campus upkeep: re-enrich `rentcafe_inline` -> `rentcafe_ysi` (DOM), test `jsonld_offers` and `university_rates` without `html_files` (6/8 A&M `jsonld_offers` and 2/2 `university_rates` already pass live when `html_files` is stripped), and replace `text_plan_list` with live HTTP/DOM adapters or checked-in rescues.

### 6. Hardcoded macOS Paths (`/Users/elijahwangchen/FML_rebuild/...`) Break Repo Rescue Files on Linux
- **Symptom:** All **13** `headed_rescue` entries in `data/texas_am/listing_config.json` fail on Linux with `[Errno 2] No such file or directory: '/Users/elijahwangchen/FML_rebuild/data/texas_am/rescues/<slug>.json'`, even though all 13 JSON files **are committed** in `data/texas_am/rescues/`.
- **Root cause:** `listing_config.json` stores absolute Mac paths in `params.file` instead of repo-relative paths (`data/texas_am/rescues/<slug>.json`).
- **Fix:**
  - When updating `listing_config.json` in `FML_Rebuild`, store `params.file` relative to repo root (`data/<campus>/rescues/<slug>.json`) or resolve relative to `ROOT` in `listing_adapters.py`.
  - In read-only runs where you must not touch `FML_Rebuild`, remap `/Users/elijahwangchen/FML_rebuild/` -> `<work_repo_root>/` only in your runner script.

### 7. Campuses Without `"locked": true` Emit NO 20-Column Legacy CSV/JSON
- **Symptom:** Running `refresh_listings.py texas_am` produces `units_YYYY-MM-DD.json` and `refresh_YYYY-MM-DD.md`, but **no** `advertised_prices_YYYY-MM-DD.csv`, `.json`, or `.unit_ids.json`.
- **Root cause:** `refresh_listings.py:77-85,114` only builds `legacy_records` and calls `write_legacy()` for properties with `"locked": true`. `ut_austin` has 145 locked properties; `texas_am` currently has **0**.
- **Fix:**
  - To emit the 20-column schema for an unlocked campus like Texas A&M without mutating repo configs, run `legacy_emit.property_record()` + `write_legacy()` over the extracted rows (as done in `texas-am/legacy_emit_report.json`).
  - For long-term production refreshes on a new campus, promote verified entries in `listing_config.json` (locking or enabling `write_legacy` for verified properties) once their sources are validated.

### 8. `jonah_detail_json` Looks Hung for 5–8+ Minutes on Large Properties
- **Symptom:** Stdout in `refresh_listings.py ut_austin` stopped completely after `Metropolis` for ~8 minutes while scraping `Elle West Ave` (`jonah_detail_json`), and `ps`/`wchan` showed `hrtimer_nanosleep` with no active socket.
- **Root cause:** `http_extractors.jonah_detail_json` fetches `/floorplans/` HTML, collects every floorplan slug, and runs `time.sleep(2)` *after every single slug*. `Elle West Ave` has **156** floorplans (`156 * (2s sleep + ~1s fetch)` ≈ 7.8 minutes) with no per-slug progress log.
- **Fix:** Do **not** kill the process thinking it hung. Confirm progress by checking `/proc/<pid>/io` `rchar`/`syscr` over 4–5 seconds (bytes read climbs steadily between 2s sleeps). On full UT refreshes, expect ~20–25 minutes total runtime (`22m 13s` observed).

### 9. `FML_SOLVE_WAIT_S` Defaults to `300` Seconds (5 Minutes per Blocked Site)
- **Symptom:** If `DOM_HEADED=1` hits an interactive Cloudflare/bot challenge, `listing_adapters.py` waits up to `FML_SOLVE_WAIT_S` (default `300s` = 5 min) *per site* before moving on.
- **Fix:** Set `FML_SOLVE_WAIT_S=25` (or similar short window) in batch runs so passive JS checks can settle while hard-blocked sites fail fast without stalling the batch. Never bypass interactive CAPTCHAs.

### 10. Legacy `objectID` vs Rebuild `objectID` Mismatch (17 UT Properties)
- **Symptom:** Comparing `advertised_prices_YYYY-MM-DD.json` (`locked` emitter) to `listing_config.json` by `objectID` misses 17 UT properties (e.g., `callaway-house` vs `the-callaway-house-austin`, `quarters-on-campus-nueces` vs `the-quarters-nueces-house`, `sabina-condominiums` vs `sabina`).
- **Root cause:** `legacy_emit` preserves `FML_Data` canonical `objectID` slugs from `locked_from` / `properties_config.json`, while `listing_config.json` uses Rebuild's roster `objectID`.
- **Fix:** When joining `advertised_prices_*.json` back to `listing_config.json` or `units_*.json`, fall back to `property_name` (or `source_id`) if `objectID` isn't found directly.

### 11. `g5_sniff` Unit Ordering Is Non-Deterministic
- **Symptom:** `Promontory Point` (`g5_sniff`, 50 units) failed naive index-by-index JSON comparison against the morning baseline, even though **50/50** unit objects were field-for-field identical.
- **Fix:** Compare `g5_sniff` (and other DOM-sniffed unit lists) as multisets/sorted by `(unit_or_floorplan_label, base_rent, availability)` rather than relying on array index order.

### 12. Missing `rapidfuzz` on the Box
- **Symptom:** `common.name_sim()` raises `ModuleNotFoundError: No module named 'rapidfuzz'` if invoked.
- **Impact:** `refresh_listings.py` and `test_phase0.py` do **not** hit `name_sim()`, so refreshes run cleanly without it. Discovery/matching scripts (`PLAYBOOK_1_DISCOVERY.md`) will need `pip install rapidfuzz` in a venv if run on the box.

### 13. `villas_wp` Version Drift in `FML_Data` vs `FML_Rebuild`
- **Context from morning baseline:** `FML_Data` `402b54a` had the old `villas_wp` extractor; `a953774` updated `villas_wp` to the LeaseLeads DOM parser (`data-ll-floor-plan-lease-terms`), adding 89 rows across 4 buildings (`Villas on Guadalupe`: 45, `Signature 1909`: 18, `Axis West Campus`: 15, `21 Pearl`: 15 — 93 rows total). `FML_Rebuild` `0e2981b` is synced to `a953774` via `scripts/sync_fml_extractors.py` and matched all 4 `villas_wp` buildings (`93/93` rows) exactly.

### 14. Known Live-Site Failures That Are Expected Today (Do Not "Fix" in a Refresh)
- **UT `Villas on 26th` (`vnue_grid_static`):** `HTTP Error 403: Forbidden` (same in `FML_Data` morning baseline).
- **UT `1883 at Montgomery House` (`entrata_pp`):** `no_rows` (same in `FML_Data` morning baseline).
- **UT `Texan 26` (`no_public_pricing`):** Entrata portal is Cloudflare-blocked; placeholder is intentional — do not bypass.
- **A&M `Sierra Condos` & `Canyon Village Apartments` (`jsonld_offers`):** Return `HTTP Error 500` live even with `html_files` stripped.
- **A&M `rentcafe_inline` (8 sites):** All 8 return `HTTP 403` to `urllib` live; need Playwright DOM (`rentcafe_ysi`) during an enrichment pass.

---

## 3. Managing & Updating a Campus (Step-by-Step)

### Existing Campus Weekly Refresh
1. **Run `refresh_listings.py <campus>`** (never edit extractors during a weekly refresh; see `refresh_listings.py` docstring).
   - Re-run a single failed building without wiping the rest:
     ```bash
     python3 -u aggregator/refresh_listings.py ut_austin --only <objectID_or_source_id> --patch
     ```
2. **Inspect `out/refresh_YYYY-MM-DD.md`:** Check `Failed` and `Big moves since last run` (>15% median rent swing or >50% row count swing). Verify swings by hand before any downstream publish.
3. **Archive history (`tools/scrape_archive/`):**
   ```bash
   python3 -m tools.scrape_archive ingest --campus ut-austin --input "data/ut_austin/out/csv outputs/advertised_prices_YYYY-MM-DD.csv"
   ```

### Completing Texas A&M (`texas_am`) or Onboarding a New Campus
1. **Campus profile (`campuses/<campus>.json`):** Define `name`, `short`, `city`, `neighbor_cities`, `state`, `center`, `core_radius_m`, `max_radius_m`, `neighborhoods`, `subreddits`, `city_words`, `rcp_urls`, `ocp_base`, `extra_pm_sites`.
2. **Discovery (`PLAYBOOK_1_DISCOVERY.md`):** Build `roster_final.csv` / `.json`, dedupe by `place_id` / normalized address (beware leasing-office duplicates like `Domain Northgate` / `The Ridge` / `EVER College Station` appearing twice in `texas_am/roster_final.csv`). Notice `texas_am/listing_config.json` currently covers only **113** of **173** roster rows (~59 missing).
3. **Enrichment (`PLAYBOOK_2_ENRICHMENT.md`):**
   - Resolve first-party websites (`own_site` / `operator_page` / `official_org_page` / `portal`; never ILS/directories).
   - Detect live feed/DOM adapters (`enrich_listings.py`) so `listing_config.json` contains **zero** `text_plan_list` and **zero** `params.html_files` Mac paths.
   - Store any required `headed_rescue` JSONs as repo-relative paths (`data/<campus>/rescues/<slug>.json`), never `/Users/<user>/...`.
4. **Locking & 20-Column Parity (`docs/PARITY_PHASE0.md`, `aggregator/test_phase0.py`):**
   - Mark verified live configs `"locked": true` (or update `refresh_listings.py` once Phase 1 retires the locked-only gate) so `write_legacy()` emits the 20-column CSV + JSON + `unit_ids.json`.
   - Always run `python3 aggregator/test_phase0.py` after touching extractors or `legacy_emit`.
