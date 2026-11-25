# Grok Bot handbook — FML_Rebuild, re-scrapes, and new campuses

**Audience:** a new Grok Bot (or a manager bot coordinating several) that has to navigate [FML_Rebuild](https://github.com/Elijahwanghcen/FML_Rebuild), run and manage re-scrapes, stand up a new campus, and keep a campus updated without losing data.

**Owner:** Elijah WangChen. Speak as him on his accounts. Time zone for reports is America/Chicago.

This file is the operator runbook and the lesson log. It does **not** replace the campus playbooks. For discovery, enrichment, completeness rules, and platform fingerprints, follow and link to those docs; do not copy them here.

| Doc | Use it for |
|---|---|
| [docs/PLAYBOOK_1_DISCOVERY.md](PLAYBOOK_1_DISCOVERY.md) | Finding every student-relevant building around a campus, source order, identity rules, miss-cause table (section 5c), A&M reference shape |
| [docs/PLAYBOOK_2_ENRICHMENT.md](PLAYBOOK_2_ENRICHMENT.md) | Coordinates, websites, amenities, listings adapters, Cloudflare ladder, plan images, publish gate |
| [docs/PARITY_PHASE0.md](PARITY_PHASE0.md) | Latest Tier A / Tier B parity results vs the FML_Data baseline |
| [docs/POSTMORTEM_DISCOVERY_2026-11-24.md](POSTMORTEM_DISCOVERY_2026-11-24.md) | Discovery postmortem |
| [docs/POSTMORTEM_PLAN_IMAGES_2026-11-24.md](POSTMORTEM_PLAN_IMAGES_2026-11-24.md) | Plan-image postmortem |
| [docs/RESULTS.md](RESULTS.md) | Measured discovery/enrichment results |
| [docs/lessons/2026-11-25-rebuild-scrape.md](lessons/2026-11-25-rebuild-scrape.md) | Field notes from the 2026-11-25 box refresh (UT + A&M); summarized in section 10 |
| [tools/scrape_archive/README.md](../tools/scrape_archive/README.md) | Snapshot, change log, master list, Drive upload |
| [austin_leases_units/scraper/CLAUDE_WEEKLY.md](https://github.com/Elijahwanghcen/FML_Data/blob/main/austin_leases_units/scraper/CLAUDE_WEEKLY.md) (FML_Data) | Deterministic refresh rules (no new extractors mid-run) |
| [austin_leases_units/scraper/CLAUDE_BUILD.md](https://github.com/Elijahwanghcen/FML_Data/blob/main/austin_leases_units/scraper/CLAUDE_BUILD.md) (FML_Data) | Writing or fixing extractors |
| [tools/rmr-discrepancy-updater/README.md](https://github.com/Elijahwanghcen/FML_Data/blob/main/tools/rmr-discrepancy-updater/README.md) (FML_Data) | Rate My Rent dry-run / apply |

---

## 1. Purpose and repos

The work has two GitHub repos, both under Elijahwanghcen:

| Repo | Role |
|---|---|
| [FML_Rebuild](https://github.com/Elijahwanghcen/FML_Rebuild) | Campus-agnostic discovery + enrichment, locked UT sources, shared extractors, parity harness, scrape archive. **This is the destination system.** |
| [FML_Data](https://github.com/Elijahwanghcen/FML_Data) | The production UT scraper (`austin_leases_units/scraper/run.py`), Algolia transform/push for `austin_leases_units`, and the Rate My Rent discrepancy updater. Still the refresh path until Rebuild is cut over. |

**Standing goal (lossless data):** a one-shot scrape of a new campus should come out as data-rich as the merged UT set or the A&M set. Rebuild must not drop buildings, plans, prices, or images that FML_Data already knows how to get. Listings a partial run does not touch stay in the archive master.

**Migration status as of 2026-11-25 (America/Chicago):**

- Shared extractors are synced from FML_Data (including the `villas_wp` LeaseLeads fix, commit `a953774` on FML_Data). `python3 scripts/sync_fml_extractors.py --check /path/to/FML_Data` fails if they drift.
- All 145 UT buildings are locked in Rebuild (`listing_config.json`, `"locked": true`). Detection may add a building; it may not replace a locked backend, URL, or params.
- Rebuild emits the same 20-column legacy sheet as `run.py`.
- **Tier A and Tier B parity is exact for the 36 HTTP-feed buildings** (ACC, Torre/wp-json Entrata, SightMap, Knock, RealPage, AppFolio, Jonah, and similar). See [docs/PARITY_PHASE0.md](PARITY_PHASE0.md).
- The 2026-11-25 FML_Data baseline is **2,627 plans / 145 properties** (full `run.py` on `402b54a`, plus the four `villas_wp` buildings re-run on `a953774`).
- Cloud-agent Playwright was missing, so browser-family parity was unfinished there. The later box refresh (2026-11-25, America/Chicago) matched all **49/49** locked DOM properties exactly against the FML_Data baseline. See [section 10](#10-lessons-from-the-2026-11-25-rebuild-scrape).
- Switching the 36 HTTP-feed buildings onto Rebuild in the every-4-days routine, with FML_Data running alongside as a check, was proposed and is **not automatic**. Do it only if Elijah says yes.

Useful local checkouts:

- Elijah's MacBook Air: `~/fml-migration/FML_Rebuild` and (set `FML_DATA_ROOT` to) the FML_Data clone in the same folder. `gh` is logged in as `Elijahwanghcen`. machineId `5f889b5f-1d67-456e-a0e4-0581d3062cf8`. Commands on this machine need his approval — batch them.
- The shared box has no `gh` login. Do not assume a clone on the box is current; pull or read GitHub main.

Campus slugs:

- Scripts and `campuses/*.json`: `ut_austin`, `texas_am`.
- Scrape archive `--campus`: `ut-austin`, `texas-am` (aliases such as `ut_austin` / `tamu` are accepted). A new campus is a new slug and a new folder; it does not need a code change in the archive.

---

## 2. Access and permissions

### What needs Elijah's explicit yes

Nothing in this list is implied by a task description, a memory, or a previous "yes" on a different building or date.

- **Any write to live Rate My Rent** (MCP `update_listing` / `add_listing_record`, or `--apply` on the discrepancy updater). A dry-run and a review markdown are fine.
- **Any Algolia `--push`** (or `--settings` that changes the live index). Transform-only and `--backup` are fine. The live index is `austin_leases_units` (also used: `rentright_buildings`, `FML_Property_amenities_scored`).
- **Hiding, deleting, or merging listings** on Rate My Rent, including "the 125 duplicate plans" or a Montgomery placeholder, until he names the building and the action.
- **Spending money, sending mail/Slack, or posting publicly.**

### What is already standing approval (code only)

- **Merge scraper / Rebuild / updater *code and config* straight into `main`** on both FML_Data and FML_Rebuild, each time, with no PR review step. This is code and config only — not data pushes, not Algolia, not live RMR.
- Do this so every other agent gets the same extractors and fingerprints.

### Secrets — name the files, never print values

Read credentials in-process. Never paste a key into Slack, a doc, a chat, a commit, a PR, a review markdown, or this handbook.

| Secret | Where it lives (name only) |
|---|---|
| Rate My Rent MCP Bearer token | `~/.claude.json` under `mcpServers.rmr`. Operator header: `X-RMR-Operator: elijah`. The key is shared admin access. `tools/rmr-discrepancy-updater/mcp_client.py` reads it and must never print or write it. |
| Algolia admin key | `~/.algolia_admin_key` (mode 600). `austin_leases_algolia_push.py` reads it from that file only, never from argv, env, or logs. |
| Google Drive upload creds | Environment at upload time only: `FML_DRIVE_ACCESS_TOKEN`, or `FML_DRIVE_REFRESH_TOKEN` + `FML_DRIVE_CLIENT_ID` + `FML_DRIVE_CLIENT_SECRET`, or `FML_DRIVE_SERVICE_ACCOUNT_FILE` / `GOOGLE_APPLICATION_CREDENTIALS`. See [tools/scrape_archive/README.md](../tools/scrape_archive/README.md). |
| Browser profile / clearance cookies | `~/.fml_dom_profile` and any cookie-handoff JSON. Never commit them. |

Also do not commit approval files, run output, or cookie jars.

### Machines and git

- **The box has no `gh` login.** cursor-github can read the repo and open branches/PRs, but cannot commit file contents. To land commits: use Elijah's Mac (`gh` already logged in) or a cloud agent with a file overlay. Do not try to invent a token.
- **Do not drive box Chrome from Shell.** Use the headed-browser tools / desktop when a real browser is required.
- **Never bypass a CAPTCHA or a Cloudflare challenge.** If a site shows an interactive check, log it, stop touching that property, and ask Elijah to clear it in a real browser if a rescue is needed.
- Claude Code on the Mac (`~/.local/bin/claude`) had a sign-in that expires **2026-11-27 through 2026-11-30**. If a Mac session fails auth, ask him to run `claude auth login` or `claude setup-token` — do not work around the login.
- Grok Bot weekly usage is shared with the rest of the plan. A long scrape, a headed rescue, or the every-4-days routine can **stop mid-run when usage is exhausted**. Check usage before starting a heavy job; if the week is nearly spent, tell Elijah and wait for the reset rather than launching a routine that will die halfway.

---

## 3. Standard re-scrape runbook

This is the every-4-days (America/Chicago) refresh, and any ad-hoc re-scrape of an existing campus. It is a cheap, deterministic run — not a rebuild.

**Do not write new extractors or "improve" backends mid-run.** Failures get logged and, if needed, a headed rescue or a later CLAUDE_BUILD / `enrich_listings.py` session. See FML_Data `CLAUDE_WEEKLY.md`.

### 3.1 Before you start

1. Check weekly usage. If it is nearly gone, do not start.
2. `git pull` on both repos (Mac: `~/fml-migration/FML_Rebuild` and FML_Data). Confirm you are on `main`.
3. If extractors changed in FML_Data, sync and check:
   ```bash
   python3 scripts/sync_fml_extractors.py --check "$FML_DATA_ROOT"
   # if it drifts, and Elijah's standing code-to-main rule applies:
   python3 scripts/sync_fml_extractors.py "$FML_DATA_ROOT"
   ```
4. Confirm Playwright / Node are present before any DOM backend run (`node_modules` for Playwright, browsers installed). `run.py` sets `NODE_PATH` from `npm root -g`, with a Homebrew fallback of `/opt/homebrew/lib/node_modules`. A missing Playwright install looks like every DOM building failing at once. Cloud agents often do not have it; the box and the Mac can.
5. Decide which engine to run:
   - **Default today:** FML_Data `run.py` for the full UT set.
   - **Rebuild refresh** (locked pins): `python3 refresh_listings.py <campus>` from `aggregator/`, after `cd aggregator`. Locked buildings go through `locked_scrape.py` and write the legacy 20-column files plus `data/<campus>/out/units_YYYY-MM-DD.json` and `refresh_YYYY-MM-DD.md`.
   - For the 36 HTTP-feed buildings, Rebuild has matched FML_Data exactly. Do not cut the every-4-days routine over without Elijah saying so. Until then, FML_Data remains the baseline.

### 3.2 Run the scrape

From FML_Data `austin_leases_units/scraper/`:

```bash
python3 run.py
# one source, for a test or a patch after a fix:
python3 run.py --only src_08
python3 run.py --only src_08 --patch output/advertised_prices_YYYY-MM-DD.json
```

Outputs:

- `output/advertised_prices_YYYY-MM-DD.json` — nested, Algolia-ready
- `output/csv outputs/advertised_prices_YYYY-MM-DD.csv` — flat 20-column sheet
- `output/run_log.txt`

From Rebuild `aggregator/`:

```bash
python3 refresh_listings.py ut_austin
python3 refresh_listings.py texas_am
python3 refresh_listings.py ut_austin --only <objectID|source_id> --patch
```

Shared `source_id`s are fetched once. Same-host requests wait 4 seconds. A failure becomes an explicit `(extraction failed)` stub, never a silent omission. Big median-rent moves (>15% in Rebuild) or large row-count swings are listed for a person, not "fixed."

### 3.3 Handle failures (tiered rescue)

Order, cheap first. **Never solve a CAPTCHA or Cloudflare challenge.**

1. **Off-portal CMS / marketing URL, or a known portal path.** Many Entrata buildings need `/<city>/<slug>/student/` (or `conventional/`), or `entrata.<site>`, not the marketing "Floor Plans" page. Quarters houses: `quartersoncampus.com/austin/{grayson,nueces,sterling}/student/`. GrandMarc: `entrata.grandmarcaustin.com`. Inspire: `entrata.inspire22nd.com`. Prefer a JSON/CMS feed when it exists; cold cloud calls to the same host as a WAF-gated portal still fail.
2. **Headed browser on the box or the Mac**, with a persistent profile (`~/.fml_dom_profile`). Rebuild's synced `dom_extract.js` uses FML_Data launch by default. Only when `DOM_PROFILE`, `DOM_HEADED=1`, or `DOM_CHALLENGE_WAIT_S` is set does it use the persistent/headed path and wait for a *non-interactive* "just a moment" page to clear. Interactive checks still stop the property.
3. **Cookie handoff.** If the headed run is blocked, ask Elijah to clear the challenge in his own Chrome, then reuse that clearance (cookie jar / profile) for the extractor. Do not remote-control his desktop as the weekly default. Do not pull cookies out of a file and print them.
4. **Hand-saved rescue** at `data/<campus>/rescues/<objectID>.json` (Rebuild) or ingest via FML_Data `ingest_headed_rescues.py`. Same idea: a real-browser capture, not a guessed price.
5. **Chronic list-only.** If it keeps failing, leave the last good rows in the archive master, keep a stub in this run, and report it. Do not wipe the building.

Known chronic cases to expect (see also the troubleshooting table):

- **Villas on 26th** — Cloudflare HTTP 403.
- **1883 at Montgomery House** — `no_rows` (keep it distinct from Cameron House).
- **Texan 26** — leasing portal blocked; placeholder / no public pricing only.
- A cluster of buildings with **no public rents** (including 1883 at Cameron House and Icon at times). Keep the placeholder row; do not invent a price.

After a parser fix (example: `villas_wp` on 2026-11-25), re-run **only those sources** with `--only` / `--patch` and merge into the baseline. Do not leave the unfixed empty rows in the archive as if they were a real scrape of those buildings.

### 3.4 Archive the run

From the FML_Rebuild repo root. Details: [tools/scrape_archive/README.md](../tools/scrape_archive/README.md).

```bash
python3 -m tools.scrape_archive ingest --campus ut-austin --input /path/to/advertised_prices_YYYY-MM-DD.csv
# or the nested JSON / Rebuild units_YYYY-MM-DD.json — ingest accepts all of these
python3 -m tools.scrape_archive upload-plan
# Drive upload only with credentials present; otherwise leave the plan for an agent that has Drive:
python3 -m tools.scrape_archive upload
```

Rules that already burned us:

- A property is updated only when the file has **real rows** for it. `(extraction failed)` stubs do not wipe that property.
- Listings of every other property stay in the master with the same `last_seen`.
- Pass `--full` only when the file is a complete roster snapshot and a missing property should be marked no longer advertised.
- The same file (sha256) is skipped if it is already in a snapshot.
- **Do not ingest an Rate My Rent export as if it were a scrape.** The 2026-11-17 file in the first history rebuild was an RMR export, not a `run.py` scrape. Comparing it to real scrapes produced thousands of formatting "changes." Mark exports in the archive, or leave them out of `rebuild-history`. The fresh 2026-11-25 baseline is the newest real UT scrape from that week.

Drive folder (already created): [FML Scrape Archive](https://drive.google.com/drive/folders/1WYFc1tCirxxC0MiwhkIxk5c6fNLmlIu8). Keep CSVs as plain CSVs. Upload after ingest; do not commit `tools/scrape_archive/output/`.

### 3.5 Rate My Rent review (dry-run only until he says yes)

From FML_Data `tools/rmr-discrepancy-updater/`:

```bash
python3 discrepancy_updater.py --refresh-live \
  --scrape /path/to/master/algolia_units_<run>.json --scrape-date YYYY-MM-DD \
  --run-log /path/to/scraper/output/run_log.txt
```

Send Elijah `runs/<date>/review.md`. Stop. Do not apply.

### 3.6 Algolia (only with an explicit yes)

Default is transform only, nothing live:

```bash
cd austin_leases_units/master
python3 austin_leases_algolia_push.py
# if he approved a live update, in this order:
python3 austin_leases_algolia_push.py --backup
python3 austin_leases_algolia_push.py --push --settings --verify
```

`--push` refuses unless a backup file exists. Key file is `~/.algolia_admin_key` — never print it. `base_rent < 300` is dropped to the audit/dropped file; academic-year / `base_rent > 6000` is nulled and the row is kept. Canonical names must resolve against `properties.csv` / `price_name_aliases.json` or the run aborts.

### 3.7 After the run, tell Elijah

- Counts (properties, rows, failures, no-public-pricing).
- Buildings that need a human Cloudflare clear.
- Path to the review markdown and the archive / Drive update.
- That nothing was pushed to Algolia or Rate My Rent unless he already approved a named set.

---

## 4. New-campus runbook

Goal: a first scrape as complete as merged UT or A&M — not "the top 150 looked full." A campus is not done until every name on a reference list is on the roster or written down with a cause.

Follow [docs/PLAYBOOK_1_DISCOVERY.md](PLAYBOOK_1_DISCOVERY.md) and [docs/PLAYBOOK_2_ENRICHMENT.md](PLAYBOOK_2_ENRICHMENT.md). Commands below are the short path; the playbooks have the rules.

### 4.1 Discovery → lock sources

1. Write `campuses/<slug>.json`. Include `neighbor_cities` (A&M needed **Bryan**; a city-only search drops buildings across the line), a wide enough `pm_radius_m` if the town is spread out, `rcp_urls` / `ocp_base`, and `extra_pm_sites`.
2. Collect leads, then merge and cut, then **put locked pins and `ADD` resolutions back after the top-N cut**. Top-N is not the roster.
   ```bash
   cd aggregator
   python3 discover_rcp.py <campus>          # names/addresses/coords only — never rent from a directory
   # or discover_ocp.py after a person saves the directory in their own browser
   python3 discover_places.py <campus>
   python3 discover_overture.py <campus>
   python3 discover_pm_sites.py <campus>     # include condo-landlord /communities/ indexes
   python3 resolve_addresses.py <campus>
   node reddit_fetch.js <out> <subs> "<queries>" 120   # Elijah logs in once per machine
   python3 discover_reddit.py <campus>
   python3 merge_candidates.py <campus>
   python3 select_roster.py <campus>
   python3 apply_resolutions.py <campus> roster_final.json
   python3 include_pinned.py <campus>        # optional top-N; run_campus.sh defaults to 170
   python3 campus_completeness.py <campus> --reference <reference.json>
   ```
   Or, after the user-assisted directory and Reddit steps: `./run_campus.sh <campus> [topN]`.
3. Completeness exits non-zero while reference names are missing. Causes and rules live in Playbook 1 section 5c and `aggregator/miss_causes.py`. **Read that table. Do not paste it here.** In short, the UT holes were: condo landlords (Uptown-style portfolios), buildings ranked below the review cut, Entrata/RentCafe bot walls, manager-portal filters, university/co-op rate tables, layouts-only / no public pricing, shared-feed filters, shorter Repli360 feeds, directory-lead-only names, LeaseLeads markup (`villas_wp`), Yugo per-room-type pages, URLs whose query string matters (Noble `?_lease_term=fall`), and **name collisions**.
4. **Name collisions:** do not alias distinct pins because they share a leasing office. UT examples: **1883 at Cameron House vs 1883 at Montgomery House**, the four Quarters houses, the three Town Lake names. Montgomery stays its own listing.
5. Copy the **A&M shape**, not only a Places cut: `neighbor_cities`, wider PM radius, off-campus directory as a lead list, `resolutions.json` after a person checks buildings with no site, hand-saved rescues under `data/texas_am/rescues/`, and frozen adapters (RentCafe, JSON-LD, Gogetter — not page text alone).

Lock backends, URLs, and params once they work. Saved `html_files` adapters are banned on a production refresh.

### 4.2 Enrichment

From `aggregator/`, on the enrich roster (see Playbook 2 section 7):

```bash
python3 resolve_website.py --roster <rows.json>
python3 enrich_site.py <campus> [roster_file]
python3 enrich_amenities.py <campus> [roster_file]
python3 enrich_listings.py <campus> [roster_file]
python3 build_json.py <campus> [roster_file]
```

Listings come from the building's own site or its local PM / realtor page, **never** from Apartments.com, Zillow, RentCollegePads, or a campus directory. Prefer platform JSON adapters, then a liberal first-party read. Never guess a price; use `price_status = not_publicly_listed`. LLM reads are last resort, one building at a time, only with `--llm`.

Cloudflare ladder for browser adapters: headless → headless with `~/.fml_dom_profile` → visible browser. Then a hand-saved rescue. Interactive CAPTCHAs are never solved.

### 4.3 Parity and completeness

- Run `python3 campus_completeness.py <campus> --reference <reference.json>` until it is clean or every miss has a cause and a rule.
- If this campus is being compared to FML_Data (UT) or to a previous engine:
  ```bash
  cd aggregator
  export FML_DATA_ROOT=/path/to/FML_Data
  python3 parity_harness.py tier-a
  python3 parity_harness.py tier-b
  python3 test_phase0.py    # offline groundwork checks, no network
  ```
  Tier A = same HTTP cassette, both code paths. Tier B = live, FML extractor then Rebuild, back to back. The harness does not solve challenges and does not call Algolia or Rate My Rent. Normalize number formatting (`1424` vs `1424.0`) and do not treat `scraped_at` as a data mismatch unless you intend to.
- After extractor changes, re-run `--check` on `scripts/sync_fml_extractors.py` and Tier A at least.

### 4.4 Archive → RMR review

Ingest the first full scrape into a new campus folder in the archive, upload to Drive under the same slug, then dry-run the discrepancy updater if the campus already has Rate My Rent listings. New buildings go into a review for Elijah; do not add them live until he says yes. See [docs/NEW_BUILDINGS_FOR_RMR.md](NEW_BUILDINGS_FOR_RMR.md) for the UT-era list format.

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Many Entrata / RentCafe buildings fail with `blocked_bot_wall` or Cloudflare on a cloud scrape | JSON/availability endpoints sit behind the same WAF as the marketing page. Cold cloud calls do not bypass it. | Tiered rescue: off-portal CMS or the real portal path (`/<city>/<slug>/student/`, `entrata.<site>`, `rentcafe_ysi` / `rentcafe_inline`) → headed box/Mac browser with `~/.fml_dom_profile` → cookie handoff after Elijah clears the check in real Chrome → hand-saved rescue. Never solve the challenge. Do not freeze `text_plan_list` when the status is `blocked_bot_wall`. |
| Interactive CAPTCHA appears mid-run | Site upgraded from a silent managed check to a human check. | Log `blocked_manual_review_needed`, stop touching that property, ask Elijah if a rescue is needed. |
| Headed run works on the box but cloud agent returns empty / launch errors | Playwright / `node_modules` missing on that machine; `NODE_PATH` wrong. | Install Playwright and browsers where the scrape runs, or run DOM buildings on the box or Mac. Re-run only those sources. Do not "fix" it by skipping DOM buildings silently. |
| Quarters / GrandMarc / Inspire suddenly empty | Stale marketing URL; plans live on the student portal or `entrata.*` host. | Pin the portal URLs in `properties_config.json` / `listing_config.json` and merge to main (code/config). Re-scrape those `source_id`s with `--only` / `--patch`. |
| Torre stuck as not listed, or prices discarded | Old `params.force_not_listed` pin. | That flag was removed. Do not put it back. Re-scrape Torre via `wp_entrata_json`. |
| Icon (or similar Entrata white-label) has duplicate labels like "A1 1 Bed, Call for Pricing" plus a clean "A1" | Overlapping cards; image and beds on only one copy. | `params.clean_labels` (and Rebuild `clean_dedupe_rows`). Keep the merged clean label. Icon has also gone `no_rows` when the site removed listings — treat as a possible temporary empty, not a standing skip. |
| Villas on Guadalupe, 21 Pearl, Axis West Campus, Signature 1909 return no or partial plans | LeaseLeads markup; a partial HTTP read of the JSON is not enough. | Use the synced `villas_wp` parser (FML_Data `a953774`): browser read of `[data-ll-floor-plan-card]` / `data-ll-floor-plan-lease-terms`. Lowest term price on the row; other terms in availability text. Re-run those four after any scrape that landed before the fix. |
| Yugo (Rio, Corner, Nueces, Waterloo) missing plans or plan images | Plans live on per-room-type / `product-tile` pages, not a single floor-plan list. | Pin backend `yugo` and `params.gtm_name`. Do not let `text_plan_list` win. Rescue images from the room-type pages if the list page has none. |
| Union on San Antonio (and other Unions) have prices but blank or wrong layout images | Image picker grabbed the wrong asset, or the bot-walled page never yielded plan images. | Re-scrape with the headed path; use the Playbook 2 section 4x image gates. Match replacements in the RMR review; do not blank a live image. |
| 1883 Montgomery plans appear under Cameron, or one listing absorbs the other | Shared leasing office; names collide if you alias too aggressively. | Keep two pins, two `source_id`s, two RMR listings. Elijah already decided Montgomery stays its own listing (with its plans). |
| Villas on 26th is empty with HTTP 403 | Cloudflare block. | Leave last-good archive rows in place; do not mark the whole building gone. Retry only after Elijah clears the check. |
| Texan 26 is a single placeholder row | Leasing portal blocked; no public pricing. | Keep the placeholder. Do not invent rents. Same family as other `no_public_pricing` / `layouts_only` pins (Town Lake names, Tower View, sometimes Icon). |
| `(no public pricing on site)` or `not_publicly_listed` rows | Site truly has no public rent, or the extractor could not see it. | Keep the placeholder and `params.reason` if pinned. The updater must **not** turn placeholder-only buildings into hides/adds. A scrape with rows but no prices while live has 3+ priced plans is degraded — leave the live building as-is. |
| Playwright `execution context destroyed` / nav flakes (Redpoint, Ion, Lark, Noble, and similar) | Client-side navigation killed the page mid-extract. | Retry once later in a headed session; do not loop aggressively. Noble's locked URL must keep `?_lease_term=fall`. |
| Box cannot `git push` / `gh` says not logged in | Box has no GitHub CLI login. cursor-github cannot commit files. | Commit from the Mac clone (`git pull --rebase`, commit, `git push`) or hand a tarball to a cloud agent. Ask before setting up `gh auth login` on the box. |
| Every-4-days routine dies mid-scrape or never finishes | Grok Bot weekly usage exhausted (it can be most of the plan's usage). | Check usage first. If a run was cut off, do not ingest a partial file as `--full`. Resume or re-run when the quota resets; tell Elijah. |
| Thousands of "changes" after ingesting a mid-November file | The 2026-11-17 CSV was a **Rate My Rent export**, not a scrape. Formatting differences looked like field changes. | Never use an RMR export as a scrape baseline. Mark it as an export in the archive or exclude it from `rebuild-history`. Compare reviews to a real `run.py` / Rebuild refresh (the 2026-11-25 baseline is the one from that week). |
| Unit `objectID` collisions or unstable IDs | Mixing formats. Legacy/Algolia IDs are content-derived: `<property-slug>__<label-slug>[-<sqft>]` (example: `crest-at-pearl__2-bed-2-bath-g-900`). Collisions on the Algolia push are broken by `layout_image_url` then `base_rent`, never source order. `property_objectID` is the canonical name slug and must match `rentright_buildings`. An unlocked Rebuild refresh path that uses `<objectID>__<index>` is not the Algolia id. | Use `legacy_emit.unit_object_ids` / the Algolia transformer for anything that will be pushed or matched to RMR. Do not match a `-SHARED` plan to a non-SHARED plan, even if objectIDs collide. |
| Algolia push aborted on a name | Canonical name failed `price_name_aliases.json` / `properties.csv`. | Fix the alias or the scrape name; never push an unresolved name. |
| `base_rent` missing after transform, or a $2-style row disappeared | Push drops `base_rent < 300` to the dropped/audit file; yearly / `base_rent > 6000` is nulled and kept. | Inspect `algolia_units_21f.dropped.json`. Do not force a sub-$300 rent live. The RMR updater also **holds** price jumps over 45% and rents under $300. |
| Updater would delete plans that the site stopped advertising | Wrong mental model. | Set availability to **"No longer advertised"**. Never remove. If a plan comes back, bring it back. Hold the building if more than 8 plans or more than 40% would flip. Failed/empty buildings are left untouched. |
| Fall 2027 (or "next year's lease") plans marked not available | Availability text was not treated as a current leasing cycle. | Fall 2027 counts as **Available**. Normalize to the fixed set: Available / Limited / Sold Out / Waitlist / No longer advertised. |
| Live images or prices went blank | A write filled empty scrape fields over good live values. | Never blank a price or an image. Refresh images when they *differ*; use `--no-refresh-images` only to fill blanks. Re-read each building before write; skip the call on drift. |
| Apply run retried errors or wrote two buildings at once | Process not followed. | One building at a time. Approval file + `RMR_APPLY_CONFIRM=I_REVIEWED_THE_PLAN`. No retries, stop on the first write error, 3 seconds between writes. Held buildings need `override_held: true` in the approval file. |
| Cloning `FML_Rebuild` or `FML_Data` on the box returns 404 / auth required | The box has no `gh` login; both repos are private. | Pull `origin/main` on the Mac (`gh` is already logged in), stage a tarball or git bundle under `~/fml-migration/` (not `/tmp`), and transfer with `CopyToBox`. See also the next two rows. |
| `CopyToBox` fails with `Path is outside the allowed local-exec root` | Staging the archive in `/tmp` on the Mac is outside the allowed root. | Put the tarball or bundle in the user's project workspace, e.g. `~/fml-migration/fml_repos_main.tar.gz`, then call `CopyToBox`. |
| `git clone repo.bundle dest` is an empty `master` with no files | `git bundle create <file> origin/main` omitted `HEAD`. | Include HEAD when bundling (`git bundle create repo.bundle HEAD origin/main`), or `git init`, `git fetch <bundle> '+refs/*:refs/*'`, then `checkout -b main <commit_sha>`. |
| DOM extractors fail or silently fall back on the box even when Playwright is installed under `/workspace/pwdeps` | Node cannot resolve `playwright` from `npm root -g`, or Chromium has no Xvfb display. | Symlink `/workspace/pwdeps/node_modules/playwright` to `/home/box/.local/lib/node_modules/playwright`. Confirm Chromium in `~/.cache/ms-playwright/`. For `DOM_HEADED=1`, run Xvfb and set `DISPLAY=:4`. For FML_Data `run.py`, set `NODE_PATH=/workspace/pwdeps/node_modules`. |
| `refresh_listings.py` exits `2` even though `units_YYYY-MM-DD.json` and the 20-column files were written | One or more `listing_config.json` entries hit `saved_html_banned` (`text_plan_list`, or any backend with `params.html_files`). The script raises `SystemExit(2)` *after* writing outputs. On 2026-11-25: 9 unlocked UT buildings; 54 A&M buildings. | Do not chain the refresh with `&&`. Capture `; RC=$?` and confirm the output files exist. Re-enrich banned entries to a live HTTP/DOM adapter (or a checked-in rescue). Do not treat exit 2 as "the scrape produced nothing." |
| A&M `headed_rescue` buildings fail with `[Errno 2]` for `/Users/elijahwangchen/FML_rebuild/data/texas_am/rescues/<slug>.json` | `listing_config.json` stores absolute Mac paths in `params.file`. The 13 rescue JSONs are already in git under `data/texas_am/rescues/`. | Store `params.file` as a repo-relative path (`data/<campus>/rescues/<slug>.json`), or resolve it from the repo root. In a read-only run, remap the Mac prefix only in the runner. Never commit `/Users/<user>/...` paths. |
| `refresh_listings.py texas_am` writes `units_*.json` but no `advertised_prices_*.csv` / `.json` / `.unit_ids.json` | `write_legacy()` runs only for `"locked": true` properties. A&M currently has **0** locked pins. | For a one-off, call `legacy_emit.property_record()` + `write_legacy()` over the extracted rows. For production, lock verified live configs (or change the locked-only gate in a later phase) so the 20-column emit happens on every refresh. |
| Stdout from `refresh_listings.py` stops for 5–8+ minutes on a `jonah_detail_json` building (e.g. Elle West Ave) | The extractor sleeps **2 seconds after every floorplan slug**. Elle West Ave has 156 plans, so ~8 minutes with no per-slug log. `ps` may show `hrtimer_nanosleep` and no socket. | Do not kill the process. Watch `/proc/<pid>/io` `rchar`/`syscr` over 4–5 seconds — bytes read should keep climbing between sleeps. A full UT refresh is about 20–25 minutes (22m 13s on 2026-11-25). |
| Batch DOM refresh stalls ~5 minutes per blocked site | `FML_SOLVE_WAIT_S` defaults to **300** seconds when a headed/profile run hits a challenge page. | Export `FML_SOLVE_WAIT_S=25` (or similar) for batch runs so hard-blocked sites fail fast. Never bypass an interactive CAPTCHA or Cloudflare challenge. |
| Joining `advertised_prices_*.json` to `listing_config.json` by `objectID` drops ~17 UT properties | `legacy_emit` keeps FML_Data canonical slugs (`callaway-house`, `quarters-on-campus-nueces`, `sabina-condominiums`); Rebuild `listing_config.json` uses roster slugs (`the-callaway-house-austin`, `the-quarters-nueces-house`, `sabina`). | Fall back to `property_name` (or `source_id`) when the `objectID` is not found. |
| `g5_sniff` (Promontory Point, 50 units) looks like a parity mismatch against an otherwise identical baseline | Unit order from the DOM sniff is not stable. The 50 objects were field-for-field identical as a multiset. | Compare `g5_sniff` (and similar sniffed lists) as a multiset, or sort by `(unit_or_floorplan_label, base_rent, availability)`. Do not require identical array index order. |
| `common.name_sim()` raises `ModuleNotFoundError: No module named 'rapidfuzz'` | `rapidfuzz` is not installed on the box. | `refresh_listings.py` and `test_phase0.py` do not call `name_sim()`, so a refresh can run without it. Install `rapidfuzz` in a venv before discovery/matching scripts from Playbook 1. |
| A&M `rentcafe_inline` sites are `saved_html_banned`, and fail with HTTP 403 if you only strip `html_files` and retry over `urllib` | Eight A&M configs still point at gitignored Mac HTML snapshots; the live RentCafe pages 403 to plain HTTP. | During an enrichment pass, move them to Playwright DOM (`rentcafe_ysi`). Do not treat a 403-to-urllib as "the building has no plans." |
| A&M `jsonld_offers` / `university_rates` are banned because of `params.html_files`, but most work live | The ban is triggered by the Mac snapshot path, not by a dead adapter. Diagnostic with `html_files` stripped: 6/8 `jsonld_offers` ok, 2 HTTP 500 (`Sierra Condos`, `Canyon Village Apartments`); both `university_rates` ok (`The Gardens Apartments`, `White Creek Apartments`). | Drop `html_files` from those configs and keep the live adapter. Leave the two HTTP 500 buildings as known live failures; do not "fix" them in a refresh. |

---

## 6. Rate My Rent updater rules and guards

Canonical detail: [FML_Data tools/rmr-discrepancy-updater/README.md](https://github.com/Elijahwanghcen/FML_Data/blob/main/tools/rmr-discrepancy-updater/README.md). Current matcher is `discrepancy_updater.py` (v4).

**Policy Elijah has already set:**

- Plans no longer advertised stay on Rate My Rent with availability **"No longer advertised"** — never deleted.
- Fall 2027 (next-year leasing) counts as **Available**.
- Availability wording-only rewrites belong in the proposed changes.
- Layout images that differ from the scrape are refreshed; images are never blanked.
- Removed plans that later reappear are brought back.
- Placeholder scrape rows are never turned into adds or hides.
- Approved changes are applied **one building at a time**. He reviews each building.

**Guards (do not weaken these):**

- Hold a building if a large share of its plans would flip (>8 plans or >40%).
- Hold price jumps over **45%** and rents under **$300**.
- Never blank a price or an image.
- Re-read each building before writing; skip if live values drifted from the plan.
- No retries. Stop at the first write error. Pause 3 seconds between writes. Cap at 400 writes.
- `--apply` requires an approval file (`approved_by`, `approved_at`) and the exact env value `RMR_APPLY_CONFIRM=I_REVIEWED_THE_PLAN`.
- Held batches refuse `--apply` unless the approval file has `override_held: true`.
- MCP writes are refused unless the guarded apply path sets `allow_write=True`.

Apply one building (only after he approved that building):

```bash
# copy approvals/<building>.TEMPLATE.json -> approvals/<building>.json and fill approved_by / approved_at
RMR_APPLY_CONFIRM=I_REVIEWED_THE_PLAN python3 discrepancy_updater.py --apply \
  --plan runs/<date>/plan.json --only <building> \
  --approval runs/<date>/approvals/<building>.json --out runs/<date>
```

Public read-only listing API (no key in this file): `/api/listings?campus=ut-austin` and `/api/listings/page?campus=ut-austin&id=ID` on the Rate My Rent workers host. MCP read tools: `get_listing`, `search_listings`.

---

## 7. Archive and Google Drive

Code: `tools/scrape_archive/`. Output (gitignored): `tools/scrape_archive/output/`.

Drive: [FML Scrape Archive](https://drive.google.com/drive/folders/1WYFc1tCirxxC0MiwhkIxk5c6fNLmlIu8).

The master list keeps each listing's latest values plus `first_seen`, `last_seen`, and `last_changed`. A weekly run that only refreshes some listings does not erase the rest. A building whose scrape failed is not wiped. Stable key: `{property}__{label}`.

History rebuild from past FML_Data scrapes:

```bash
python3 -m tools.scrape_archive rebuild-history --campus ut-austin --fml-data /path/to/FML_Data
```

UT files come from `austin_leases_units/`. Prefer a CSV that has at least one real listing; some dates are JSON-only; the 2026-08-06 CSV is a one-row failure stub (use the JSON). After a rebuild, treat any RMR export (notably 2026-11-17) as an export, not a scrape.

The first history rebuild (10 runs, 2026-08-06 through 2026-11-17) is already in Drive: snapshots, per-run change logs, masters, and the append-only change history. Most of the 2026-11-17 "changes" were export formatting, not real market moves.

The package does not talk to Algolia or Rate My Rent.

---

## 8. Manager bot and multi-bot direction

End state Elijah asked for: **a manager that coordinates several Grok Bots**, each running scrapes with the extractors and fingerprints in FML_Rebuild, including new campuses.

Until that manager exists, work this way:

- **One source of truth for code:** merge extractor, fingerprint, config, and runbook changes to `main` on the repo they belong in (Rebuild and/or FML_Data) so every bot pulls the same tree.
- **Non-overlapping boundaries** when running agents in parallel (example that already worked: a cloud agent on shared extractors / locked sources / parity; Claude on the Mac on a LeaseLeads parser; the box on a baseline `run.py` scrape). Do not let two agents edit the same file or apply RMR writes together.
- **A manager bot should:** assign a campus or a backend family, require a completeness report and an archive ingest, collect review markdown, and **never** apply RMR or Algolia itself without Elijah's yes on the named buildings.
- **Each worker bot should:** read this handbook first, follow the playbooks, refuse to print secrets, and stop at the first unsafe write.
- Keep FML_Data `run.py` as the UT parity baseline until Elijah cuts a family (for example the 36 HTTP-feed buildings) over to Rebuild.

---

## 9. Checklist before telling Elijah "done"

Do not say a scrape, a campus, or a migration step is done until all of these that apply are true:

- [ ] `main` was pulled; extractors `--check` clean if both repos were used.
- [ ] The run finished (or a partial run is clearly labeled; never ingested with `--full`).
- [ ] Failure list is in the report, with the rescue tier used or needed — including Cloudflare / CAPTCHA buildings left for him.
- [ ] No CAPTCHA or Cloudflare challenge was bypassed; no guessed prices; no blanked prices or images.
- [ ] Stub / no-public-pricing / blocked portal buildings did not wipe last-good archive rows.
- [ ] Archive ingest completed for the campus; 2026-11-17-style exports were not treated as scrapes.
- [ ] Drive upload finished, or the `upload_plan.json` is ready and you said why it was not uploaded.
- [ ] For a new campus: `campus_completeness.py` was run; every miss has a cause; pinned sources are locked; A&M-style directory + PM + rescue path was considered.
- [ ] For extractor changes: Tier A (and Tier B if live network was available) was run, or you said which family was not tested and why (for example Playwright missing).
- [ ] Code/config changes are on `main`. Data, Algolia, and Rate My Rent were **not** pushed unless he explicitly approved the named buildings / index.
- [ ] A review markdown is ready for any RMR updates; apply was not run "to be helpful."
- [ ] No secret values appear in the report, the commit, or the review file.
- [ ] The report includes counts, dates in America/Chicago, links to commits or Drive, and a clear list of decisions still waiting on him.

---

## 10. Lessons from the 2026-11-25 Rebuild scrape

Field notes and full commands: [docs/lessons/2026-11-25-rebuild-scrape.md](lessons/2026-11-25-rebuild-scrape.md) (copied from the run's `difficulties.md`). Source summaries: `/workspace/fml-scrape/2026-11-25-rebuild/ut-austin/summary.md` and `texas-am/summary.md`.

**Run meta (America/Chicago):** Rebuild `refresh_listings.py` at [`0e2981b`](https://github.com/Elijahwanghcen/FML_Rebuild/commit/0e2981b3297d3368f3088c5e362dcc8f77879856) (Phase 0 `main`). Compared to the morning FML_Data baseline (`402b54a` full pass + [`a953774`](https://github.com/Elijahwanghcen/FML_Data/commit/a953774aed5fd176d22f815d96a473588ecb9d8a) `villas_wp` merge): **2,627 rows / 145 locked properties**. Linux box, `FML_SOLVE_WAIT_S=25`, Playwright 1.64.1 under `/workspace/pwdeps`, Xvfb `DISPLAY=:4`. UT ran 10:12:40–10:34:53 CST (**22m 13s**). A&M ran ~10:12–10:19 CST. No CAPTCHA or Cloudflare challenge was bypassed; nothing was written to Algolia or Rate My Rent; this scrape did not itself ingest the archive or upload Drive (outputs remain under `/workspace/fml-scrape/2026-11-25-rebuild/`).

### UT Austin

`listing_config.json` has **185** properties (**145** locked, **40** unlocked). Exit code **2** because of `saved_html_banned` on unlocked entries; the 20-column legacy CSV/JSON and `units_2026-11-25.json` were written before that exit.

- **Locked 145 / 2,627 rows** matched the FML_Data baseline property set and row counts **145/145** (2,220 `listed`, 407 unpriced or stub).
- Full refresh across 185: **174** ok (**3,038** ok unit rows: 2,625 from 143 ok locked + 413 from 31 ok unlocked), **11** failed.
- **Locked failures (same as the morning baseline):** Villas on 26th (`vnue_grid_static`) HTTP **403**; 1883 at Montgomery House (`entrata_pp`) `no_rows`. Texan 26 stays a `no_public_pricing` placeholder (Entrata portal Cloudflare-blocked; not bypassed). Other locked no-public-rent / unpriced clusters include the Town Lake names, Tower View, Venue on Guadalupe, Icon (Sold Out), 1883 at Cameron House (contact/unpriced), and the co-ops.
- **DOM Tier B (Playwright, 49 properties, 1,354 rows): 49/49 exact** vs the baseline (48 ordered exact; **1** exact as a multiset — Promontory Point, `g5_sniff`, 50/50 units identical when order is ignored). Families: `entrata_pp` 14, `landmark` 7, `rentcafe_ysi` 5, `repli360` 5, `villas_wp` 4 (93/93, including the LeaseLeads fix), `yugo` 4, plus `ion_wp`, `sinclair_wp`, `g5_sniff`, `gogetter_wc_floorplans`, `rambler_lvbode`, `realpage_sniff`, `rise_units`.
- **Only live drift:** two `jonah_detail_json` buildings whose floor-plan pages changed between the morning scrape and ~10:30 AM — Estates at East Riverside (`3X3` advertised range `$1311-$1495` → `$1311-$1489`) and Village at East Riverside (`Two Bedroom` dropped the `$1154-$1157` range text). Row counts still matched (30/30). This is site change, not an extractor bug.
- **9 unlocked UT `saved_html_banned`:** The Hive Red River, Barranca Square Student Apartments, Melroy Apartments, Wedgewood Condos, Lenox Condos, West Ridge Condos (`text_plan_list`); Volume, North 40, Avana Apartments (`rentcafe_inline` with `params.html_files`). The other 31 unlocked buildings were ok (413 rows, 225 priced).

### Texas A&M

A&M is **not** production-ready as a locked 20-column refresh yet.

- `roster_final.csv`: **173** rows, including three exact-name duplicates (Domain Northgate, The Ridge, EVER College Station). `listing_config.json`: **113** properties, **0** with `"locked": true`, so unmodified `refresh_listings.py` **does not call `write_legacy()`** — only `units_2026-11-25.json` and `refresh_2026-11-25.md`. About **59** roster rows are missing from the config (33 Tier A, 26 Tier B), e.g. The Lory of College Station, Lory of Bryan, University Heights, Howdy Apartments, The Penny, Country Place Apartment Homes, The Atrium.
- **13 `headed_rescue` entries** use hardcoded `/Users/elijahwangchen/FML_rebuild/data/texas_am/rescues/<slug>.json` paths. The JSON files *are* in git under `data/texas_am/rescues/`; they failed on Linux only with `Errno 2`. Remapping the prefix recovered all 13 (229 rows, 221 priced).
- **54 `saved_html_banned`:** **36** `text_plan_list` (no live adapter); **8** `rentcafe_inline` (banned for Mac `html_files`; all 8 also **403 to urllib** live — need Playwright `rentcafe_ysi`); **8** `jsonld_offers` (banned for `html_files`; **6 live ok** / 43 rows, 39 priced; **2 HTTP 500:** Sierra Condos, Canyon Village Apartments); **2** `university_rates` (banned for `html_files`; **both ok live:** The Gardens Apartments, White Creek Apartments).
- Unmodified refresh: **46** ok / **472** unit rows, **67** failed (54 banned + 13 path errors), **539** records in `units_*.json`, exit code 2, no 20-column emit. A read-only legacy emit that remapped only the 13 rescue paths produced **755** CSV rows (59 ok / 701 units, plus 54 stubs). Six ok buildings still had no public rents (Berkeley House, The Element at University Park, Sterling College Station, Caprock Crossing, Falcon Point Condos, Eastmark Apartments).

### Difficulties and fixes from this run

These are also in the [troubleshooting table](#5-troubleshooting) and in [docs/lessons/2026-11-25-rebuild-scrape.md](lessons/2026-11-25-rebuild-scrape.md).

1. **Private repos, no `gh` on the box.** Pull on the Mac, stage the transfer under `~/fml-migration/` (not `/tmp` — `CopyToBox` rejects that path), then `CopyToBox`.
2. **Git bundle without `HEAD` clones an empty repo.** Bundle `HEAD origin/main`, or `git init` + `fetch '+refs/*:refs/*'` + `checkout -b main <sha>`.
3. **Playwright symlink + `DISPLAY`.** Link `/workspace/pwdeps/node_modules/playwright` at `npm root -g` (`/home/box/.local/lib/node_modules/playwright`); Chromium in `~/.cache/ms-playwright/`; Xvfb `DISPLAY=:4` if headed; `NODE_PATH=/workspace/pwdeps/node_modules` for FML_Data `run.py`.
4. **Exit code 2 from `saved_html_banned` after outputs are written.** Do not use `&&`. Capture `RC=$?` and verify the files. Then re-enrich banned configs.
5. **Hardcoded `/Users/elijahwangchen/...` rescue paths.** Use repo-relative `data/<campus>/rescues/<slug>.json`.
6. **Zero `"locked": true` means no 20-column emit.** Lock verified A&M (and new-campus) configs, or call `write_legacy()` explicitly.
7. **`jonah_detail_json` 2s/plan pauses look like a hang.** Check `/proc/<pid>/io`; do not kill it. Budget ~20–25 minutes for a full UT run.
8. **`FML_SOLVE_WAIT_S` defaults to 300.** Set `FML_SOLVE_WAIT_S=25` on batch runs. Never bypass challenges.
9. **Legacy vs Rebuild `objectID` mismatch (17 UT properties).** Join on `property_name` or `source_id` when the slug differs.
10. **`g5_sniff` order is unstable.** Compare as a multiset / sorted by label, rent, and availability.
11. **`rapidfuzz` is missing on the box.** Refreshes still run; install it before Playbook 1 discovery matching.

### Onboarding and refresh commands (from this run)

Always use `python3 -u` so logs stream line by line. Refresh into a scratch checkout if you need the reference clone left untouched (`refresh_listings.py` writes `data/<campus>/out/` and `legacy_emit.py` creates `csv outputs/`).

```bash
export FML_SOLVE_WAIT_S=25
python3 -u aggregator/refresh_listings.py ut_austin
# expect exit 2 when saved_html_banned entries exist; check that outputs were written
python3 -u aggregator/refresh_listings.py ut_austin --only <objectID_or_source_id> --patch

python3 -m tools.scrape_archive ingest --campus ut-austin \
  --input "data/ut_austin/out/csv outputs/advertised_prices_YYYY-MM-DD.csv"

python3 aggregator/test_phase0.py   # after touching extractors or legacy_emit
```

For **Texas A&M or a new campus:** write `campuses/<slug>.json` (include `neighbor_cities`); follow Playbook 1 (dedupe by `place_id` / normalized address — A&M already has leasing-office / exact-name duplicates); run completeness against the full roster (A&M config is missing ~59 names); follow Playbook 2 so `listing_config.json` has **zero** `text_plan_list` and **zero** `params.html_files` Mac paths; store rescues as repo-relative paths; mark verified live configs `"locked": true` so `write_legacy()` emits the 20-column CSV, JSON, and `unit_ids.json`.
