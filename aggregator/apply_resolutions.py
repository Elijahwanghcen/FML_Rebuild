"""Apply hand-verified identity decisions to the roster (runs after select_roster, before enrichment).

data/<campus>/resolutions.json holds one entry per problem building, written by a person or a research agent
following docs/PLAYBOOK_1_DISCOVERY.md section 5b. Status codes:
  KEEP                 real community; set canonical name / website / addresses as given
  KEEP_UNIT_SOURCE     real community whose only source is one unit listing (broker, manager portal)
  ALIAS_TO             row describes another roster building: merge its names and URLs into that one, drop the row
  REVIEW               plausible but unverified: keep the row, never auto-merge, publish only after review
  REJECT_PROPERTY_ROW  not a rentable community (single unit, owner entity, facility, locator): drop, keep reason
  ADD                  a building the rank cut missed. Insert it. Do not use ADD to replace a row that is already there.
A website_url given here is LOCKED: enrich_site will not swap it for a URL that "names the building".
Rejected and aliased rows go to data/<campus>/rejected_rows.json with their reason, so nothing disappears silently.

Also removes duplicate rows that slugify to the same objectID (keeps the higher-ranked one, unions names/URLs).

  python3 apply_resolutions.py <campus> [roster_file ...]      default: roster_final.json roster_enrich.json
"""
import json, sys, time
from common import campus
from enrich_site import slugify


def merge_into(dst, src):
    dst["aliases"] = list(dict.fromkeys(dst.get("aliases", []) + [src["canonical_name"]] + src.get("aliases", [])))
    dst["aliases"] = [a for a in dst["aliases"] if a != dst["canonical_name"]]
    dst["other_urls"] = list(dict.fromkeys((dst.get("other_urls") or []) + [u for u in [src.get("website")] + (src.get("other_urls") or []) if u]))
    dst["source_families"] = sorted(set(dst.get("source_families", [])) | set(src.get("source_families", [])))


def apply(cfg, roster, res, log):
    by = {r["original_name"]: r for r in res if r.get("original_name") and r.get("status") != "ADD"}
    names = {b["canonical_name"]: b for b in roster}
    out, seen = [], {}
    for b in roster:
        r = by.get(b["canonical_name"])
        if r:
            st = r["status"]
            b["resolution"] = {k: v for k, v in r.items() if k not in ("original_name",)}
            if st == "REJECT_PROPERTY_ROW":
                log.append({"name": b["canonical_name"], "address": b.get("address"), **r}); continue
            if st == "ALIAS_TO":
                t = names.get(r["alias_to"])
                if t is None and r.get("only_if_target_exists"):
                    pass                    # target not in this roster: keep the row as it is
                elif t is None:
                    raise SystemExit(f"ALIAS_TO target not in roster: {r['alias_to']}")
                else:
                    merge_into(t, b); log.append({"name": b["canonical_name"], "address": b.get("address"), **r}); continue
            if r.get("canonical_name") and r["canonical_name"] != b["canonical_name"]:
                b["aliases"] = list(dict.fromkeys([b["canonical_name"]] + b.get("aliases", [])))
                b["canonical_name"] = r["canonical_name"]
            b["aliases"] = [a for a in dict.fromkeys(b.get("aliases", []) + r.get("aliases_add", []))
                            if a not in r.get("aliases_remove", []) and a != b["canonical_name"]]
            if "website_url" in r:
                old = [u for u in [b.get("website")] + (b.get("other_urls") or []) if u]
                b["website"] = r["website_url"]
                b["website_locked"] = True
                # spam / wrong-building URLs from discovery must not come back through other_urls
                b["other_urls"] = [u for u in (r.get("unit_listing_urls") or [])] + \
                                  ([u for u in old if "aggiesearch" in u or "offcampus" in u] if st != "REVIEW" else [])
            for k in ("floorplans_url", "appfolio_portal", "address_match", "manager", "property_address",
                      "leasing_office_address", "entity_type", "property_status", "source_type", "site_status"):
                if k in r:
                    b[k] = r[k]
            if r.get("manager"):
                b["manager"] = r["manager"]
            b["needs_review"] = b.get("needs_review") or st == "REVIEW"
        s = slugify(b["canonical_name"])
        if s in seen:                       # same building listed twice (e.g. a leasing-office pin)
            merge_into(seen[s], b); log.append({"name": b["canonical_name"], "address": b.get("address"),
                                                "status": "DUPLICATE_ROW", "alias_to": seen[s]["canonical_name"]}); continue
        seen[s] = b
        out.append(b)
    names = {b["canonical_name"] for b in out}
    for r in res:
        if r.get("status") != "ADD":
            continue
        name = r.get("canonical_name") or r.get("original_name")
        if not name or name in names:
            continue
        out.append({
            "canonical_name": name,
            "aliases": list(r.get("aliases_add") or []),
            "address": r.get("property_address") or r.get("address") or "",
            "website": r.get("website_url") or r.get("floorplans_url"),
            "website_locked": bool(r.get("website_url") or r.get("floorplans_url")),
            "floorplans_url": r.get("floorplans_url"),
            "building_type": r.get("building_type") or "apartment",
            "source_families": ["manual", "add"],
            "neighborhood": r.get("neighborhood"),
            "pin_lat": r.get("lat"),
            "pin_lng": r.get("lng"),
            "dist_campus_m": r.get("dist_campus_m"),
            "rating_count": 0,
            "needs_review": True,
            "resolution_status": "ADD",
            "miss_cause": r.get("miss_cause") or "ranked_below_cut",
        })
        names.add(name)
        log.append({"name": name, "status": "ADD", "miss_cause": r.get("miss_cause")})
    return out


def main(slug, *files):
    cfg = campus(slug)
    p = cfg["dir"] / "resolutions.json"
    res = json.load(open(p))["resolutions"] if p.exists() else []
    for fn in files or ("roster_final.json", "roster_enrich.json"):
        f = cfg["dir"] / fn
        if not f.exists():
            continue
        roster = json.load(open(f))
        log = []
        new = apply(cfg, roster, res, log)
        f.write_text(json.dumps(new, indent=1))
        rp = cfg["dir"] / "rejected_rows.json"
        prev = json.load(open(rp)) if rp.exists() else []
        keep = {(x["name"], x.get("status")) for x in prev}
        prev += [dict(x, file=fn, applied=time.strftime("%Y-%m-%d")) for x in log if (x["name"], x.get("status")) not in keep]
        rp.write_text(json.dumps(prev, indent=1))
        print(f"{fn}: {len(roster)} -> {len(new)} rows; dropped/merged {len(log)}")
        missing = [r["original_name"] for r in res if r["original_name"] not in {b["canonical_name"] for b in roster}
                   and r["original_name"] not in {a for b in new for a in b.get("aliases", [])}]
        if missing:
            print("  resolutions with no matching row:", missing)


if __name__ == "__main__":
    main(*sys.argv[1:])
