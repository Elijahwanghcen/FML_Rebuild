"""Source 2 (free, storable): Overture Maps places + building footprints for the campus bbox.

places  -> extra discovery candidates + alternate names
buildings -> footprint polygons used by coords_footprint.py for owned, rooftop coordinates
"""
import json, subprocess, sys
from common import campus, offset, haversine_m

RES_CATS = ("apartment", "condominium", "university_housing", "dormitor", "student_housing",
            "property_management", "housing_cooperative", "townhouse")


def bbox(center, r):
    lo, hi = offset(center[0], center[1], -r, -r), offset(center[0], center[1], r, r)
    return f"{lo[1]:.5f},{lo[0]:.5f},{hi[1]:.5f},{hi[0]:.5f}"


def dl(cfg, typ, center, r, tag):
    out = cfg["dir"] / "cache" / f"overture_{typ}_{tag}.geojsonseq"
    if not out.exists() or out.stat().st_size == 0:
        subprocess.run(["overturemaps", "download", f"--bbox={bbox(center, r)}", "-f", "geojsonseq",
                        "-t", typ, "-o", str(out)], check=True)
    return out


def main(slug):
    cfg = campus(slug)
    areas = [("core", cfg["center"], cfg["core_radius_m"] + 600)] + \
            [(n["name"].lower().replace(" ", "_"), n["center"], n["radius_m"] + 400) for n in cfg["neighborhoods"]]
    cands, seen, agents = [], set(), []
    for tag, c, r in areas:
        dl(cfg, "building", c, r, tag)
        dl(cfg, "address", c, r, tag)
        for line in open(dl(cfg, "place", c, r, tag)):
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            f = json.loads(line)
            p = f["properties"]
            tax = p.get("taxonomy") or {}
            cats = {"primary": tax.get("primary") or p.get("basic_category"),
                    "alternate": tax.get("alternates") or tax.get("hierarchy")}
            allc = " ".join([p.get("basic_category") or "", tax.get("primary") or ""])
            pid = p.get("id") or f.get("id")
            if pid in seen or (p.get("operating_status") == "closed"):
                continue
            if "real_estate" in allc and not any(k in allc for k in RES_CATS):
                # realtors are not buildings, but their sites list condos -> feed discover_pm_sites
                lng, lat = f["geometry"]["coordinates"]
                w = (p.get("websites") or [None])[0]
                if w:
                    seen.add(pid)
                    agents.append({"name": (p.get("names") or {}).get("primary"), "website": w, "category": "property_management",
                                   "dist_m": round(haversine_m(cfg["center"][0], cfg["center"][1], lat, lng))})
                continue
            if not any(k in allc for k in RES_CATS):
                continue
            seen.add(pid)
            lng, lat = f["geometry"]["coordinates"]
            addr = (p.get("addresses") or [{}])[0]
            cands.append({"overture_id": pid, "name": (p.get("names") or {}).get("primary"),
                          "address": addr.get("freeform"), "lat": lat, "lng": lng,
                          "category": cats.get("primary"), "alt_categories": cats.get("alternate"),
                          "website": (p.get("websites") or [None])[0],
                          "confidence": p.get("confidence"),
                          "dist_m": round(haversine_m(cfg["center"][0], cfg["center"][1], lat, lng)),
                          "sources": ["overture_places"]})
    (cfg["dir"] / "cand_overture.json").write_text(json.dumps(cands, indent=1))
    (cfg["dir"] / "pm_overture_agents.json").write_text(json.dumps(agents, indent=1))
    print("overture residential-ish places:", len(cands), "realtor sites:", len(agents))


if __name__ == "__main__":
    main(sys.argv[1])
