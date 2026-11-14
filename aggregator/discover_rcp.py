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
                     "rcp_id": k,
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
