#!/usr/bin/env python3
"""Compare a campus roster with a reference list and report likely misses.

Reference lists, in the order a new campus should collect them:
  1. Google Places grid (discover_places.py) and Overture footprints
  2. University off-campus housing list (discover_rcp.py / discover_ocp.py) as names only
  3. Property-manager portfolios (discover_pm_sites.py), including condo landlords
  4. Aggregators as lead lists, never as the rent source
  5. An existing catalog (RMR, a previous scrape, properties_config.json)

  python3 campus_completeness.py <campus> [--reference path.json] [--roster path.json]

--reference is a JSON list, or {"properties": [...]} with property_name / canonical_name.
Default reference for ut_austin is the synced FML_Data properties_config.json.
Default roster is data/<campus>/out/buildings.json when present, else roster_final.json.
Exit 1 when the reference has buildings the roster does not name.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from common import campus
from miss_causes import classify, rule
from pinned_sources import ROSTER_ALIAS, load_fml, norm_key, roster_names


def load_reference(cfg, path):
    if path:
        data = json.loads(Path(path).read_text())
        rows = data["properties"] if isinstance(data, dict) and "properties" in data else data
        return rows
    if cfg["slug"] == "ut_austin":
        _backends, props = load_fml()
        return props
    return []


def load_roster(cfg, path):
    if path:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, list) else data.get("properties") or data.get("buildings") or []
    rows = []
    buildings = cfg["dir"] / "out" / "buildings.json"
    if buildings.exists():
        rows.extend(json.loads(buildings.read_text()))
    extra = cfg["dir"] / "added_buildings.json"
    if extra.exists():
        rows.extend(json.loads(extra.read_text()))
    if rows:
        return rows
    final = cfg["dir"] / "roster_final.json"
    if final.exists():
        return json.loads(final.read_text())
    return []


def as_prop(row):
    if "property_name" in row or "backend" in row:
        return row
    return {
        "property_name": row.get("canonical_name") or row.get("name") or "",
        "backend": row.get("locked_backend") or row.get("backend") or "",
        "url": row.get("website") or row.get("url") or "",
        "params": row.get("params") or {},
    }


def report(reference, roster):
    known = roster_names(roster)
    misses = []
    for row in reference:
        prop = as_prop(row)
        name = prop.get("property_name")
        alias = ROSTER_ALIAS.get(name)
        if norm_key(name) in known or (alias and norm_key(alias) in known):
            continue
        cause = row.get("miss_cause") or classify(prop)
        misses.append({
            "property_name": prop.get("property_name"),
            "backend": prop.get("backend"),
            "url": prop.get("url") or prop.get("website"),
            "cause": cause,
            "rule": rule(cause),
        })
    return misses


def main(slug, reference=None, roster=None):
    cfg = campus(slug)
    ref = load_reference(cfg, reference)
    ros = load_roster(cfg, roster)
    if not ref:
        print(f"no reference list for {slug}; pass --reference")
        return 0
    misses = report(ref, ros)
    counts = Counter(m["cause"] for m in misses)
    lines = [
        f"# Completeness: {cfg['name']}",
        "",
        f"Reference buildings: {len(ref)}",
        f"Roster rows: {len(ros)}",
        f"Reference names absent from the roster: {len(misses)}",
        "",
        "## Causes",
        "",
    ]
    for cause, n in counts.most_common():
        lines.append(f"- **{cause}** ({n}): {rule(cause)}")
    lines += ["", "## Missing", ""]
    for m in misses:
        lines.append(f"- {m['property_name']} [{m['backend'] or 'n/a'}] cause `{m['cause']}`")
    text = "\n".join(lines) + "\n"
    out = cfg["dir"] / "completeness.md"
    out.write_text(text)
    print(text)
    print(f"wrote {out}")
    return 1 if misses else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    slug = args[0]
    ref = ros = None
    if "--reference" in args:
        ref = args[args.index("--reference") + 1]
    if "--roster" in args:
        ros = args[args.index("--roster") + 1]
    sys.exit(main(slug, ref, ros))
