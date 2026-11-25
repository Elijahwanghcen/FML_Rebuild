"""Write the FML_Data advertised-prices CSV and nested JSON.

Column order, property objectID, scraped_ts and numeric typing match
austin_leases_units/scraper/run.py. Unit objectIDs use the Algolia form
`{property-slug}__{label-slug}` (sqft suffix, then a collision suffix) and are
written to a sibling `*.unit_ids.json`. They are not inserted into the nested
units, so that JSON stays the run.py contract.
"""
import csv
import datetime
import json
import re
from pathlib import Path

FIELDS = [
    "property_name", "address", "unit_or_floorplan_label", "beds", "baths",
    "sqft", "base_rent", "total_price_with_mandatory_fees", "price_basis",
    "concessions_raw", "concessions_type", "concessions_value", "availability",
    "layout_image_url", "price_image_url", "concessions_image_url",
    "source_url", "source_type", "price_status", "scraped_at",
]
PROPERTY_FIELDS = ["property_name", "address", "source_url", "source_type", "scraped_at"]
UNIT_FIELDS = [f for f in FIELDS if f not in PROPERTY_FIELDS]
NUMERIC_FIELDS = {
    "beds", "baths", "sqft", "base_rent",
    "total_price_with_mandatory_fees", "concessions_value",
}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def to_num(s):
    if s is None or s == "":
        return None
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s
    return int(f) if isinstance(f, float) and f.is_integer() else f


def scraped_stamps(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    day = now.astimezone(datetime.timezone.utc).date()
    scraped_at = now.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")
    scraped_ts = int(datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc).timestamp())
    return scraped_at, scraped_ts, day.isoformat()


def property_record(prop, rows, scraped_at, scraped_ts):
    name = prop["property_name"]
    url = prop["url"]
    source_type = prop.get("source_type") or "first_party"
    address = prop.get("address") or ""
    record = {
        "objectID": slugify(name),
        "property_name": name,
        "address": address,
        "source_url": url,
        "source_type": source_type,
        "scraped_at": scraped_at,
        "scraped_ts": scraped_ts,
        "units": [],
    }
    flat = []
    for r in rows:
        r_out = dict(r)
        r_out["property_name"] = name
        r_out["address"] = address
        r_out["source_url"] = url
        r_out["source_type"] = source_type
        r_out["scraped_at"] = scraped_at
        flat.append({k: r_out.get(k, "") for k in FIELDS})
        record["units"].append({
            k: (to_num(r_out.get(k)) if k in NUMERIC_FIELDS else (r_out.get(k) or None))
            for k in UNIT_FIELDS
        })
    return record, flat


def unit_object_ids(property_slug, units):
    """Algolia objectID = {property}__{label-slug}[-{sqft}], collisions suffixed.

    Same rule as austin_leases_algolia_push.unit_ids. Content-derived, not row order
    of the first assignment: ties break on layout image then rent, matching that script.
    """
    groups = {}
    order = []
    for u in units:
        base = slugify(u.get("unit_or_floorplan_label") or "")
        sqft = u.get("sqft")
        if sqft not in (None, ""):
            base = f"{base}-{sqft}"
        if base not in groups:
            order.append(base)
        groups.setdefault(base, []).append(u)
    out = []
    for base in order:
        group = groups[base]
        group.sort(key=lambda u: (
            (u.get("layout_image_url") or ""),
            u["base_rent"] if isinstance(u.get("base_rent"), (int, float)) else -1,
        ))
        for i, u in enumerate(group):
            oid = f"{property_slug}__{base}" if i == 0 else f"{property_slug}__{base}-{i + 1}"
            out.append({"objectID": oid, "property_objectID": property_slug,
                        "unit_label": u.get("unit_or_floorplan_label"),
                        "base_rent": u.get("base_rent"), "sqft": u.get("sqft"),
                        "price_status": u.get("price_status"), "source_type": None})
    return out


def write_legacy(records, csv_rows, unit_ids, out_dir, day):
    out_dir = Path(out_dir)
    csv_dir = out_dir / "csv outputs"
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / f"advertised_prices_{day}.csv"
    json_path = out_dir / f"advertised_prices_{day}.json"
    ids_path = out_dir / f"advertised_prices_{day}.unit_ids.json"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in csv_rows:
            w.writerow(row)
    json_path.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    ids_path.write_text(json.dumps(unit_ids, indent=2, ensure_ascii=False))
    return {"csv": csv_path, "json": json_path, "unit_ids": ids_path}
