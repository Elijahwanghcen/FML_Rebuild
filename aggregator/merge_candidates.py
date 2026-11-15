"""Merge every discovery source into one deduplicated building roster with aliases.

Dedupe is the core of the system (properties are renamed constantly, one building has many names,
one Google listing can stand for several buildings). Rules:
  * only compare candidates within 200 m of each other
  * merge when   same street-number address                      (any name)
            or   <=60 m  and name similarity >= 85
            or   <=200 m and name similarity >= 92
  * never merge on proximity alone (1883 at Cameron House vs 1883 at Montgomery House are 30 m apart)
Every surviving name becomes an alias; every source is kept for provenance.
"""
import csv, json, re, sys
from collections import Counter, defaultdict
from rapidfuzz import fuzz
from common import campus, haversine_m, norm_name, norm_addr, street_number, name_sim
import geo

RES_TYPES = {"apartment_building", "apartment_complex", "condominium_complex", "housing_complex"}
DROP_TYPES = {"hotel", "lodging", "hostel", "guest_house", "school", "motel", "bed_and_breakfast", "extended_stay_hotel",
              "university", "storage", "parking", "church", "restaurant"}
PM_NAME = re.compile(r"\b(realty|realtors?|real estate|management|mgmt|locators?|locating|properties|property group|"
                     r"investments?|capital|holdings|llc|inc\.?|leasing office|brokerage|group|associates|partners|"
                     r"construction|development|homeowners|hoa|airbnb|vrbo|furnished housing|corporate housing|"
                     r"vacation|short[- ]term|rooms? for rent|sublease|sublet|room in|private room|bedroom in)\b", re.I)
BLDG_NAME = re.compile(r"apartment|apts|condo|lofts?\b|flats?\b|villas?\b|co-?op\b|residen|tower|place\b|court\b|"
                       r"house\b|hall\b|dorm|square|terrace|manor|arms\b|plaza|gardens?\b|pointe?\b|commons|village|"
                       r"townhomes|student living|on \d|at \d", re.I)
LISTING_TITLE = re.compile(r"\bsq\.? ?f|\bwalk to\b|\bmin(ute)?s? (walk|to|from)|\b\d ?(br|bd|bed(room)?s?)\b|\bnear ut\b|"
                           r"\bpool view|\bcozy\b|\bspacious\b|\bcharming\b|\bentire\b|\bgetaway\b|\bstay\b|!|\$", re.I)
UNIT = re.compile(r"\s*(#|unit|apt\.?|suite|ste\.?)\s*[\w-]+\s*$", re.I)
SKIP_RCP = {"House", "Duplex", "Room", "Townhouse", "Sublet"}


def fn_is_unit(name):
    """Directory rows titled with a bare street address are single units / houses, not buildings."""
    return True


def kind_of(name, types):
    n = (name or "").lower()
    t = " ".join(types).lower()
    if re.search(r"co-?op\b|cooperative", n + " " + t):
        return "co_op"
    if re.search(r"\bdorm|residence hall|\bhall\b|university_housing|residence halls|private dorm", n + " " + t):
        return "dorm"
    if re.search(r"condo", n + " " + t):
        return "condo"
    if re.search(r"student", n + " " + t):
        return "student_housing"
    return "apartment"


def load(cfg):
    d, rows = cfg["dir"], []
    def add(**k):
        k["name"] = UNIT.sub("", re.sub(r"\s+", " ", (k.get("name") or "")).strip())
        if k["name"] and not LISTING_TITLE.search(k["name"]):
            rows.append(k)
    f = d / "cand_places.json"
    for x in json.load(open(f)) if f.exists() else []:
        pt, ts, nm = x.get("primary_type"), set(x.get("types") or []), x.get("name") or ""
        if pt in DROP_TYPES or (ts & DROP_TYPES and not ts & RES_TYPES) or x.get("status") == "CLOSED_PERMANENTLY":
            continue
        res = bool(ts & RES_TYPES)
        if PM_NAME.search(nm) and not BLDG_NAME.search(PM_NAME.sub("", nm)):
            continue
        review = False
        if not res and not BLDG_NAME.search(nm):
            # e.g. Dobie Twenty21 is typed shopping_mall. Keep only if a housing text query surfaced it; flag it.
            if not any(s.startswith("places_text:") and re.search(r"student|dorm|co-op", s) for s in x["sources"]) \
                    or x["dist_m"] > cfg["core_radius_m"] or PM_NAME.search(nm):
                continue
            review = True
        add(name=nm, address=x.get("address"), lat=x["lat"], lng=x["lng"], types=sorted(ts & RES_TYPES) or [pt or ""],
            website=x.get("website"), place_id=x["place_id"], rating_count=x.get("rating_count") or 0, fam="places",
            sources=x["sources"], review=review)
    f = d / "cand_overture.json"
    for x in json.load(open(f)) if f.exists() else []:
        if x["category"] in ("property_management", "apartment_agent", "service_apartment") or PM_NAME.search(x["name"] or ""):
            continue
        add(name=x["name"], address=x.get("address"), lat=x["lat"], lng=x["lng"], types=[x["category"]],
            website=x.get("website"), fam="overture", sources=["overture_places"])
    for x in [y for fn in ("cand_rcp.json", "cand_ocp.json") if (d / fn).exists() for y in json.load(open(d / fn))]:
        if x["type"] in SKIP_RCP or x["lat"] is None or (street_number(x["name"]) and fn_is_unit(x["name"])):
            continue
        add(name=x["name"], address=x.get("address"), lat=x["lat"], lng=x["lng"], types=[x["type"] or ""],
            website=x.get("url"), manager=x.get("manager"), fam="rcp", sources=x.get("sources") or ["rcp_directory"])
    for fn, fam in (("cand_pm_raw.json", "pm"), ("cand_reddit.json", "reddit"), ("cand_manual.json", "manual")):
        f = d / fn
        for x in json.load(open(f)) if f.exists() else []:
            if (x.get("type") or "") in ("house", "duplex") or PM_NAME.search(x["name"] or ""):
                continue
            add(name=x["name"], address=x.get("address"), lat=x.get("lat"), lng=x.get("lng"), types=[x.get("type") or ""],
                website=x.get("url"), fam=fam, sources=x["sources"])
    return rows


def locate(cfg, rows):
    """Give coordinate-less candidates (PM sites, Reddit) a position: NAD address point, else the
    position of an already-located candidate with the same normalised name."""
    cw = set(cfg.get("city_words", []))
    byname = defaultdict(list)
    for r in rows:
        if r.get("lat") is not None:
            byname[norm_name(r["name"], cw)].append(r)
    out, unresolved = [], []
    for r in rows:
        if r.get("lat") is None:
            a = r.get("address") or (r["name"] if street_number(r["name"]) else None)
            g = geo.geocode(cfg, a) if a else None
            if g:
                r["lat"], r["lng"], r["located_by"] = g[0], g[1], "nad_address"
            else:
                m = byname.get(norm_name(r["name"], cw))
                if m and norm_name(r["name"], cw):
                    r["lat"], r["lng"], r["located_by"] = m[0]["lat"], m[0]["lng"], "name_match"
                else:
                    unresolved.append(r)
                    continue
        out.append(r)
    return out, unresolved


def cluster(cfg, rows):
    cw = set(cfg.get("city_words", []))
    for r in rows:
        r["_n"] = norm_name(r["name"], cw)
        a = norm_addr(r.get("address") or "")
        r["_a"] = a if street_number(a) else ""
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    grid = defaultdict(list)
    for i, r in enumerate(rows):
        grid[(round(r["lat"] / 0.002), round(r["lng"] / 0.002))].append(i)
    for (gy, gx), idxs in grid.items():
        near = [j for dy in (-1, 0, 1) for dx in (-1, 0, 1) for j in grid.get((gy + dy, gx + dx), [])]
        for i in idxs:
            for j in near:
                if j <= i:
                    continue
                a, b = rows[i], rows[j]
                d = haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
                if d > 200:
                    continue
                same_pid = a.get("place_id") and a.get("place_id") == b.get("place_id")
                same_addr = a["_a"] and a["_a"] == b["_a"]
                s = name_sim(a["_n"], b["_n"])
                # an address-as-name ("2400 Nueces") vs a real name at the same spot
                if same_pid or same_addr or (d <= 60 and s >= 85) or s >= 92:
                    if same_addr and s < 50 and a["fam"] == b["fam"] == "places" and d > 25:
                        continue      # two differently named Google listings sharing a street address
                    parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[find(i)].append(r)
    return list(groups.values())


FAM_RANK = {"manual": 0, "rcp": 1, "places": 2, "pm": 3, "reddit": 4, "overture": 5}


def build(cfg, groups):
    c0, out = cfg["center"], []
    cw = set(cfg.get("city_words", []))
    for g in groups:
        g.sort(key=lambda r: (FAM_RANK[r["fam"]], -(r.get("rating_count") or 0)))
        named = [r for r in g if not street_number(r["name"])] or g
        head = named[0]
        names = Counter()
        for r in g:
            names[r["name"]] += 1
        aliases, seen = [], {norm_name(head["name"], cw).replace(" ", "")}
        for n, _ in names.most_common():
            k = norm_name(n, cw).replace(" ", "")
            if k and k not in seen:
                seen.add(k); aliases.append(n)
        pl = [r for r in g if r["fam"] == "places"]
        pin = (pl or [r for r in g if r.get("located_by") == "nad_address"] or g)[0]
        addr = next((r["address"] for r in g if r.get("address") and street_number(r["address"])), None)
        fams = sorted({r["fam"] for r in g})
        types = [t for r in g for t in r.get("types", []) if t]
        lat, lng = pin["lat"], pin["lng"]
        dist = haversine_m(c0[0], c0[1], lat, lng)
        nb = None
        for n in cfg["neighborhoods"]:
            if haversine_m(n["center"][0], n["center"][1], lat, lng) <= n["radius_m"] * 1.25:
                nb = n["name"]; break
        if nb is None and dist <= cfg["core_radius_m"]:
            nb = "campus_core"
        webs = [r["website"] for r in g if r.get("website")]
        out.append({"canonical_name": head["name"], "aliases": aliases, "address": addr,
                    "pin_lat": lat, "pin_lng": lng, "building_type": kind_of(" ".join(names), types),
                    "neighborhood": nb, "dist_campus_m": round(dist),
                    "place_id": next((r["place_id"] for r in pl), None),
                    "rating_count": max([r.get("rating_count") or 0 for r in g]),
                    "website": next((w for r in g if r["fam"] == "places" for w in [r.get("website")] if w), webs[0] if webs else None),
                    "other_urls": sorted(set(webs))[:6], "manager": next((r["manager"] for r in g if r.get("manager")), None),
                    "source_families": fams, "sources": sorted({s for r in g for s in r["sources"]}),
                    "n_records": len(g), "needs_review": all(r.get("review") for r in g)})
    return out


def main(slug):
    cfg = campus(slug)
    rows = load(cfg)
    rows, unresolved = locate(cfg, rows)
    rows = [r for r in rows if haversine_m(cfg["center"][0], cfg["center"][1], r["lat"], r["lng"]) <= cfg["max_radius_m"]]
    roster = build(cfg, cluster(cfg, rows))
    roster.sort(key=lambda r: r["dist_campus_m"])
    for r in roster:   # eval_coverage compatibility
        r["name"], r["lat"], r["lng"] = r["canonical_name"], r["pin_lat"], r["pin_lng"]
    (cfg["dir"] / "roster_merged.json").write_text(json.dumps(roster, indent=1))
    (cfg["dir"] / "unresolved_candidates.json").write_text(json.dumps(
        [{k: v for k, v in r.items() if not k.startswith("_")} for r in unresolved], indent=1))
    ins = [r for r in roster if r["neighborhood"]]
    print(f"records={len(rows)} buildings={len(roster)} in_scope={len(ins)} unresolved={len(unresolved)}")
    print("in-scope by type:", Counter(r["building_type"] for r in ins))
    print("in-scope by #source families:", Counter(len(r["source_families"]) for r in ins))


if __name__ == "__main__":
    main(sys.argv[1])
