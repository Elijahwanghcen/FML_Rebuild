"""Weekly listings refresh - deterministic, config-driven, no LLM, no crawling, no detection.

Modeled on FML_scraper/austin_leases_units/scraper/run.py (the most reliable part of the UT system):
  * reads only data/<campus>/listing_config.json (frozen by enrich_listings.py during the build phase)
  * a source shared by several buildings (source_id) is fetched once per run
  * polite delay between requests to the same host
  * a failed building keeps an explicit "(extraction failed)" stub with the status - never silently missing
  * writes fresh dated files: out/units_YYYY-MM-DD.json and out/refresh_YYYY-MM-DD.md (failures, blocked sites,
    buildings whose row count or prices moved a lot since the previous run - flagged for a human, not "fixed")
  * --only <objectID|source_id> re-scrapes one; --patch merges it into the latest dated units file

Do not write new extractors or debug sites from a refresh run (FML_scraper CLAUDE_WEEKLY.md). A building that keeps
failing goes back to the build phase (enrich_listings.py) or gets a hand-saved data/<campus>/rescues/<objectID>.json.

  python3 refresh_listings.py <campus> [--only X] [--patch]
"""
import argparse, glob, json, os, time
from collections import Counter, defaultdict
from urllib.parse import urlparse
from common import campus
import listing_adapters as LA
from enrich_listings import basis

POLITE_DELAY_S = 4
SWING = 0.15          # flag a building whose median rent moved more than 15%


def median(xs):
    xs = sorted(x for x in xs if x)
    return xs[len(xs) // 2] if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campus")
    ap.add_argument("--only")
    ap.add_argument("--patch", action="store_true")
    a = ap.parse_args()
    cfg = campus(a.campus)
    conf = json.load(open(cfg["dir"] / "listing_config.json"))["properties"]
    if a.only:
        conf = [p for p in conf if a.only in (p["objectID"], p["source_id"])]
    today = time.strftime("%Y-%m-%d")
    out_dir = cfg["dir"] / "out"
    prev_files = sorted(glob.glob(str(out_dir / "units_20*.json")))
    prev = json.load(open(prev_files[-1])) if prev_files else []
    prev_by = defaultdict(list)
    for u in prev:
        prev_by[u["property_objectID"]].append(u)

    raw_cache, last_host, units, log = {}, None, [], []
    for p in conf:
        cand = {"backend": p["backend"], "url": p["url"], "params": p["params"]}
        host = urlparse(p["url"]).netloc
        key = (p["source_id"], json.dumps(p["params"], sort_keys=True))
        if key not in raw_cache:
            if host == last_host:
                time.sleep(POLITE_DELAY_S)
            last_host = host
            raw_cache[key] = LA._run(cand)
        raw, status = raw_cache[key]
        raw = [r for r in raw if (r.get("unit_or_floorplan_label") or "").strip() and not r["unit_or_floorplan_label"].startswith("(")]
        rows = [LA.convert(r, cand, basis, p["building_type"]) for r in raw]
        if rows and any(not r.get("layout_image_url") for r in rows):
            # plan images from the build phase's saved pages (no new crawling, no plan-page follow-ups here)
            rd = cfg["dir"] / "raw" / p["objectID"]
            htmls = {f.stem: f.read_text(errors="replace") for f in rd.glob("*.html")} if rd.exists() else {}
            mp = rd / "meta.json"
            try:
                LA.attach_images({"website": p["url"]}, p["objectID"], rows, htmls,
                                 json.loads(mp.read_text()) if mp.exists() else {}, cfg, fetch=False)
            except Exception:
                pass
        if not rows:
            rows = [{"name": "(extraction failed)", "availability": f"extractor status: {status}", "price_min": None,
                     "price_status": "not_publicly_listed", "adapter": p["backend"], "source_url": p["url"]}]
        for i, r in enumerate(rows):
            units.append({"objectID": f"{p['objectID']}__{i}", "property_objectID": p["objectID"], **r, "scraped_at": today})
        ok = rows[0]["name"] != "(extraction failed)"
        pm_new = median([r.get("price_min") for r in rows])
        pm_old = median([u.get("price_min") for u in prev_by.get(p["objectID"], [])])
        swing = pm_new and pm_old and abs(pm_new - pm_old) / pm_old > SWING
        log.append({"objectID": p["objectID"], "status": status, "ok": ok, "rows": len(rows) if ok else 0,
                    "rows_before": len(prev_by.get(p["objectID"], [])), "median_now": pm_new, "median_before": pm_old,
                    "swing": bool(swing)})
        print(f"  {p['property_name'][:36]:36} {p['backend']:20} {status[:28]:28} rows={len(rows) if ok else 0}", flush=True)

    target = out_dir / f"units_{today}.json"
    if a.patch and prev_files:
        ids = {p["objectID"] for p in conf}
        units = [u for u in prev if u["property_objectID"] not in ids] + units
        target = prev_files[-1]
    json.dump(units, open(target, "w"), indent=1)
    fails = [x for x in log if not x["ok"]]
    md = [f"# Listings refresh {today} ({cfg['name']})", "",
          f"- buildings: {len(log)}  ok: {len(log) - len(fails)}  failed: {len(fails)}  rows: {sum(x['rows'] for x in log)}",
          f"- statuses: {dict(Counter(x['status'].split(' (')[0] for x in log))}", "",
          "## Failed (back to the build phase, or save a rescue file)", ""] + \
         [f"- {x['objectID']}: {x['status']}" for x in fails] + \
         ["", "## Big moves since last run (check by hand, do not 'fix' in a refresh)", ""] + \
         [f"- {x['objectID']}: median ${x['median_before']} -> ${x['median_now']}" for x in log if x["swing"]] + \
         [f"- {x['objectID']}: rows {x['rows_before']} -> {x['rows']}" for x in log
          if x["ok"] and x["rows_before"] and abs(x["rows"] - x["rows_before"]) > max(3, 0.5 * x["rows_before"])]
    (out_dir / f"refresh_{today}.md").write_text("\n".join(md))
    print("\n".join(md[:4]), f"\n-> {target}")


if __name__ == "__main__":
    main()
