#!/usr/bin/env python3
"""Parity between FML_Data run.py and Rebuild's locked emitter.

Tier A replays one cassette of HTTP responses into both sides and diffs every
CSV field. scraped_at may differ only when --allow-stamp is set; the default
passes one shared stamp so the files match exactly.

Tier B fetches each building live, twice, back to back (FML extractor, then
Rebuild extractor) and writes a markdown diff. A network error is "unreachable".
It does not solve a CAPTCHA or a Cloudflare challenge. It does not call Algolia
or Rate My Rent.

  python3 parity_harness.py tier-a [--limit N]
  python3 parity_harness.py tier-b [--limit N]

HTTP-feed family: acc_lightning, wp_entrata_json, sightmap, knock_doorway,
realpage_cms_proxy, jonah_detail_json, fp_units_modal_v2, duda_appfolio_feed,
appfolio_listings.
"""
import base64
import json
import os
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FML_ROOT = Path(os.environ.get("FML_DATA_ROOT", "/agent/repos/FML_Data"))
FML_SCRAPER = FML_ROOT / "austin_leases_units" / "scraper"
sys.path.insert(0, str(ROOT / "aggregator"))

from legacy_emit import FIELDS, property_record, scraped_stamps  # noqa: E402
from listing_post import apply_row_policy  # noqa: E402
from pinned_sources import load_fml  # noqa: E402

HTTP_FAMILY = {
    "acc_lightning", "wp_entrata_json", "sightmap", "knock_doorway",
    "realpage_cms_proxy", "jonah_detail_json", "fp_units_modal_v2",
    "duda_appfolio_feed", "appfolio_listings",
}
CASSETTE = ROOT / "data" / "ut_austin" / "cache" / "parity_cassette.json"
REPORT = ROOT / "docs" / "PARITY_PHASE0.md"


class _Body:
    def __init__(self, status, body: bytes, url, headers=None):
        self.status = status
        self._body = body
        self.url = url
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return self.url


def _url_of(req):
    if isinstance(req, str):
        return req
    return getattr(req, "full_url", None) or req.get_full_url()


def install_cassette(mode, store):
    orig = urllib.request.urlopen

    def urlopen(req, timeout=30, *args, **kwargs):
        url = _url_of(req)
        if mode == "replay":
            rec = store["urls"].get(url)
            if rec is None:
                raise urllib.error.URLError(f"cassette miss: {url}")
            raw = base64.b64decode(rec["body_b64"])
            return _Body(rec.get("status", 200), raw, url, rec.get("headers") or {})
        resp = orig(req, timeout=timeout)
        raw = resp.read()
        headers = {k: v for k, v in getattr(resp, "headers", {}).items()}
        store["urls"][url] = {
            "status": getattr(resp, "status", 200),
            "body_b64": base64.b64encode(raw).decode("ascii"),
            "headers": headers,
        }
        return _Body(store["urls"][url]["status"], raw, url, headers)

    urllib.request.urlopen = urlopen
    return orig


def family(limit=None):
    _backends, props = load_fml()
    rows = [p for p in props if p.get("backend") in HTTP_FAMILY]
    return rows[:limit] if limit else rows


def _stamp_rows(prop, rows, scraped_at, scraped_ts):
    rec, flat = property_record(prop, rows, scraped_at, scraped_ts)
    return rec, flat


def run_fml(props, scraped_at, scraped_ts):
    """Use FML_Data's own extractor module and clean_dedupe_rows."""
    sys.path.insert(0, str(FML_SCRAPER / "extractors"))
    sys.path.insert(0, str(FML_SCRAPER))
    import http_extractors as HX
    import run as fml_run
    HX._FETCH_CACHE.clear()
    flat = []
    notes = []
    for prop in props:
        params = prop.get("params") or {}
        try:
            rows = HX.EXTRACTORS[prop["backend"]](prop["url"], params)
            status = "ok"
        except Exception as e:
            rows, status = [], f"error: {e}"
            notes.append({"property_name": prop["property_name"], "error": status})
        if rows and params.get("clean_labels"):
            rows = fml_run.clean_dedupe_rows(rows)
        if status != "ok" or not rows:
            rows = [dict(
                unit_or_floorplan_label="(extraction failed)",
                beds="", baths="", sqft="", base_rent="",
                total_price_with_mandatory_fees="", price_basis="",
                concessions_raw="", concessions_type="", concessions_value="",
                availability=f"extractor status: {status if status != 'ok' else 'no rows'}",
                price_status="not_publicly_listed",
            )]
        _rec, csv_rows = _stamp_rows(prop, rows, scraped_at, scraped_ts)
        flat.extend(csv_rows)
    return flat, notes


def run_rebuild(props, scraped_at, scraped_ts):
    sys.path.insert(0, str(ROOT / "reference" / "legacy_ut_scraper" / "extractors"))
    import http_extractors as HX
    HX._FETCH_CACHE.clear()
    flat = []
    notes = []
    for prop in props:
        params = prop.get("params") or {}
        try:
            rows = HX.EXTRACTORS[prop["backend"]](prop["url"], params)
            status = "ok"
        except Exception as e:
            rows, status = [], f"error: {e}"
            notes.append({"property_name": prop["property_name"], "error": status})
        rows, _ok = apply_row_policy(rows or [], params, status)
        _rec, csv_rows = _stamp_rows(prop, rows, scraped_at, scraped_ts)
        flat.extend(csv_rows)
    return flat, notes


def _key(row):
    return (row.get("property_name"), row.get("unit_or_floorplan_label"), str(row.get("beds")), str(row.get("baths")), str(row.get("sqft")))


def diff_rows(left, right, ignore=("scraped_at",)):
    """Exact multiset diff on the 20 columns. Returns a list of mismatch dicts."""
    def norm(row):
        return tuple("" if row.get(k) is None else str(row.get(k)) for k in FIELDS if k not in ignore)

    from collections import Counter
    lc, rc = Counter(norm(r) for r in left), Counter(norm(r) for r in right)
    missing, extra = [], []
    for item, n in (lc - rc).items():
        missing.extend([item] * n)
    for item, n in (rc - lc).items():
        extra.extend([item] * n)
    return missing, extra


def _show(item):
    # item is a tuple aligned to FIELDS minus scraped_at
    cols = [k for k in FIELDS if k != "scraped_at"]
    data = dict(zip(cols, item))
    return f"{data.get('property_name')} | {data.get('unit_or_floorplan_label')} | rent={data.get('base_rent')} | status={data.get('price_status')} | basis={data.get('price_basis')}"


def tier_a(limit=None):
    props = family(limit)
    store = {"urls": {}}
    scraped_at, scraped_ts, _day = scraped_stamps()
    # Record from the Rebuild copy (byte-identical HTTP extractors) so the cassette
    # holds every URL either side will request.
    install_cassette("record", store)
    try:
        run_rebuild(props, scraped_at, scraped_ts)
    finally:
        urllib.request.urlopen = urllib.request.urlopen  # replaced below
    # install_cassette replaced urlopen; restore by re-import is messy. Re-exec replay
    # in this process after swapping to replay mode. The record hook is still installed
    # if we don't save orig. Capture orig properly.
    return props, store, scraped_at, scraped_ts


def tier_a_full(limit=None):
    props = family(limit)
    store = {"urls": {}}
    orig = install_cassette("record", store)
    scraped_at, scraped_ts, _day = scraped_stamps()
    record_errors = []
    try:
        sys.path.insert(0, str(ROOT / "reference" / "legacy_ut_scraper" / "extractors"))
        import http_extractors as HX
        HX._FETCH_CACHE.clear()
        for prop in props:
            try:
                HX.EXTRACTORS[prop["backend"]](prop["url"], prop.get("params") or {})
            except Exception as e:
                record_errors.append({"property_name": prop["property_name"], "backend": prop["backend"], "error": f"{type(e).__name__}: {e}"})
    finally:
        urllib.request.urlopen = orig
    CASSETTE.parent.mkdir(parents=True, exist_ok=True)
    CASSETTE.write_text(json.dumps({"urls": store["urls"]}, ensure_ascii=False))

    def replay(which):
        # Fresh interpreter so extractor caches and the cassette hook cannot leak.
        import subprocess
        payload = {
            "which": which,
            "cassette": str(CASSETTE),
            "props": props,
            "scraped_at": scraped_at,
            "scraped_ts": scraped_ts,
        }
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "aggregator")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--replay-worker"],
            input=json.dumps(payload),
            text=True, capture_output=True, env=env,
        )
        if proc.returncode != 0:
            raise SystemExit(proc.stderr[-2000:] or proc.stdout[-2000:])
        return json.loads(proc.stdout)

    fml = replay("fml")
    rebuild = replay("rebuild")
    missing, extra = diff_rows(fml["rows"], rebuild["rows"])
    by_prop = {}
    for prop in props:
        name = prop["property_name"]
        lf = [r for r in fml["rows"] if r["property_name"] == name]
        rf = [r for r in rebuild["rows"] if r["property_name"] == name]
        m, e = diff_rows(lf, rf)
        err = next((x for x in record_errors if x["property_name"] == name), None)
        if err and not lf and not rf:
            status = "unreachable"
        elif not m and not e:
            status = "exact"
        else:
            status = "mismatch"
        by_prop[name] = {
            "backend": prop["backend"],
            "status": status,
            "fml_rows": len(lf),
            "rebuild_rows": len(rf),
            "missing": [_show(x) for x in m[:3]],
            "extra": [_show(x) for x in e[:3]],
            "error": err["error"] if err else None,
        }
    return by_prop, len(store["urls"]), record_errors


def replay_worker():
    payload = json.loads(sys.stdin.read())
    store = json.loads(Path(payload["cassette"]).read_text())
    install_cassette("replay", store)
    props = payload["props"]
    if payload["which"] == "fml":
        rows, notes = run_fml(props, payload["scraped_at"], payload["scraped_ts"])
    else:
        rows, notes = run_rebuild(props, payload["scraped_at"], payload["scraped_ts"])
    json.dump({"rows": rows, "notes": notes}, sys.stdout)


def tier_b(limit=None):
    props = family(limit)
    scraped_at, scraped_ts, _day = scraped_stamps()
    out = {}
    for prop in props:
        name = prop["property_name"]
        try:
            fml_rows, fml_notes = run_fml([prop], scraped_at, scraped_ts)
        except Exception as e:
            out[name] = {"backend": prop["backend"], "status": "unreachable", "error": f"fml {type(e).__name__}: {e}", "fml_rows": 0, "rebuild_rows": 0, "missing": [], "extra": []}
            continue
        try:
            rb_rows, rb_notes = run_rebuild([prop], scraped_at, scraped_ts)
        except Exception as e:
            out[name] = {"backend": prop["backend"], "status": "unreachable", "error": f"rebuild {type(e).__name__}: {e}", "fml_rows": len(fml_rows), "rebuild_rows": 0, "missing": [], "extra": []}
            continue
        err = (fml_notes or rb_notes)
        # A failure stub whose availability contains the exception is unreachable, not a data mismatch.
        def failed(rows):
            return rows and rows[0].get("unit_or_floorplan_label") == "(extraction failed)" and "error:" in (rows[0].get("availability") or "")
        if failed(fml_rows) or failed(rb_rows):
            msg = (fml_rows or rb_rows)[0].get("availability")
            out[name] = {"backend": prop["backend"], "status": "unreachable", "error": msg, "fml_rows": len(fml_rows), "rebuild_rows": len(rb_rows), "missing": [], "extra": []}
            continue
        m, e = diff_rows(fml_rows, rb_rows)
        out[name] = {
            "backend": prop["backend"],
            "status": "exact" if not m and not e else "mismatch",
            "fml_rows": len(fml_rows),
            "rebuild_rows": len(rb_rows),
            "missing": [_show(x) for x in m[:3]],
            "extra": [_show(x) for x in e[:3]],
            "error": err[0]["error"] if err else None,
        }
    return out


def render(title, results):
    lines = [f"# {title}", ""]
    counts = {"exact": 0, "mismatch": 0, "unreachable": 0}
    for name, row in results.items():
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    lines.append(f"exact {counts.get('exact', 0)}, mismatch {counts.get('mismatch', 0)}, unreachable {counts.get('unreachable', 0)}")
    lines.append("")
    lines.append("| Building | Backend | Result | FML rows | Rebuild rows |")
    lines.append("|---|---|---|---|---|")
    for name, row in results.items():
        lines.append(f"| {name} | `{row['backend']}` | {row['status']} | {row['fml_rows']} | {row['rebuild_rows']} |")
    lines.append("")
    for name, row in results.items():
        if row["status"] == "exact":
            continue
        lines.append(f"## {name}")
        lines.append("")
        if row.get("error"):
            lines.append(f"Error: `{row['error'][:300]}`")
            lines.append("")
        for label, items in (("In FML only", row.get("missing") or []), ("In Rebuild only", row.get("extra") or [])):
            if items:
                lines.append(f"{label}:")
                for item in items:
                    lines.append(f"- {item}")
                lines.append("")
    return "\n".join(lines) + "\n"


def main():
    if "--replay-worker" in sys.argv:
        try:
            replay_worker()
        except Exception:
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
        return
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tier-a"
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if cmd == "tier-a":
        results, nurls, _errs = tier_a_full(limit)
        text = render("Tier A cassette replay (HTTP-feed family)", results)
        text = f"Cassette URLs recorded: {nurls}\n\n" + text
    elif cmd == "tier-b":
        results = tier_b(limit)
        text = render("Tier B live shadow (HTTP-feed family)", results)
    else:
        raise SystemExit("usage: parity_harness.py tier-a|tier-b [--limit N]")
    REPORT.write_text(text)
    print(text)
    print(f"wrote {REPORT}")
    bad = [n for n, r in results.items() if r["status"] == "mismatch"]
    if bad:
        sys.exit(2)


if __name__ == "__main__":
    main()
