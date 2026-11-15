"""Source 4b: Off Campus Partners directories (CoStar; e.g. aggiesearch.tamu.edu). Akamai blocks every scripted
client, so the rows are collected inside the user's own Chrome and handed to recv_local.py:
  1. in the tab: for n in 1..totalPages fetch('/housing/page-'+n); parse <script id="ocp-state">; the search response body
     is JSON escaped with &q; (") &a; (&) &s; (') &l; (<) &g; (>); placards[] carry name + geography{streetAddress,lat,lng}
  2. drop isSublet / isSharedSpace and listing-title names, join rows as name|street|city|lat|lng|perBed|id
  3. put the text in window.name, navigate the tab to http://127.0.0.1:8766/ and fetch('/?i=&n=&d=') it in chunks
     (window.name survives the cross-origin navigation; page->localhost fetches are otherwise held by Chrome)
This script turns cache/ocp_rows.txt into cand_ocp.json."""
import json, sys
from common import campus, haversine_m


def main(slug):
    cfg = campus(slug)
    rows = []
    for l in open(cfg["dir"] / "cache" / "ocp_rows.txt"):
        p = l.rstrip("\n").split("|")
        if len(p) < 7:
            continue
        lat, lng = float(p[3]), float(p[4])
        d = haversine_m(cfg["center"][0], cfg["center"][1], lat, lng)
        if d > cfg["max_radius_m"]:
            continue
        slugid = p[6]
        rows.append({"name": p[0], "address": f"{p[1]}, {p[2]}, {cfg['state']}", "lat": lat, "lng": lng,
                     "type": "Apartment Building", "manager": None, "rent_style": "person" if p[5] == "1" else "unit",
                     "url": f"{cfg['ocp_base']}/housing/property/x/{slugid}", "dist_m": round(d),
                     "floorplans": [], "feature_strings": [], "images": [], "sources": ["campus_directory_ocp"]})
    (cfg["dir"] / "cand_ocp.json").write_text(json.dumps(rows, indent=1))
    print("ocp rows in range:", len(rows))


if __name__ == "__main__":
    main(sys.argv[1])
