"""Source 4: Rent College Pads platform (rentcollegepads.com/off-campus-housing/<school>/search and the
white-labelled university directories such as housing.offcampus.utexas.edu). The search page embeds every
listing as `var listingData = JSON.parse(JSON.stringify({...}))` - no API key, no paging."""
import json, re, sys
from collections import Counter
from common import campus, haversine_m
from webtext import fetch_html


def parse(h):
    i = h.find("var listingData")
    if i < 0:
        return {}
    j = h.find("{", i)
    obj, _ = json.JSONDecoder().raw_decode(h[j:])
    return obj


def main(slug):
    cfg = campus(slug)
    out = {}
    for u in cfg.get("rcp_urls", []):
        h = fetch_html(u, cfg["dir"] / "cache" / "rcp", render="never") or ""
        d = parse(h)
        print(u, len(d))
        for k, v in d.items():
            out.setdefault(k, (u, v))
    rows = []
    for k, (u, v) in out.items():
        try:
            lat, lng = float(v.get("lat")), float(v.get("lng") or v.get("lon"))
        except Exception:
            lat = lng = None
        rows.append({"name": v.get("title"), "address": re.sub(r"\s+USA$", "", v.get("address") or ""),
                     "lat": lat, "lng": lng, "type": v.get("category_title"),
                     "manager": v.get("landlord_company"), "units": v.get("units_number"),
                     "url": u.split("/off-campus")[0].split("/listing")[0] + "/listing/" + str(v.get("slug")),
                     "rcp_id": k, "landlord_website": v.get("landlord_website") or v.get("website") or None,
                     "rent_style": v.get("rent_style"),
                     "floorplans": [{"beds": f.get("bed"), "baths": f.get("bath"), "min_rent": f.get("min_rent"),
                                     "max_rent": f.get("max_rent"), "sqft": f.get("sq_footage"), "title": f.get("title"),
                                     "available": f.get("available_date"), "status": f.get("status")}
                                    for f in (v.get("floorplans") or []) if isinstance(f, dict)],
                     "feature_strings": [x.strip() for grp in ((v.get("features") or {}).values() if isinstance(v.get("features"), dict) else [])
                                         for x in (grp if isinstance(grp, list) else []) if isinstance(x, str)]
                                        + [x for x in (v.get("utilities") or []) if isinstance(x, str)]
                                        + [x for x in (v.get("pets") or []) if isinstance(x, str)],
                     "images": ["https://rcp-prod-uploads.s3.amazonaws.com/property_images/slider_images/" + i
                                for i in (v.get("images") or [])[:8] if isinstance(i, str)],
                     "dist_m": round(haversine_m(cfg["center"][0], cfg["center"][1], lat, lng)) if lat else None,
                     "sources": ["rcp_directory"]})
    (cfg["dir"] / "cand_rcp.json").write_text(json.dumps(rows, indent=1))
    print(len(rows), Counter(r["type"] for r in rows))
    return out


if __name__ == "__main__":
    o = main(sys.argv[1])
    if "-v" in sys.argv:
        v = next(iter(o.values()))[1]
        print({k: (str(x)[:60]) for k, x in v.items()})
