#!/usr/bin/env python3
"""Weekly refresh runner for the UT Austin advertised-rent scraper.

Reads properties_config.json, dispatches each property to its backend extractor
(HTTP extractors in-process; DOM extractors via Node/Playwright subprocess),
and writes two fresh dated files:
  output/advertised_prices_YYYY-MM-DD.json          # main artifact — Algolia-ready,
                                                    # one record per property, units nested
  output/csv outputs/advertised_prices_YYYY-MM-DD.csv  # flat CSV kept for viewing/QC

Each run creates new standalone files — no data from previous runs is mixed in.
Deterministic: no LLM calls. Shared sources (same source_id) are scraped once
per run and split per property.

Usage:
  python3 run.py                 # full run → output/advertised_prices_YYYY-MM-DD.json
  python3 run.py --only src_08   # run a single source (testing — overwrites output)
  python3 run.py --only src_08 --patch output/advertised_prices_2026-08-06.json
                                 # re-scrape one source and patch it into an existing file
"""
import argparse
import csv
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "extractors"))
import http_extractors  # noqa: E402

CONFIG = os.path.join(HERE, "properties_config.json")
OUT_DIR = os.path.join(HERE, "output")
LOG = os.path.join(OUT_DIR, "run_log.txt")
NODE_SCRIPT = os.path.join(HERE, "extractors", "dom_extract.js")

FIELDS = ["property_name", "address", "unit_or_floorplan_label", "beds", "baths",
          "sqft", "base_rent", "total_price_with_mandatory_fees", "price_basis",
          "concessions_raw", "concessions_type", "concessions_value", "availability",
          "layout_image_url", "price_image_url", "concessions_image_url",
          "source_url", "source_type", "price_status", "scraped_at"]

# Fields stamped once per property in the JSON output; the rest are unit-level
PROPERTY_FIELDS = ["property_name", "address", "source_url", "source_type", "scraped_at"]
UNIT_FIELDS = [f for f in FIELDS if f not in PROPERTY_FIELDS]
NUMERIC_FIELDS = {"beds", "baths", "sqft", "base_rent",
                  "total_price_with_mandatory_fees", "concessions_value"}

POLITE_DELAY_S = 4


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def to_num(s):
    """Empty → None; numeric strings → int/float; anything else passes through."""
    if s is None or s == "":
        return None
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s
    return int(f) if f.is_integer() else f


def log(msg):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def node_path():
    try:
        return subprocess.check_output(["npm", "root", "-g"], text=True).strip()
    except Exception:
        return "/opt/homebrew/lib/node_modules"


def run_dom_extractor(backend, url, npath, params=None):
    env = dict(os.environ, NODE_PATH=npath)
    try:
        out = subprocess.check_output(
            ["node", NODE_SCRIPT, backend, url, json.dumps(params or {})],
            env=env, text=True, timeout=180)
        return json.loads(out.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"status": "error: extractor timeout", "rows": []}
    except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError) as e:
        return {"status": f"error: {e}", "rows": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run only this source_id")
    ap.add_argument("--patch", metavar="JSON_FILE",
                    help="patch results into an existing JSON file instead of writing "
                         "a fresh one (use with --only to re-scrape a single source)")
    args = ap.parse_args()

    if args.patch and not args.only:
        ap.error("--patch requires --only (specify which source to re-scrape)")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CONFIG) as f:
        cfg = json.load(f)
    backends = cfg["backends"]
    props = cfg["properties"]
    if args.only:
        props = [p for p in props if p["source_id"] == args.only]

    today_date = datetime.date.today()
    today = today_date.isoformat()
    scraped_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    # Unix timestamp at midnight UTC of the run date (day accuracy is all we need)
    scraped_ts = int(datetime.datetime(today_date.year, today_date.month, today_date.day,
                                       tzinfo=datetime.timezone.utc).timestamp())

    # Each run writes fresh dated files: JSON (main, Algolia-ready) + CSV (viewing/QC)
    csv_dir = os.path.join(OUT_DIR, "csv outputs")
    os.makedirs(csv_dir, exist_ok=True)
    out_csv = os.path.join(csv_dir, f"advertised_prices_{today}.csv")
    out_json = os.path.join(OUT_DIR, f"advertised_prices_{today}.json")
    log(f"Starting run for {today} → {out_json} (+ {out_csv})")

    npath = node_path()
    dom_cache = {}  # source_id -> extractor result (shared-source dedupe)
    stats = {"props": 0, "rows": 0, "failures": [], "not_listed": []}
    records = []  # one JSON record per property, units nested

    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        last_host = None
        for p in props:
            name = p["property_name"]
            backend = p["backend"]
            btype = backends[backend]["type"]
            url = p["url"]
            log(f"scraping {name} [{backend}/{btype}] {url}")

            host = url.split("/")[2]
            if host == last_host:
                time.sleep(POLITE_DELAY_S)
            last_host = host

            rows, status = [], "ok"
            try:
                if btype == "http":
                    # http extractors cache fetches internally, so shared sources
                    # (e.g. the six Block rows on src_01) hit the network once
                    rows = http_extractors.EXTRACTORS[backend](url, p.get("params", {}))
                else:
                    sid = p["source_id"]
                    if sid not in dom_cache:
                        dom_cache[sid] = run_dom_extractor(backend, url, npath, p.get("params"))
                    result = dom_cache[sid]
                    status = result["status"]
                    rows = result["rows"]
            except Exception as e:  # keep the run going; log the failure
                status = f"error: {e}"

            if status != "ok" or not rows:
                stats["failures"].append((name, status if status != "ok" else "no rows"))
                log(f"  FAILED: {name}: {status if status != 'ok' else 'no rows extracted'}")
                rows = [dict(unit_or_floorplan_label="(extraction failed)",
                             beds="", baths="", sqft="", base_rent="",
                             total_price_with_mandatory_fees="", price_basis="",
                             concessions_raw="", concessions_type="", concessions_value="",
                             availability=f"extractor status: {status}",
                             price_status="not_publicly_listed")]

            record = {
                "objectID": slugify(name),
                "property_name": name,
                "address": p.get("address", ""),
                "source_url": url,
                "source_type": p.get("source_type", "first_party"),
                "scraped_at": scraped_at,
                "scraped_ts": scraped_ts,
                "units": [],
            }
            for r in rows:
                r_out = dict(r)
                r_out["property_name"] = name
                r_out["address"] = p.get("address", "")
                r_out["source_url"] = url
                r_out["source_type"] = p.get("source_type", "first_party")
                r_out["scraped_at"] = scraped_at
                if r_out["price_status"] == "not_publicly_listed":
                    stats["not_listed"].append(name)
                writer.writerow({k: r_out.get(k, "") for k in FIELDS})
                stats["rows"] += 1
                record["units"].append({
                    k: (to_num(r_out.get(k)) if k in NUMERIC_FIELDS
                        else (r_out.get(k) or None))
                    for k in UNIT_FIELDS})
            records.append(record)
            f.flush()
            stats["props"] += 1
            log(f"  wrote {len(rows)} rows for {name}")

    if args.patch:
        # Patch mode: load existing JSON, swap matching records by objectID
        patch_path = args.patch if os.path.isabs(args.patch) else os.path.join(HERE, args.patch)
        with open(patch_path, "r") as f:
            existing = json.load(f)
        # Build lookup of new records by objectID
        new_by_id = {r["objectID"]: r for r in records}
        patched_ids = set()
        for i, rec in enumerate(existing):
            if rec["objectID"] in new_by_id:
                existing[i] = new_by_id[rec["objectID"]]
                patched_ids.add(rec["objectID"])
        # Append any new records that weren't already in the file
        for oid, rec in new_by_id.items():
            if oid not in patched_ids:
                existing.append(rec)
        with open(patch_path, "w") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        patched_names = [r["property_name"] for r in new_by_id.values()]
        log(f"PATCHED {len(new_by_id)} record(s) into {patch_path}: {patched_names}")
    else:
        with open(out_json, "w") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

    target = patch_path if args.patch else out_json
    log(f"DONE: {stats['props']} properties, {stats['rows']} rows, "
        f"{len(stats['failures'])} failures → {target} (+ {out_csv})")
    if stats["failures"]:
        for n, s in stats["failures"]:
            log(f"  failure: {n}: {s}")


if __name__ == "__main__":
    main()
