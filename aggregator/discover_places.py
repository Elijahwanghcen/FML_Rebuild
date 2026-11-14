"""Source 1: Google Places (New). Adaptive nearby-search grid + text searches.

Nearby Search returns at most 20 places and has no paging, so a fixed grid
silently truncates dense blocks. We quadtree instead: any cell that comes back
full (20) is split in four until it is not full or is < MIN_HALF metres.
Text Search (3 pages = 60) then catches places whose Google *type* is not
residential (leasing offices typed real_estate_agency, co-ops, private dorms).
"""
import json, sys
from common import campus, places_post, places_spend, offset, haversine_m

TYPES = ["apartment_building", "apartment_complex", "condominium_complex", "housing_complex"]
FM = ",".join("places." + f for f in ("id", "displayName", "formattedAddress", "location", "types",
                                      "primaryType", "websiteUri", "rating", "userRatingCount",
                                      "businessStatus"))
MIN_HALF = 70
TEXT_Q = ["student apartments", "apartments", "student housing", "condominiums", "condos for rent",
          "housing co-op", "private dormitory", "apartment complex"]
BUDGET = 25.0


def nearby(cfg, lat, lng, half, out, depth=0):
    if places_spend(cfg) > BUDGET:
        raise SystemExit("Places budget reached - stop and ask")
    body = {"includedTypes": TYPES, "maxResultCount": 20, "rankPreference": "DISTANCE",
            "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng},
                                               "radius": half * 1.4143}}}
    res = places_post(cfg, "searchNearby", body, FM).get("places", [])
    for p in res:
        out.setdefault(p["id"], {**p, "_src": set()})["_src"].add("places_nearby")
    if len(res) >= 20 and half > MIN_HALF:
        q = half / 2
        for dn in (-q, q):
            for de in (-q, q):
                la, ln = offset(lat, lng, dn, de)
                nearby(cfg, la, ln, q, out, depth + 1)


def text(cfg, query, center, radius, out):
    lat, lng = center
    lo, hi = offset(lat, lng, -radius, -radius), offset(lat, lng, radius, radius)
    body = {"textQuery": query, "pageSize": 20,
            "locationRestriction": {"rectangle": {"low": {"latitude": lo[0], "longitude": lo[1]},
                                                  "high": {"latitude": hi[0], "longitude": hi[1]}}}}
    for _ in range(3):
        if places_spend(cfg) > BUDGET:
            raise SystemExit("Places budget reached - stop and ask")
        r = places_post(cfg, "searchText", body, FM + ",nextPageToken")
        for p in r.get("places", []):
            out.setdefault(p["id"], {**p, "_src": set()})["_src"].add("places_text:" + query.split(" near ")[0])
        tok = r.get("nextPageToken")
        if not tok:
            break
        body = {**body, "pageToken": tok}


def main(slug):
    cfg = campus(slug)
    out = {}
    c = cfg["center"]
    # 1. core: quadtree over the square around campus
    h = cfg["core_radius_m"]
    nearby(cfg, c[0], c[1], h, out)
    # 2. each named neighbourhood (covers the ones outside the core)
    for nb in cfg["neighborhoods"]:
        nearby(cfg, nb["center"][0], nb["center"][1], nb["radius_m"], out)
    n_near = len(out)
    # 3. text searches per neighbourhood + campus-wide
    areas = [{"name": cfg["short"][-1], "center": c, "radius_m": cfg["core_radius_m"]}] + cfg["neighborhoods"]
    for a in areas:
        for q in TEXT_Q:
            text(cfg, f"{q} near {a['name']} {cfg['city']} {cfg['state']}", a["center"], a["radius_m"] * 1.3, out)
    rows = []
    for p in out.values():
        loc = p.get("location", {})
        rows.append({"place_id": p["id"], "name": p.get("displayName", {}).get("text"),
                     "address": p.get("formattedAddress"), "lat": loc.get("latitude"),
                     "lng": loc.get("longitude"), "types": p.get("types", []),
                     "primary_type": p.get("primaryType"), "website": p.get("websiteUri"),
                     "rating_count": p.get("userRatingCount"), "status": p.get("businessStatus"),
                     "dist_m": round(haversine_m(c[0], c[1], loc.get("latitude", 0), loc.get("longitude", 0))),
                     "sources": sorted(p["_src"])})
    (cfg["dir"] / "cand_places.json").write_text(json.dumps(rows, indent=1))
    print(f"nearby={n_near} total={len(rows)} est_spend=${places_spend(cfg):.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
