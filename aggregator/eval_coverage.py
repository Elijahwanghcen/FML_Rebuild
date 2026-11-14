"""Compare a candidate set against a ground-truth roster (name + lat/lng).
A roster building counts as found if a candidate is (<=150 m and name sim >=60) or (name sim >=88 and <=1.5 km).
Usage: eval_coverage.py <campus> <roster_coords.csv> <cand.json> [...]
"""
import csv, json, sys
from rapidfuzz import fuzz
from common import campus, haversine_m, norm_name, name_sim


def load(paths):
    out = []
    for p in paths:
        out += json.load(open(p))
    return out


def match(r, cands, cw):
    rn = norm_name(r["name"], cw)
    best = None
    for c in cands:
        if c.get("lat") is None:
            continue
        d = haversine_m(r["lat"], r["lng"], c["lat"], c["lng"])
        if d > 1500:
            continue
        s = max(name_sim(rn, norm_name(n, cw)) for n in [c["name"]] + (c.get("aliases") or []) if n) if c.get("name") else 0
        ok = (d <= 150 and s >= 60) or s >= 88
        score = s - d / 30
        if ok and (best is None or score > best[0]):
            best = (score, c, round(d), s)
    return best


def main():
    cfg = campus(sys.argv[1])
    cw = set(cfg.get("city_words", []))
    roster = [{"name": r["canonical_name"], "lat": float(r["lat"]), "lng": float(r["lng"])}
              for r in csv.DictReader(open(sys.argv[2])) if r.get("lat")]
    cands = load(sys.argv[3:])
    c0 = cfg["center"]
    found, miss = [], []
    for r in roster:
        m = match(r, cands, cw)
        r["dist_campus"] = round(haversine_m(c0[0], c0[1], r["lat"], r["lng"]))
        (found if m else miss).append((r, m))
    print(f"roster={len(roster)} found={len(found)} ({100*len(found)/len(roster):.0f}%) missed={len(miss)}")
    for r, _ in sorted(miss, key=lambda x: x[0]["dist_campus"]):
        near = sorted(((haversine_m(r["lat"], r["lng"], c["lat"], c["lng"]), c["name"]) for c in cands if c.get("lat")),
                      key=lambda x: x[0])[:2]
        print(f"  MISS {r['name']:<42} {r['dist_campus']:>6}m  nearest: " + "; ".join(f"{n} ({d:.0f}m)" for d, n in near))
    json.dump({"found": [{"roster": r["name"], "cand": m[1]["name"], "d": m[2], "sim": m[3], "sources": m[1].get("sources")} for r, m in found],
               "missed": [r["name"] for r, _ in miss]}, open(cfg["dir"] / "coverage_eval.json", "w"), indent=1)


if __name__ == "__main__":
    main()
