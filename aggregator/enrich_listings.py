"""Enrichment step 3: floor plans + advertised rent.

Never a rent source: listing aggregators and campus off-campus directories (RentCollegePads and its white-labels, CoStar /
Apartments.com, Zillow, Redfin, Zumper ...; see common.is_ils). Local realtor / property-manager firms (Uptown Realty,
Westside Group ...) are the building's own leasing channel and ARE read, like a first-party site.

Order of preference per building:
  1. platform adapters (listing_adapters.py -> reference/legacy_ut_scraper extractors): the leasing platform's own feed,
     auto-detected from markers in the crawled HTML (ACC, wp-json Entrata, SightMap, RealPage, Repli360, RentCafe,
     Knock, AppFolio, Yugo, Jonah, ...). Deterministic, no LLM, and it returns every rate tier / available unit.
     The UT audit showed that skipping this step loses ~40% of rows - do not go straight to the LLM read.
  2. liberal read: the rendered floor-plans page text -> LLM -> rows. Many realtor sites have no feed at all; whatever the
     page shows is all there is. Missing sqft / layout image stays null. Nothing is invented.
Every result records which adapter ran, what was tried, and undercount flags (listing_adapters.coverage_flags);
build_json.py lists the flagged buildings in the QC report. `--refresh` redoes every building.
Rent basis: purpose-built student sites price PER BED (a 4-bed plan shows less than a 1-bed); broker/realtor and
conventional sites price PER UNIT. Words like person / bed / installment force per_bed.
"""
import json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from common import campus, norm_name, name_sim
from enrich_site import slugify
from webtext import to_text
from llm import ask_json, NotCached
import listing_adapters as LA


def basis(text, btype, hint=None):
    if hint in ("person", "bed"):
        return "per_bed"
    if hint == "unit":
        return "per_unit"
    if re.search(r"per (person|bed|bedroom)|/ ?(person|bed)\b|installment|by the bed", text or "", re.I):
        return "per_bed"
    return "per_bed" if btype in ("student_housing", "dorm", "co_op") else "per_unit"


def from_page(cfg, b, rd, meta, cache_only=False):
    parts = []
    kinds = [k for k in ("floorplans", "floorplans2", "fpdetail") if (rd / f"{k}.html").exists()]
    if not kinds:
        # a broker's unit page or a manager's property page: the listing is on the page itself
        kinds = [k for k in ("home", "alt1", "alt2") if (rd / f"{k}.html").exists()]
    for k in kinds:
        p = rd / f"{k}.html"
        if k in ("home", "alt1", "alt2") and not re.search(r"\$\s?\d", to_text(p.read_text(errors="replace"))):
            # broker unit pages fill in the price with JavaScript (longitudebcs.com): read the rendered page
            from webtext import fetch_html
            h = fetch_html(meta["pages"][k], cfg["dir"] / "cache" / "site" / rd.name, render="always")
            if h and re.search(r"\$\s?\d", to_text(h)):
                p.write_text(h)
        if p.exists():
            parts.append(f"=== {meta['pages'][k]} ===\n" + to_text(p.read_text(errors="replace"), meta["pages"][k], limit=30000))
    blob = "\n\n".join(parts)[:70000]
    if len(blob) < 300 or not re.search(r"\$\s?\d{3}|\bbed|\bbath|studio", blob, re.I):
        return [], blob
    r = ask_json(
        f"Text of the floor-plans / availability page(s) for the building '{b['canonical_name']}' in {cfg['city']}, {cfg['state']}.\n"
        "Extract every floor plan or listed unit. Return a JSON array of objects with keys:\n"
        "name, beds (number; 0 = studio), baths, sqft (number or null), price_min, price_max (monthly numbers or null if not shown), "
        "price_label (the price exactly as written, or null), per (\"person\"|\"unit\"|null - only if the page says), "
        "availability (text or null), concession (any special/discount text for it or null), image_url (floor plan image link if present or null).\n"
        "Only what the page shows. Never guess a price. If the page shows no plans return [].\n\n" + blob, model="haiku",
        cache_only=cache_only)
    if r is None:
        return None, blob             # LLM failed: caller must not cache
    return [x for x in r if isinstance(x, dict)], blob


def page_html(rd):
    out = {}
    for k in ("floorplans", "floorplans2", "fpdetail", "home", "alt1", "alt2", "alt3"):
        p = rd / f"{k}.html"
        if p.exists():
            out[k] = p.read_text(errors="replace")[:3_000_000]
    return out


def llm_rows(b, plans, blob, meta):
    return [{"name": x.get("name"), "beds": x.get("beds"), "baths": x.get("baths"), "sqft": x.get("sqft"),
             "price_min": x.get("price_min"), "price_max": x.get("price_max"), "price_label": x.get("price_label"),
             "rent_basis": basis((x.get("price_label") or "") + " " + blob[:4000], b["building_type"], x.get("per")),
             "availability": x.get("availability"), "concession": x.get("concession"),
             "layout_image_url": x.get("image_url"), "source_url": meta["pages"].get("floorplans") or meta["pages"].get("home"),
             "source_type": "first_party_site", "adapter": "llm_page_read"} for x in plans or []]


def priced(rows):
    return sum(1 for r in rows if r.get("price_min"))


def take_llm_if_better(rows, src, adapter, chosen, lr):
    """If the LLM read has more priced rows, it produced them. Do not freeze the previous adapter."""
    if (priced(lr), len(lr)) > (priced(rows), len(rows)):
        return lr, "first_party_site", "llm_page_read", None
    return rows, src, adapter, chosen


def write_listing_config(cfg, roster, res):
    """Freeze what detection found. Locked pins are kept as-is (merge, not overwrite).

    llm_page_read, text_plan_list and any adapter that only has html_files are not frozen:
    a production refresh refuses saved HTML, and an LLM win must not be stored as the
    adapter that happened to be tried before it.
    """
    import hashlib
    from pinned_sources import merge_detected
    props, sources = [], {}
    for b, r in zip(roster, res):
        sc = r.get("source_config")
        if sc and sc["backend"] == "text_plan_list" and sc.get("url"):
            # saved-page win -> freeze the same parser on the live page (refresh refuses saved HTML)
            sc = {**sc, "backend": "text_plan_live", "params": {}}
        elif sc and sc["backend"] == "rentcafe_inline" and (sc.get("params") or {}).get("html_files"):
            # RentCafe 403s plain HTTP; headless rentcafe_ysi reads ysi/fee-button pages. Oculus-theme pages
            # (data-floorplan-* cards only) need rentcafe_cards: re-run detection or set it by hand if ysi is empty.
            sc = {**sc, "backend": "rentcafe_ysi", "params": {}}
        if not sc or sc["backend"] in ("llm_page_read", "text_plan_list"):
            continue
        if (sc.get("params") or {}).get("html_files"):
            continue
        key = json.dumps([sc["backend"], sc["url"], {k: v for k, v in sc["params"].items() if k != "location_filter"}], sort_keys=True)
        sid = sources.setdefault(key, "src_" + hashlib.sha1(key.encode()).hexdigest()[:8])
        props.append({"objectID": r["slug"], "property_name": b["canonical_name"], "address": b.get("address"),
                      "building_type": b["building_type"], "source_id": sid, "backend": sc["backend"], "url": sc["url"],
                      "params": sc["params"], "detected_rows": len(r["listings"]),
                      "detected_priced": priced(r["listings"]), "detected_at": time.strftime("%Y-%m-%d")})
    p = cfg["dir"] / "listing_config.json"
    existing = json.loads(p.read_text()).get("properties", []) if p.exists() else []
    merged = merge_detected(existing, props)
    p.write_text(json.dumps({"_comment": "written by enrich_listings.py; locked pins are kept verbatim",
                             "properties": merged}, indent=1))
    n_locked = sum(1 for x in merged if x.get("locked"))
    print(f"listing_config.json: {len(merged)} buildings ({n_locked} locked) on {len(set(x['source_id'] for x in merged))} sources")


def main(slug, roster_file="roster_final.json", refresh=False, use_llm=False):
    cfg = campus(slug)
    cw = set(cfg.get("city_words", []))
    roster = json.load(open(cfg["dir"] / roster_file))

    def one(b):
        s = slugify(b["canonical_name"])
        rd = cfg["dir"] / "raw" / s
        out_p = rd / "listings.json"
        old = json.loads(out_p.read_text()) if out_p.exists() else None
        if old and old.get("extractor_version") == LA.VERSION and not refresh:
            return old
        names = [norm_name(n, cw) for n in [b["canonical_name"]] + b["aliases"]]
        mp = rd / "meta.json"
        meta = json.loads(mp.read_text()) if mp.exists() else {"pages": {}}
        htmls = page_html(rd)
        rows, src, adapter, tried, blob, failed, chosen = [], None, None, [], "", False, None
        # 1. platform adapters
        if meta.get("pages") or b.get("website"):
            try:
                rows, adapter, tried, chosen = LA.extract(b, meta, htmls, cfg, basis)
            except Exception as e:
                tried = [{"backend": "detect", "status": f"error: {str(e)[:120]}", "rows": 0, "priced": 0}]
            src = "first_party_site" if rows else None
        # 2. LLM read of the page text - LAST RESORT, off by default (--llm). An earlier read of the same saved pages
        #    is reused for free; new reads are a case-by-case job, not part of a normal run.
        if meta.get("pages") and not priced(rows):
            # an earlier LLM read: the current file if it holds one, else the v1 backup (only if that one has rows)
            v1p = rd / "listings.v1.json"
            src_old = old
            if not (old and old.get("adapter") == "llm_page_read" and old.get("listings")) and v1p.exists():
                v1 = json.loads(v1p.read_text())
                if v1.get("source") == "first_party_site" and v1.get("listings"):
                    src_old = v1
            prev_llm = src_old and src_old.get("source") == "first_party_site" and src_old.get("listings") and \
                (not src_old.get("extractor_version") or src_old.get("adapter") == "llm_page_read")
            if prev_llm and not refresh:
                # reuse the earlier LLM read of the same saved pages: each claude -p call costs ~28k tokens of overhead
                lr = [{**r, "adapter": "llm_page_read"} for r in src_old["listings"]]
            elif not use_llm:
                # an answer already in the LLM cache for these exact saved pages is free; never make a new call
                try:
                    plans, blob = from_page(cfg, b, rd, meta, cache_only=True)
                    lr = llm_rows(b, plans, blob, meta)
                except NotCached:
                    lr = []
            else:
                plans, blob = from_page(cfg, b, rd, meta)
                failed = plans is None
                lr = llm_rows(b, plans, blob, meta)
            rows, src, adapter, chosen = take_llm_if_better(rows, src, adapter, chosen, lr)
        # No third step: aggregators and campus directories (RentCollegePads, CoStar, Zillow ...) are never a rent source.
        # A building with no first-party / local-realtor rows stays `not_publicly_listed`.
        text_blob = blob or "\n".join(to_text(htmls[k], limit=200000) for k in ("floorplans", "floorplans2") if k in htmls)
        errs = [t for t in tried if str(t.get("status", "")).startswith("error")]
        if old and old.get("listings") and (priced(old["listings"]), len(old["listings"])) > (priced(rows), len(rows)) \
                and (errs or not rows):
            rows, src, adapter = old["listings"], old.get("source"), old.get("adapter")
            chosen = chosen or (old.get("source_config") and {**old["source_config"]})
            tried = tried + [{"backend": "kept_previous", "why": "this run returned fewer rows with errors",
                              "status": "stale_kept", "rows": len(rows), "priced": priced(rows)}]
        flags_extra = [] if rows else ["needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue)"]
        if rows:
            # plan images: most adapters return names + prices only; the saved pages usually show each plan's image
            try:
                added, missing = LA.attach_images(b, s, rows, htmls, meta, cfg)
                if missing:
                    flags_extra.append(f"plan_images_missing:{missing}/{len(rows)}")
                if LA.weak_images(rows):
                    flags_extra.append(f"plan_images_check_by_eye:{LA.weak_images(rows)}")
            except Exception as e:
                flags_extra.append(f"plan_images_error:{str(e)[:60]}")
        res = {"slug": s, "extractor_version": LA.VERSION, "listings": rows, "source": src, "adapter": adapter,
               "source_config": ({k: chosen[k] for k in ("backend", "url", "params")} if chosen else None),
               "adapters_tried": tried, "coverage_flags": LA.coverage_flags(rows, adapter if adapter not in ("llm_page_read",) else None, htmls, text_blob, tried) + flags_extra,
               "price_status": "listed" if priced(rows) else "not_publicly_listed"}
        rd.mkdir(parents=True, exist_ok=True)
        if not (meta.get("pages") and failed):
            if old and not old.get("extractor_version") and not (rd / "listings.v1.json").exists():
                (rd / "listings.v1.json").write_text(json.dumps(old, indent=1))
            out_p.write_text(json.dumps(res, indent=1))
        print(f"  {b['canonical_name'][:38]:38} {str(adapter):22} rows={len(rows):3} priced={priced(rows):3} {' '.join(res['coverage_flags'])[:80]}", flush=True)
        return res

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, roster))
    # sister feeds: a building whose only page is a directory listing may sit on a multi-building feed found above
    for b in roster:          # feeds found on any building's pages, including cached ones
        fp = cfg["dir"] / "raw" / slugify(b["canonical_name"]) / "floorplans.html"
        for lid in set(re.findall(r"/api/lightning/floorplans/(\d+)", fp.read_text(errors="replace"))) if fp.exists() else ():
            try:
                LA.acc_locations(int(lid))
            except Exception:
                pass
    for i, (b, r) in enumerate(zip(roster, res)):
        if r.get("adapter") == "acc_lightning":
            continue
        rows, t = LA.sister_feed(b, basis)
        if rows:
            r["source_config"] = t.pop("cand", None)
        r.pop("sister_checked", None)
        if rows and (priced(rows), len(rows)) > (priced(r["listings"]), len(r["listings"])):
            r.update(listings=rows, source="first_party_site", adapter="acc_lightning", price_status="listed" if priced(rows) else r["price_status"],
                     adapters_tried=r.get("adapters_tried", []) + [t], coverage_flags=[])
            print(f"  sister feed: {b['canonical_name']} -> {t['why']} rows={len(rows)}")
        (cfg["dir"] / "raw" / r["slug"] / "listings.json").write_text(json.dumps(r, indent=1))
    write_listing_config(cfg, roster, res)
    from collections import Counter
    print(Counter(r["price_status"] for r in res), Counter(r["source"] for r in res), "rows:", sum(len(r["listings"]) for r in res))
    print("adapters:", Counter(r.get("adapter") for r in res).most_common())
    print("flagged for undercount:", sum(1 for r in res if r.get("coverage_flags")))


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    main(*a[:2], refresh="--refresh" in sys.argv, use_llm="--llm" in sys.argv)
