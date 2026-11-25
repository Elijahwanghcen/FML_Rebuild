# Grok Bot handbook — campus listing maintenance

**Audience:** a Grok Bot that maintains an already-built campus: re-scrape listings, add a building that uses an existing extractor or fingerprint, archive the run, and propose Rate My Rent updates. New-campus onboarding is a different process and is not covered here.

**Owner:** Elijah WangChen. Speak as him on his accounts. Report times in America/Chicago.

This is the operator runbook. It does not replace the playbooks.

| Doc | Use it for |
|---|---|
| [docs/PLAYBOOK_2_ENRICHMENT.md](PLAYBOOK_2_ENRICHMENT.md) | Official websites, platform fingerprints, listings adapters, Cloudflare ladder, plan images |
| [tools/scrape_archive/README.md](../tools/scrape_archive/README.md) | Snapshot, change log, master list, Drive upload plan |
| [FML_Data tools/rmr-discrepancy-updater/README.md](https://github.com/Elijahwanghcen/FML_Data/blob/main/tools/rmr-discrepancy-updater/README.md) | Rate My Rent dry-run and guarded apply (v4, `discrepancy_updater.py`) |

Live listing updates go only through the Rate My Rent MCP. Algolia is no longer pushed.

---

## 1. Rules

**Needs Elijah's explicit yes** (a previous yes on a different building or date does not count):

- Any write to live Rate My Rent (`update_listing`, `add_listing_record`, or `discrepancy_updater.py --apply`).
- Hiding, deleting, or merging listings.

A dry-run and a review markdown are always fine. Send the review and stop.

**Already standing (code and config only):** merge scraper, Rebuild, and updater *code and config* straight into `main` on FML_Rebuild and FML_Data, with no PR review. This is not approval to change live Rate My Rent data.

**Never:**

- Bypass a CAPTCHA or Cloudflare challenge (no solver, no cookie theft, no evasion). Log it, leave that property, and ask Elijah to clear it in a real browser if a rescue is needed.
- Drive box Chrome from Shell. Use headed-browser / desktop tools.
- Print or commit secrets, approval files, cookie jars, or `~/.claude.json`.
- Invent a price. Use `price_status = not_publicly_listed` or a placeholder row.
- Ingest a Rate My Rent export as if it were a scrape.

**Secrets — name the file, never the value:**

| Secret | Where it lives |
|---|---|
| Rate My Rent MCP Bearer token | `~/.claude.json` under `mcpServers.rmr`. Operator header: `X-RMR-Operator: elijah`. `tools/rmr-discrepancy-updater/mcp_client.py` reads it in-process and must never print it. |
| Google Drive upload creds (optional CLI uploader) | Environment at upload time only: `FML_DRIVE_ACCESS_TOKEN`, or `FML_DRIVE_REFRESH_TOKEN` + `FML_DRIVE_CLIENT_ID` + `FML_DRIVE_CLIENT_SECRET`, or `FML_DRIVE_SERVICE_ACCOUNT_FILE` / `GOOGLE_APPLICATION_CREDENTIALS`. Usual path is the Google Drive MCP, which does not need these. |
| Browser profile / clearance cookies | `~/.fml_dom_profile`, `~/.fml_dom_profile_manual`, and any cookie-handoff JSON. Never commit them. |

**Machines:**

- Elijah's MacBook Air (`machineId` `5f889b5f-1d67-456e-a0e4-0581d3062cf8`): `~/fml-migration/FML_Rebuild` and the FML_Data clone beside it. `gh` is logged in. Every command on this machine needs his approval — batch them. Stage transfer files under `~/fml-migration/`, never `/tmp` (`CopyToBox` rejects `/tmp`).
- The shared box has no `gh` login. Do not assume a box clone is current. For Playwright DOM scrapes: `/workspace/pwdeps/node_modules/playwright` symlinked at `npm root -g` (`/home/box/.local/lib/node_modules/playwright`), Chromium in `~/.cache/ms-playwright/`, `DISPLAY=:4` when headed, `FML_SOLVE_WAIT_S=25` on batch runs, `NODE_PATH=/workspace/pwdeps/node_modules` if a Node extractor cannot resolve Playwright.

**Slugs:** scripts and `campuses/*.json` use `ut_austin` and `texas_am`. The scrape archive `--campus` flag uses `ut-austin` and `texas-am` (aliases such as `ut_austin` / `tamu` are accepted).

---

## 2. Run a campus scrape

A refresh is deterministic: read `data/<campus>/listing_config.json`, do not write new extractors mid-run, and do not re-detect backends. Failures get a rescue or a later enrichment pass.

`refresh_listings.py` writes `data/<campus>/out/`. Use a scratch checkout if you need a clean clone left untouched. Always `python3 -u` so logs stream line by line. Run aggregator scripts from `aggregator/` (they import sibling modules).

### 2.1 Before you start

1. Check weekly usage. If it is nearly gone, do not start a full scrape.
2. `git pull` on FML_Rebuild `main` (and FML_Data if you will run the updater).
3. If FML_Data extractors changed: `python3 scripts/sync_fml_extractors.py --check "$FML_DATA_ROOT"` from the Rebuild root, then sync and merge to main if they drifted.
4. Confirm Playwright is resolvable before any DOM backend run. A missing install looks like every DOM building failing at once.

### 2.2 Scrape

```bash
cd aggregator
export FML_SOLVE_WAIT_S=25
python3 -u refresh_listings.py ut_austin
# or: python3 -u refresh_listings.py texas_am
# one building, merge into the latest dated units file:
python3 -u refresh_listings.py ut_austin --only <objectID_or_source_id> --patch
```

Shared `source_id`s are fetched once. Same-host requests wait 4 seconds. A failure becomes an explicit `(extraction failed)` stub, never a silent omission.

**Outputs** (only locked properties get the 20-column emit):

- `data/<campus>/out/units_YYYY-MM-DD.json`
- `data/<campus>/out/refresh_YYYY-MM-DD.md` — failures and big moves (>15% median rent, or a large row-count swing)
- For `"locked": true` properties: `advertised_prices_YYYY-MM-DD.json`, `csv outputs/advertised_prices_YYYY-MM-DD.csv`, and `advertised_prices_YYYY-MM-DD.unit_ids.json`

**Exit code 2** means one or more configs hit `saved_html_banned` (`backend` is `text_plan_list`, or `params.html_files` is set). Outputs are written *before* the exit. Do not chain the command with `&&`. Capture `; RC=$?` and confirm the files exist. Then fix the banned configs (see the troubleshooting table). A campus with zero locked properties will not emit the 20-column files.

Read `refresh_YYYY-MM-DD.md`. Verify big swings by hand. Do not "fix" a real price move in the refresh itself.

### 2.3 Failures (cheap first)

Never solve a challenge. Order:

1. **Off-portal CMS or the real portal path.** Many Entrata buildings need `/<city>/<slug>/student/` (or `conventional/`), or `entrata.<site>`, not the marketing Floor Plans page. Quarters houses: `quartersoncampus.com/austin/{grayson,nueces,sterling}/student/`. GrandMarc: `entrata.grandmarcaustin.com`. Inspire: `entrata.inspire22nd.com`. Prefer a JSON/CMS feed when it exists.
2. **Headed browser** with a persistent profile (`~/.fml_dom_profile`). Only when `DOM_PROFILE`, `DOM_HEADED=1`, or `DOM_CHALLENGE_WAIT_S` is set does the extractor wait for a *non-interactive* "just a moment" page. Interactive checks still stop the property. For a visible, one-building hand-solve:
   ```bash
   cd aggregator
   python3 solve_blocked.py <campus> --only <objectID> --wait 300
   ```
   That writes `data/<campus>/rescues/<objectID>.json`. Point `params.file` at the **repo-relative** path `data/<campus>/rescues/<objectID>.json`, never `/Users/...`.
3. **Cookie handoff.** Ask Elijah to clear the challenge in his own Chrome, then reuse that clearance. Do not print cookies.
4. **Chronic failure.** Leave last-good rows in the archive master, keep a stub in this run, and report it. Do not wipe the building.

After a parser or URL fix, re-run only those sources with `--only` / `--patch`. Do not ingest the unfixed empty rows as a real scrape of those buildings.

### 2.4 Then archive, then a Rate My Rent review

Follow [section 5](#5-save-the-scrape-archive-and-drive) and [section 6](#6-rate-my-rent-mcp-only). Nothing goes live until he approves a named building.

---

## 3. Add a building to an existing campus

This is for one (or a few) buildings on a campus that already has extractors and fingerprints. It is not new-campus discovery.

1. **Confirm it is actually new.** Search `data/<campus>/listing_config.json` and `roster_final.csv` by name, address, and website. Do not alias two distinct pins just because they share a leasing office (UT examples: 1883 at Cameron House vs 1883 at Montgomery House; the four Quarters houses).
2. **Official website only.** The building's own site or its local PM / realtor page. Never Apartments.com, Zillow, RentCollegePads, or a campus directory. If the site is unknown:
   ```bash
   cd aggregator
   python3 resolve_website.py "<Name>" "<City>" "<ST>" "<street address>"
   ```
3. **Reuse an existing backend.** If a sibling building already scrapes the same platform, copy that `listing_config.json` row and change `objectID`, `property_name`, `address`, `url`, and params. Share `source_id` only when it is truly the same feed. Known patterns: `acc_lightning`, `entrata_pp` / `wp_entrata_json`, `rentcafe_ysi` (Playwright DOM — not `rentcafe_inline` over plain HTTP), `yugo` with `params.gtm_name`, `villas_wp` (LeaseLeads), `jonah_detail_json`, `g5_sniff`, `realpage_sniff`, `jsonld_offers`, `university_rates`, `gogetter_wc_floorplans`.
4. **If the platform is not obvious,** detect it without rewriting the campus config. Write a **one-building** roster JSON (keys at least `canonical_name`, `aliases`, `building_type`, `address`, `website`; add `floorplans_url` and `"website_locked": true` when the URL is confirmed) and crawl only that file:
   ```bash
   cd aggregator
   python3 enrich_site.py <campus> /path/to/one_building.json
   python3 enrich_listings.py <campus> /path/to/one_building.json
   ```
   **Do not run `enrich_listings.py` against the live `listing_config.json` on a partial roster.** `merge_detected` keeps locked rows but **drops every unlocked row the run did not see**. That will wipe unlocked buildings (and the entire A&M config today, which has zero locked pins). Run detection in a scratch checkout, or append the new property dict to `listing_config.json` by hand. Never freeze `text_plan_list`, `llm_page_read`, or `params.html_files`.
5. **Lock only after a live scrape works.** `"locked": true` is what includes the building in the 20-column emit. Set it after `--only` returns real rows (or a deliberate `not_publicly_listed` placeholder). Merge the config change to `main`.
6. Refresh with `--only` / `--patch`, ingest the run **without** `--full`, and include the new building in the Rate My Rent review. Do not add it live until he says yes.

Listings come from first-party pages. LLM reads are last resort, one building at a time, only with `enrich_listings.py --llm`.

---

## 4. Checklist

A scrape or a building add is not done until the items that apply are true:

- [ ] `main` was pulled; extractors `--check` clean if both repos were used.
- [ ] The run finished, or a partial run is clearly labeled (never ingested with `--full`).
- [ ] `refresh_YYYY-MM-DD.md` was read; failures and big swings are in the report, with the rescue used or still needed.
- [ ] The scrape was ingested into the archive; untouched properties were carried forward; Drive was updated.
- [ ] Review markdown was sent; **nothing was written to live Rate My Rent** unless he already approved a named building.
- [ ] New or changed listing-config / extractor code was merged to `main`.

---

## 5. Save the scrape (archive and Drive)

From the FML_Rebuild repo root. Details: [tools/scrape_archive/README.md](../tools/scrape_archive/README.md). Output is gitignored under `tools/scrape_archive/output/`.

```bash
python3 -m tools.scrape_archive ingest --campus ut-austin \
  --input "data/ut_austin/out/csv outputs/advertised_prices_YYYY-MM-DD.csv"
# also accepts the nested advertised_prices_YYYY-MM-DD.json or units_YYYY-MM-DD.json
python3 -m tools.scrape_archive upload-plan
python3 -m tools.scrape_archive upload --dry-run
```

The stable listing key is `{property}__{label}` (`property` is the Rebuild `property_objectID`, or the legacy property name slugified the same way).

Rules:

- A property is updated only when the file has **real rows** for it. `(extraction failed)` stubs do not wipe that property.
- Listings of every other property stay in the master with the same `last_seen` (carry-forward).
- Pass `--full` only when the file is a complete roster snapshot and a property that is simply absent should be marked no longer advertised. Do not use `--full` on a `--only` / `--patch` run or a scrape that died mid-way.
- The same file (sha256) is skipped if it is already in a snapshot.
- Never ingest a Rate My Rent export as a scrape.

Optional backfill of older dated files (not part of a normal refresh):

```bash
python3 -m tools.scrape_archive rebuild-history --campus ut-austin --fml-data /path/to/FML_Data
```

**Drive:** [FML Scrape Archive](https://drive.google.com/drive/folders/1WYFc1tCirxxC0MiwhkIxk5c6fNLmlIu8). After `upload-plan`, upload the files listed in `tools/scrape_archive/output/upload_plan.json` into that folder with the Google Drive MCP, keeping the plan's `drive_path` layout and leaving CSVs as plain CSVs. Do not commit `tools/scrape_archive/output/`. If `FML_DRIVE_*` credentials are present, `python3 -m tools.scrape_archive upload` can do the same job; without them, that command exits and leaves the plan for the MCP upload.

---

## 6. Rate My Rent (MCP only)

Canonical detail: the FML_Data updater README linked above. Current matcher is `discrepancy_updater.py` (v4). MCP read tools: `get_listing`, `search_listings`. Write tools: `update_listing`, `add_listing_record`.

**Policy:**

- Plans no longer advertised stay on Rate My Rent with availability **"No longer advertised"** — never deleted. If a plan comes back, bring it back.
- Fall 2027 (next-year leasing) counts as **Available**.
- Availability wording-only rewrites belong in the proposed changes. Normalize to Available / Limited / Sold Out / Waitlist / No longer advertised; unclear site text keeps the live value.
- Layout images that differ from the scrape are refreshed; prices and images are never blanked. `--no-refresh-images` only fills blanks.
- Placeholder scrape rows are never turned into adds or hides. A scrape with rows but no prices while live has 3+ priced plans is degraded — leave the live building as-is.
- Failed or empty buildings are left untouched.
- Approved changes are applied **one building at a time**. He reviews each building.

**Guards (do not weaken):**

- Hold a building if more than 8 plans or more than 40% would flip to "No longer advertised".
- Hold price jumps over **45%** and rents under **$300**.
- Re-read each building before writing; skip the call if live values drifted from the plan.
- No retries. Stop at the first write error. Pause 3 seconds between writes. Cap at 400 writes.
- `--apply` requires `--plan`, `--only <one building id>`, an approval file (`approved_by`, `approved_at`, matching `batch_sha256`), and the exact env value `RMR_APPLY_CONFIRM=I_REVIEWED_THE_PLAN`.
- Held batches refuse `--apply` unless the approval file has `override_held: true`.
- MCP writes are refused unless the guarded apply path sets `allow_write=True`.

**Dry-run** (from FML_Data `tools/rmr-discrepancy-updater/`). The updater wants a **flat** unit JSON (`objectID`, `property_objectID`, `unit_label`, `base_rent`, `beds`, `baths`, `sqft`, `availability`, `layout_image_url`, …). Rebuild's `advertised_prices_YYYY-MM-DD.unit_ids.json` is too thin (no beds, availability, or images). To build the file from a Rebuild locked emit, copy `data/<campus>/out/advertised_prices_YYYY-MM-DD.json` to FML_Data `austin_leases_units/scraper/output/` and run `python3 austin_leases_algolia_push.py` with **no flags**. That script is a format conversion only; **do not pass `--push`, `--backup`, or `--settings`**. A name that does not resolve against `properties.csv` / `price_name_aliases.json` aborts the conversion — fix the alias, including for a newly added building.

```bash
python3 discrepancy_updater.py --refresh-live \
  --scrape /path/to/master/algolia_units_<run>.json --scrape-date YYYY-MM-DD
```

`--run-log` is optional and expects FML_Data `run_log.txt` (`FAILED: <name>: ...`). Rebuild's `refresh_YYYY-MM-DD.md` is not that format — do not pass it here. Failed Rebuild buildings already land as `(extraction failed)` stubs, which the updater leaves as-is. Send Elijah `runs/<date>/review.md`. Stop. Do not apply.

**Apply one building** (only after he approved that building):

```bash
# copy approvals/<building>.TEMPLATE.json -> approvals/<building>.json
# and fill approved_by / approved_at
RMR_APPLY_CONFIRM=I_REVIEWED_THE_PLAN python3 discrepancy_updater.py --apply \
  --plan runs/<date>/plan.json --only <building> \
  --approval runs/<date>/approvals/<building>.json --out runs/<date>
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `WARNING N buildings skipped` at the end of `refresh_listings.py` | `saved_html_banned`: `text_plan_list` or `params.html_files`. Outputs are written and the exit code is 0 (pass `--strict` to exit `2`). Move those configs to a live HTTP/DOM adapter or a checked-in rescue. |
| Rescue / `headed_rescue` fails with `[Errno 2]` on `/Users/...` | Store `params.file` as `data/<campus>/rescues/<slug>.json` (repo-relative; `listing_adapters._abs_params` resolves it). The build now writes relative paths. Never commit absolute paths. |
| No `advertised_prices_*.csv` / `.json` | `write_legacy()` runs only for `"locked": true`. Lock verified configs (A&M: 69 locked 2026-11-25, `locked_from: texas_am_live_verified_2026-11-25`). |
| Stdout pauses 5–8+ minutes on `jonah_detail_json` (e.g. Elle West Ave) | The extractor sleeps 2s after every floorplan slug (156 plans ≈ 8 min, no per-slug log). Do not kill it. On the box, `/proc/<pid>/io` `rchar` should keep climbing. A full UT refresh is about 20–25 minutes. |
| Batch DOM run stalls ~5 minutes per blocked site | `FML_SOLVE_WAIT_S` defaults to 300. Export `FML_SOLVE_WAIT_S=25`. Never bypass the challenge. |
| DOM extractors fail or silently fall back on the box | Symlink `/workspace/pwdeps` Playwright to `npm root -g`; Chromium in `~/.cache/ms-playwright/`; `DISPLAY=:4` for headed; set `NODE_PATH` if Node cannot resolve Playwright. |
| Entrata / RentCafe `blocked_bot_wall` or Cloudflare | Off-portal CMS or portal path → headed profile → Elijah clears the check → repo-relative rescue. RentCafe that 403s to plain HTTP needs `rentcafe_ysi` (Playwright), not `rentcafe_inline` over urllib. |
| Interactive CAPTCHA mid-run | Log it, stop touching that property, ask Elijah if a rescue is needed. |
| Villas on Guadalupe, 21 Pearl, Axis West Campus, Signature 1909 are thin or empty | Use the synced `villas_wp` LeaseLeads parser (`[data-ll-floor-plan-card]` / `data-ll-floor-plan-lease-terms`). Re-run those four with `--only` / `--patch`. |
| Yugo (Rio, Corner, Nueces, Waterloo) missing plans or plan images | Pin backend `yugo` and `params.gtm_name`. Plans and images often live on per-room-type pages, not one list page. |
| Entrata "fit-in" layout image URLs look odd | They can be valid. Do not discard them just because the URL shape looks unusual. |
| Quarters / GrandMarc / Inspire suddenly empty | Stale marketing URL. Pin the student / `entrata.*` portal and re-scrape with `--only` / `--patch`. |
| Icon-style duplicate labels ("A1 1 Bed, Call for Pricing" plus a clean "A1") | `params.clean_labels` / `clean_dedupe_rows`. Keep the merged clean label. A later `no_rows` can be a temporary empty, not a standing skip. |
| Joining emit files to `listing_config.json` by `objectID` drops ~17 UT properties | Legacy emit keeps FML_Data slugs; Rebuild config uses roster slugs. Join on `property_name` or `source_id`. |
| `g5_sniff` looks like a mismatch against an identical baseline | Compare as a multiset, or sort by label, rent, and availability. Do not require the same array order. |
| `ModuleNotFoundError: rapidfuzz` | A refresh does not need it. Install `rapidfuzz` only before name-matching / discovery scripts. |
| Box cannot `git push` / `gh` not logged in | Commit from the Mac clone (`git pull --rebase`, commit, `git push origin main`) or hand files to a cloud agent. Stage transfers under `~/fml-migration/`, not `/tmp`. Include `HEAD` when making a git bundle. |
| Villas on 26th HTTP 403; Texan 26 placeholder; 1883 Montgomery `no_rows`; A&M Sierra Condos / Canyon Village HTTP 500 | Known live failures. Leave last-good archive rows; do not invent rents; do not "fix" them inside a refresh. Montgomery stays its own listing, distinct from Cameron House. |
| Live images or prices would go blank, or a >45% jump / sub-$300 rent appears | Never blank a price or an image. The updater holds those rents. Re-read the building before any write. |
| Apply would write two buildings, or retry a failed write | One building at a time. Approval file + `RMR_APPLY_CONFIRM=I_REVIEWED_THE_PLAN`. No retries. Held buildings need `override_held: true`. |

---

## 8. What to tell Elijah after a run

- Counts: properties, rows, failures, no-public-pricing, exit code (and whether outputs were written if it was 2).
- Buildings that need a human Cloudflare / CAPTCHA clear.
- Path to the review markdown and the archive / Drive update.
- Any building you want him to approve for a Rate My Rent write — named, one at a time. Nothing was pushed unless he already approved that building.
