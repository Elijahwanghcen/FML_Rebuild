"""Scrape locked pins the way FML_Data run.py does, then shape legacy records.

HTTP extractors are called directly so an empty result stays status "ok" and the
failure stub says "no rows", matching run.py. DOM extractors go through
listing_adapters._run (first try has no DOM_PROFILE, so it matches FML_Data).
Saved-HTML adapters fail loudly and do not read html_files.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reference" / "legacy_ut_scraper" / "extractors"))
import http_extractors as HX  # noqa: E402

from legacy_emit import property_record, scraped_stamps, unit_object_ids, write_legacy
from listing_post import apply_row_policy, failure_stub, saved_html_banned
from pinned_sources import load_fml


def backend_type(prop, backends=None):
    if prop.get("extractor_type"):
        return prop["extractor_type"]
    backends = backends or load_fml()[0]
    return backends[prop["backend"]]["type"]


def scrape_property(prop, backends=None):
    if saved_html_banned(prop):
        status = "error: saved_html_banned"
        return [failure_stub(status)], status, False
    params = prop.get("params") or {}
    btype = backend_type(prop, backends)
    try:
        if btype == "http":
            rows = HX.EXTRACTORS[prop["backend"]](prop["url"], params)
            status = "ok"
        else:
            import listing_adapters as LA
            rows, status = LA._run({"backend": prop["backend"], "url": prop["url"], "params": params})
            if status.startswith("ok") and rows:
                status = "ok"
    except Exception as e:
        rows, status = [], f"error: {e}"
    rows, ok = apply_row_policy(rows or [], params, status if status else "ok")
    return rows, status, ok


def records_for(props, scraped_at=None, scraped_ts=None, backends=None):
    if scraped_at is None or scraped_ts is None:
        scraped_at, scraped_ts, _day = scraped_stamps()
    records, flat, ids, banned = [], [], [], []
    for prop in props:
        rows, status, ok = scrape_property(prop, backends)
        if saved_html_banned(prop):
            banned.append(prop.get("property_name") or prop.get("objectID"))
        rec, csv_rows = property_record(prop, rows, scraped_at, scraped_ts)
        records.append(rec)
        flat.extend(csv_rows)
        made = unit_object_ids(rec["objectID"], rec["units"])
        for item in made:
            item["source_type"] = rec["source_type"]
            item["property_name"] = rec["property_name"]
        ids.extend(made)
        yield_status = status
        prop["_last_status"] = yield_status
        prop["_last_ok"] = ok
    return records, flat, ids, banned


def emit_locked(props, out_dir, now=None, backends=None):
    scraped_at, scraped_ts, day = scraped_stamps(now)
    records, flat, ids, banned = records_for(props, scraped_at, scraped_ts, backends)
    paths = write_legacy(records, flat, ids, out_dir, day)
    return paths, banned, records, flat
