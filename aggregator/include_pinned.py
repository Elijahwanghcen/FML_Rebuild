#!/usr/bin/env python3
"""Union locked / ADD buildings into the roster and into the enrich slice.

select_roster keeps a ranked top cut. Buildings that exist only as a manager-portfolio
URL, a university table, or a low review count fall out of that cut. This step puts
them back. It does not delete discovery rows.

  python3 include_pinned.py <campus> [topN]
Reads data/<campus>/roster_final.json when present, data/<campus>/added_buildings.json,
and ADD entries in resolutions.json. Writes roster_enrich.json as the top N plus every
pinned building not already in that slice.
"""
import json
import sys
from pathlib import Path

from common import campus
from pinned_sources import norm_key


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def additions(cfg):
    out = []
    for b in _load(cfg["dir"] / "added_buildings.json", []):
        out.append(b)
    res = _load(cfg["dir"] / "resolutions.json", {})
    for r in res.get("resolutions") or []:
        if r.get("status") != "ADD":
            continue
        name = r.get("canonical_name") or r.get("original_name")
        if not name:
            continue
        out.append({
            "canonical_name": name,
            "aliases": r.get("aliases_add") or [],
            "address": r.get("property_address") or r.get("address") or "",
            "website": r.get("website_url") or r.get("floorplans_url"),
            "website_locked": True,
            "floorplans_url": r.get("floorplans_url"),
            "building_type": r.get("building_type") or "apartment",
            "source_families": ["manual", "add"],
            "neighborhood": r.get("neighborhood"),
            "pin_lat": (r.get("lat") or cfg["center"][0]),
            "pin_lng": (r.get("lng") or cfg["center"][1]),
            "dist_campus_m": r.get("dist_campus_m"),
            "rating_count": 0,
            "needs_review": True,
            "resolution_status": "ADD",
            "miss_cause": r.get("miss_cause") or "ranked_below_cut",
        })
    return out


def union_roster(roster, extra):
    seen = {norm_key(b.get("canonical_name")) for b in roster}
    added = []
    for b in extra:
        k = norm_key(b.get("canonical_name"))
        if not k or k in seen:
            continue
        seen.add(k)
        row = dict(b)
        row.setdefault("aliases", [])
        row.setdefault("source_families", ["manual"])
        added.append(row)
    return roster + added, added


def enrich_slice(roster, top_n, pinned_names):
    """Top N plus every pinned name, in roster order, without duplicates."""
    head = list(roster[:top_n])
    have = {norm_key(b.get("canonical_name")) for b in head}
    for b in roster:
        k = norm_key(b.get("canonical_name"))
        if k in pinned_names and k not in have:
            head.append(b)
            have.add(k)
    return head


def pinned_name_keys(cfg):
    listing = _load(cfg["dir"] / "listing_config.json", {})
    keys = set()
    for p in listing.get("properties") or []:
        if p.get("locked"):
            keys.add(norm_key(p.get("property_name")))
    for b in _load(cfg["dir"] / "added_buildings.json", []):
        keys.add(norm_key(b.get("canonical_name")))
    return {k for k in keys if k}


def main(slug, top_n=170):
    cfg = campus(slug)
    roster_path = cfg["dir"] / "roster_final.json"
    roster = _load(roster_path, [])
    merged, added = union_roster(roster, additions(cfg))
    if roster_path.parent.exists() and roster:
        roster_path.write_text(json.dumps(merged, indent=1))
    keys = pinned_name_keys(cfg) | {norm_key(b["canonical_name"]) for b in added}
    # When discovery has not been run, the enrich slice is the pinned additions themselves.
    slice_ = enrich_slice(merged, int(top_n), keys) if merged else merged
    if slice_:
        (cfg["dir"] / "roster_enrich.json").write_text(json.dumps(slice_, indent=1))
    print(f"roster {len(roster)} -> {len(merged)} (+{len(added)} pins); enrich {len(slice_)}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 170)
