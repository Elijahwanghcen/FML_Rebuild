"""Final outputs for one campus (shape mirrors the three UT catalogs the app already reads):
  out/buildings.json   one record per building: identity, aliases, owned coords, type, area, sources, photos
  out/amenities.json   per building: features by layer + per-amenity status/evidence/source (unknown is implicit)
  out/units.json       one row per floor plan / listed unit with rent + rent basis
  out/qc_report.md     counts, gaps, everything flagged for a human
"""
import json, sys, time
from collections import Counter
from common import campus, norm_name, name_sim
from enrich_site import slugify


def main(slug, roster_file="roster_final.json"):
    cfg = campus(slug)
    cw = set(cfg.get("city_words", []))
    out = cfg["dir"] / "out"; out.mkdir(exist_ok=True)
    roster = json.load(open(cfg["dir"] / roster_file))
    rcp = json.load(open(cfg["dir"] / "cand_rcp.json")) if (cfg["dir"] / "cand_rcp.json").exists() else []
    today = time.strftime("%Y-%m-%d")
    B, A, U = [], [], []
    for b in roster:
        s = slugify(b["canonical_name"]); rd = cfg["dir"] / "raw" / s
        ld = lambda n: json.loads((rd / n).read_text()) if (rd / n).exists() else {}
        meta, am, li = ld("meta.json"), ld("amenities.json"), ld("listings.json")
        names = [norm_name(n, cw) for n in [b["canonical_name"]] + b["aliases"]]
        m = next((x for x in rcp if any(name_sim(norm_name(x["name"], cw), n) >= 90 for n in names)), None)
        B.append({"objectID": s, "canonical_name": b["canonical_name"], "aliases": b["aliases"], "address": b.get("address"),
                  "lat": b["lat"], "lng": b["lng"], "coord_method": b["coord_method"], "coord_review": b["coord_review"],
                  "google_place_id": b.get("place_id"), "property_type": b["building_type"], "area": b.get("neighborhood"),
                  "dist_campus_m": b["dist_campus_m"], "units_est": b.get("units_est"), "floors_est": b.get("floors_est"),
                  "website_url": meta.get("seed") or b.get("website"), "management_company": b.get("manager") or (m or {}).get("manager"),
                  "site_platform": meta.get("platforms", []), "site_status": meta.get("status", "not_crawled"),
                  "photos": (m or {}).get("images", [])[:6], "student_score": b["student_score"], "tier": b["tier"],
                  "reddit_threads": b.get("reddit_threads", 0), "source_families": b["source_families"],
                  "source_urls": [u for u in [meta.get("seed")] + list(meta.get("pages", {}).values()) + [(m or {}).get("url")] if u][:8],
                  "n_amenities": am.get("n", 0), "price_status": li.get("price_status", "not_scraped"), "verifiedAt": today})
        A.append({"objectID": s, "canonical_name": b["canonical_name"], "features": am.get("features", {}),
                  "amenities": am.get("amenities", {}), "amenity_data": "ok" if am.get("n") else "unknown"})
        for i, r in enumerate(li.get("listings", [])):
            U.append({"objectID": f"{s}__{i}", "property_objectID": s, **r, "scraped_at": today})
    for n, d in (("buildings", B), ("amenities", A), ("units", U)):
        (out / f"{n}.json").write_text(json.dumps(d, indent=1))
    q = [f"# {cfg['name']} - QC report ({today})", "",
         f"- buildings: **{len(B)}**  by type: {dict(Counter(b['property_type'] for b in B))}",
         f"- by area: {dict(Counter(b['area'] for b in B))}",
         f"- coord methods: {dict(Counter(b['coord_method'] for b in B))}",
         f"- with amenities: {sum(1 for b in B if b['n_amenities'])}  (median {sorted(b['n_amenities'] for b in B)[len(B)//2]})",
         f"- price status: {dict(Counter(b['price_status'] for b in B))}  unit rows: {len(U)}",
         f"- with aliases: {sum(1 for b in B if b['aliases'])}", "",
         "## Coordinates needing a manual right-click check", ""] + \
        [f"- {b['canonical_name']} ({b['address']}) - {b['coord_method']}" for b in B if b["coord_review"]] + \
        ["", "## No amenity data (site missing / blocked / condo without a page)", ""] + \
        [f"- {b['canonical_name']} - {b['site_status']} - {b['website_url']}" for b in B if not b["n_amenities"]]
    (out / "qc_report.md").write_text("\n".join(q))
    print("\n".join(q[:9]))


if __name__ == "__main__":
    main(*sys.argv[1:3])
