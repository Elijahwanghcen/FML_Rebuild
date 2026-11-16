"""Enrichment step 3: floor plans + advertised rent.

Order of preference per building:
  1. platform JSON adapters (reference/legacy_ut_scraper: Entrata, SightMap, RentCafe, ACC, AppFolio, Knock ...) - wire the
     fingerprint from enrich_site.py to an adapter when a campus has many buildings on that platform
  2. the off-campus directory's structured floor plans (cand_rcp.json)
  3. liberal read: the rendered floor-plans page text -> LLM -> rows. Many realtor sites have no feed at all; whatever the
     page shows is all there is. Missing sqft / layout image stays null. Nothing is invented.
Rent basis: purpose-built student sites price PER BED (a 4-bed plan shows less than a 1-bed); broker/realtor and
conventional sites price PER UNIT. Words like person / bed / installment force per_bed.
"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from common import campus, norm_name, name_sim
from enrich_site import slugify
from webtext import to_text
from llm import ask_json


def basis(text, btype, hint=None):
    if hint in ("person", "bed"):
        return "per_bed"
    if hint == "unit":
        return "per_unit"
    if re.search(r"per (person|bed|bedroom)|/ ?(person|bed)\b|installment|by the bed", text or "", re.I):
        return "per_bed"
    return "per_bed" if btype in ("student_housing", "dorm", "co_op") else "per_unit"


def from_page(cfg, b, rd, meta):
    parts = []
    for k in ("floorplans", "floorplans2", "fpdetail"):
        p = rd / f"{k}.html"
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
        "Only what the page shows. Never guess a price. If the page shows no plans return [].\n\n" + blob, model="haiku")
    if r is None:
        return None, blob             # LLM failed: caller must not cache
    return [x for x in r if isinstance(x, dict)], blob


def main(slug, roster_file="roster_final.json"):
    cfg = campus(slug)
    cw = set(cfg.get("city_words", []))
    roster = json.load(open(cfg["dir"] / roster_file))
    rcp = json.load(open(cfg["dir"] / "cand_rcp.json")) if (cfg["dir"] / "cand_rcp.json").exists() else []

    def one(b):
        s = slugify(b["canonical_name"])
        rd = cfg["dir"] / "raw" / s
        out_p = rd / "listings.json"
        if out_p.exists():
            return json.loads(out_p.read_text())
        names = [norm_name(n, cw) for n in [b["canonical_name"]] + b["aliases"]]
        rows, src = [], None
        mp = rd / "meta.json"
        meta = json.loads(mp.read_text()) if mp.exists() else {"pages": {}}
        blob, failed = "", False
        if meta.get("pages"):
            plans, blob = from_page(cfg, b, rd, meta)
            failed = plans is None
            for x in plans or []:
                rows.append({"name": x.get("name"), "beds": x.get("beds"), "baths": x.get("baths"), "sqft": x.get("sqft"),
                             "price_min": x.get("price_min"), "price_max": x.get("price_max"), "price_label": x.get("price_label"),
                             "rent_basis": basis((x.get("price_label") or "") + " " + blob[:4000], b["building_type"], x.get("per")),
                             "availability": x.get("availability"), "concession": x.get("concession"),
                             "layout_image_url": x.get("image_url"), "source_url": meta["pages"].get("floorplans"),
                             "source_type": "first_party_site"})
            src = "first_party_site" if rows else None
        if not any(r.get("price_min") for r in rows):
            m = next((x for x in rcp if any(name_sim(norm_name(x["name"], cw), n) >= 90 for n in names)), None)
            if m and m.get("floorplans"):
                rows = [{"name": f.get("title") or f"{f['beds']} bed / {f['baths']} bath", "beds": f["beds"], "baths": f["baths"],
                         "sqft": f.get("sqft"), "price_min": f.get("min_rent"), "price_max": f.get("max_rent"), "price_label": None,
                         "rent_basis": basis("", b["building_type"], m.get("rent_style")), "availability": f.get("available"),
                         "concession": None, "layout_image_url": None, "source_url": m["url"], "source_type": "campus_directory"}
                        for f in m["floorplans"]] + [r for r in rows if not r.get("price_min") and False]
                src = "campus_directory"
        res = {"slug": s, "listings": rows, "source": src,
               "price_status": "listed" if any(r.get("price_min") for r in rows) else "not_publicly_listed"}
        rd.mkdir(parents=True, exist_ok=True)
        if not (meta.get("pages") and failed):
            out_p.write_text(json.dumps(res, indent=1))
        return res

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, roster))
    from collections import Counter
    print(Counter(r["price_status"] for r in res), Counter(r["source"] for r in res), "rows:", sum(len(r["listings"]) for r in res))


if __name__ == "__main__":
    main(*sys.argv[1:3])
