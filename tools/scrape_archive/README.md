# Scrape archive

Every scrape is saved, and every change between runs is catalogued. A weekly run that only refreshes some listings does not erase the rest: the master keeps the last-seen values, plus `first_seen`, `last_seen`, and `last_changed`.

The package does not talk to Algolia or Rate My Rent. Google credentials are read from the environment at upload time and are never written here.

## Run

From the repo root:

```bash
python3 -m tools.scrape_archive ingest --campus ut-austin --input scrape.csv
python3 -m tools.scrape_archive rebuild-history --campus ut-austin --fml-data /path/to/FML_Data
python3 -m tools.scrape_archive upload-plan
python3 -m tools.scrape_archive upload --dry-run
```

`--campus` accepts `ut-austin`, `texas-am` (and aliases such as `ut_austin`, `tamu`), or any new slug. A new campus gets its own folder; it does not need a code change.

`--out` sets the archive directory. The default is `tools/scrape_archive/output/` (gitignored).

`ingest` reads one file:

- FML_Data legacy 20-column CSV
- the same rows as flat JSON
- legacy nested JSON (`advertised_prices_YYYY-MM-DD.json`, units under each property)
- Rebuild `units.json` / `units_YYYY-MM-DD.json`

A property is updated only when the file has real rows for it. Rows labeled `(extraction failed)` do not wipe that property. Listings of every other property stay in the master with the same `last_seen`. Pass `--full` when the file is a complete roster snapshot and a property that is simply absent should be marked no longer advertised.

The same file (sha256) is skipped if it is already in a snapshot, so a rerun does not double-count. `rebuild-history --reset` deletes that campus's archive and replays from scratch.

## What a run compares

The stable key is `{property}__{label}` (`property` is the Rebuild `property_objectID`, or the legacy property name folded the same way `run.py` slugifies it).

Inside a property that this file actually scraped:

- same label → field diff (price, availability, price status, sqft, images, beds/baths, lease term, concessions, source)
- label changed, and beds + baths + sqft all match and that signature is unique on both sides → rename, not an add plus a removal
- label gone → no longer advertised (the row stays in the master so it can come back)
- label back after that → reappeared
- exact duplicate rows in one file collapse to one listing

`1000` and `1000.0` are the same price. Lease term is read from a `lease_term` column or from the `term:` clause in `availability`.

## Archive layout

```
upload_plan.json
{campus}/snapshots/{date}_{runid}/     raw file + manifest.json (sha256, row counts, scraper commit)
{campus}/changes/{date}_changes.csv
{campus}/changes/{date}_changes.json
{campus}/changes/{date}_changes.md
{campus}/master/master_latest.csv
{campus}/master/master_{date}.csv
{campus}/changes_log.csv                 append-only, one row per change across every run
{campus}/history_summary.json            written by rebuild-history
```

`manifest.json` records the scraper commit from `--scraper-commit`, or from `git rev-parse HEAD` when the input file lives in a checkout.

## Backfill

`rebuild-history` walks an FML_Data checkout (or any folder of dated files), oldest date first. For each date it prefers a CSV that has at least one real listing. If the CSV is missing, or is only a failure stub, it uses the JSON snapshot for that date. UT Austin's `advertised_prices_2026-08-06.csv` is a one-row failure stub; the 2026-08-06 JSON is the real scrape. Three later dates exist only as JSON.

Point `--fml-data` at the checkout root. UT files are taken from `austin_leases_units/`. A future A&M tree is selected by path tokens such as `texas_am` or `college_station`.

## Upload

`upload_plan.json` at the archive root maps each local file to a path under the Drive folder **FML Scrape Archive**:

```json
{"local_path": "/abs/ut-austin/master/master_latest.csv", "drive_path": "ut-austin/master/master_latest.csv", "sha256": "...", "bytes": 123}
```

An external agent with Drive access can create those folders and upload the files. Nothing in the plan is a secret.

`upload` does the same thing when credentials are present. It creates the folder tree and updates a file that is already there under the same name.

| Variable | Use |
| --- | --- |
| `FML_DRIVE_ACCESS_TOKEN` | bearer token, used as-is |
| `FML_DRIVE_REFRESH_TOKEN`, `FML_DRIVE_CLIENT_ID`, `FML_DRIVE_CLIENT_SECRET` | OAuth refresh |
| `FML_DRIVE_SERVICE_ACCOUNT_FILE` or `GOOGLE_APPLICATION_CREDENTIALS` | service-account JSON key |
| `FML_DRIVE_ROOT_FOLDER` | parent folder id; the named archive folder is created inside it |

Share the parent folder with the service account's `client_email`. A service account has no My Drive quota of its own. With no credentials, `upload` exits and leaves the plan in place.

## Tests

```bash
python3 -m unittest tools.scrape_archive.tests.test_diff tools.scrape_archive.tests.test_archive -v
```

The diff tests cover a price change, a rename, a reappearance, and a partial scrape that carries an untouched property forward.
