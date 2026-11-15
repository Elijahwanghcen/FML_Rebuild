"""Turn the merged candidate set into the final roster: owned coordinates, size estimate, student-relevance rank.

Coordinates (never trust a site's or geocoder's street-centroid pin):
  1. NAD address point for the street address (rooftop-accurate, public domain)        -> pick the footprint it sits in
  2. else the Google pin is used ONLY to pick the Overture footprint; the stored value is the footprint centroid
  3. if (1) and the Google pin disagree by > 60 m, or no footprint is found            -> coord_review = True
     (resolve by right-clicking the building in Google Maps and copying >= 5 decimals into coord_overrides.json)
Rank = evidence that students actually rent there, not just that the building exists.
"""
import csv, json, sys
from common import campus, haversine_m, norm_name, name_sim
import geo


def main(slug, min_n=150):
    cfg = campus(slug)
    cw = set(cfg.get("city_words", []))
    roster = json.load(open(cfg["dir"] / "roster_merged.json"))
    ov_p = cfg["dir"] / "coord_overrides.json"
    overrides = json.load(open(ov_p)) if ov_p.exists() else {}
    mp = cfg["dir"] / "reddit_mentions.json"
    mentions = json.load(open(mp)) if mp.exists() else []
    mnorm = [(norm_name(m["name"], cw), m) for m in mentions]
    out = []
    for b in roster:
        if not b["neighborhood"]:
            if not ({"rcp", "reddit", "manual"} & set(b["source_families"])):
                continue                      # outside the named areas and no student evidence
        pin = (b["pin_lat"], b["pin_lng"])
        nad = geo.geocode(cfg, b["address"]) if b.get("address") else None
        fp = geo.footprint(cfg, *(nad or pin))
        if b["canonical_name"] in overrides:
            o = overrides[b["canonical_name"]]
            b["lat"], b["lng"], b["coord_method"], review = o["lat"], o["lng"], "manual_rightclick", False
        elif fp:
            b["lat"], b["lng"] = fp["lat"], fp["lng"]
            b["coord_method"] = ("nad_address" if nad else "places_pin") + "+footprint_centroid"
            review = bool(nad) and haversine_m(*nad, *pin) > 60
        else:
            b["lat"], b["lng"] = (round(nad[0], 6), round(nad[1], 6)) if nad else (round(pin[0], 6), round(pin[1], 6))
            b["coord_method"] = "nad_address_point" if nad else "pin_unverified"
            review = not nad
        b["coord_review"] = review
        b["pin_vs_final_m"] = round(haversine_m(*pin, b["lat"], b["lng"]))
        floors = None
        if fp:
            floors = fp["floors"] or (max(1, round(fp["height"] / 3.2)) if fp.get("height") else None)
            b["footprint_m2"], b["floors_est"] = fp["area_m2"], floors
            b["units_est"] = round(fp["area_m2"] * (floors or 2) * 0.8 / 75) if fp["area_m2"] else None
        # ---- student-relevance score
        nn = norm_name(b["canonical_name"], cw)
        names = [nn] + [norm_name(a, cw) for a in b["aliases"]]
        def hit(k):   # students shorten names: "Callaway" = The Callaway House, "Rise" = Rise at West Campus
            kt = set(k.split())
            return any(name_sim(k, n) >= 90 or (kt and kt <= set(n.split())) for n in names)
        th = max([m["threads"] for k, m in mnorm if hit(k)] or [0])
        b["reddit_threads"] = th
        fam = set(b["source_families"])
        s = 0.0
        s += 3 if "rcp" in fam else 0
        s += min(3, th)
        s += 1.0 * (len(fam) - 1)
        s += 2 if b["dist_campus_m"] <= 1500 else (1 if b["dist_campus_m"] <= cfg["core_radius_m"] else 0)
        s += 1 if b["rating_count"] >= 20 else 0
        s += 1 if (b.get("units_est") or 0) >= 40 else 0
        s += 1 if b["building_type"] in ("student_housing", "co_op", "dorm") else 0
        s += 0.5 if b.get("website") else 0
        s -= 2 if b.get("needs_review") else 0
        if (b.get("footprint_m2") or 999) < 220 and len(fam) == 1 and b["building_type"] == "apartment":
            s -= 3                             # almost certainly a single house / small plex
        b["student_score"] = round(s, 1)
        out.append(b)
    out.sort(key=lambda b: (-b["student_score"], b["dist_campus_m"]))
    for i, b in enumerate(out):
        b["rank"] = i + 1
        b["tier"] = "A" if b["student_score"] >= 4 else ("B" if b["student_score"] >= 2 else "C")
    final = [b for b in out if b["tier"] in ("A", "B")]
    if len(final) < min_n:
        final = out[:min_n]
    (cfg["dir"] / "roster_ranked.json").write_text(json.dumps(out, indent=1))
    (cfg["dir"] / "roster_final.json").write_text(json.dumps(final, indent=1))
    cols = ["rank", "tier", "student_score", "canonical_name", "aliases", "building_type", "neighborhood", "address", "lat", "lng",
            "coord_method", "coord_review", "dist_campus_m", "units_est", "reddit_threads", "source_families", "website", "place_id"]
    with open(cfg["dir"] / "roster_final.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for b in final:
            w.writerow({**b, "aliases": "; ".join(b["aliases"]), "source_families": "+".join(b["source_families"])})
    from collections import Counter
    print(f"ranked={len(out)} final={len(final)} tiers={dict(Counter(b['tier'] for b in out))}")
    print("final by type:", dict(Counter(b["building_type"] for b in final)))
    print("coord methods:", dict(Counter(b["coord_method"] for b in final)), "review:", sum(b["coord_review"] for b in final))


if __name__ == "__main__":
    main(sys.argv[1])
