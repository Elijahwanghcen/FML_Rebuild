"""Read a scrape file into canonical listing records.

Accepts:
- legacy 20-column CSV
- legacy flat JSON (a list of those rows)
- legacy nested JSON (one object per property, ``units`` nested), as written
  by FML_Data ``run.py``
- Rebuild ``units.json`` / ``units_YYYY-MM-DD.json`` rows
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from tools.scrape_archive.schema import TRACKED_FIELDS, canon, slug

_TERM_RE = re.compile(r"term:\s*(.+)", re.IGNORECASE)


def load_buildings(path: Path | None) -> dict:
    """objectID -> {name, address} from a Rebuild buildings.json. Missing file = {}."""
    if path is None or not Path(path).exists():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for building in data if isinstance(data, list) else []:
        oid = (building.get("objectID") or "").strip()
        if not oid:
            continue
        out[oid] = {
            "name": building.get("canonical_name") or oid,
            "address": canon(building.get("address")),
        }
    return out


def read_rows(path: Path) -> list[dict]:
    """Flatten whatever the file contains into source row dicts."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if suffix != ".json":
        raise ValueError(f"unsupported scrape file {path.name} (want .csv or .json)")
    data = json.loads(path.read_text(encoding="utf-8"))
    return _unwrap(data)


def _unwrap(data) -> list[dict]:
    if isinstance(data, dict):
        for key in ("rows", "records", "units", "listings", "data"):
            if isinstance(data.get(key), list) and key != "units":
                data = data[key]
                break
        else:
            # A single property record or a single rebuild/legacy row.
            data = [data]
    if not isinstance(data, list):
        raise ValueError("scrape JSON must be a list of rows or property records")
    flat: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        # Nested legacy property. Rebuild units also don't carry a `units` list.
        if "units" in item and "property_objectID" not in item and "unit_or_floorplan_label" not in item:
            flat.extend(_flatten_property(item))
        else:
            flat.append(item)
    return flat


def _flatten_property(item: dict) -> list[dict]:
    parent = {
        "property_name": item.get("property_name") or "",
        "address": item.get("address") or "",
        "source_url": item.get("source_url") or "",
        "source_type": item.get("source_type") or "",
        "scraped_at": item.get("scraped_at") or "",
        "objectID": item.get("objectID") or "",
    }
    units = item.get("units") or []
    if not units:
        return [{**parent, "_explicit_empty": True}]
    rows = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        row = dict(parent)
        row.update(unit)
        for key, value in parent.items():
            if row.get(key) in (None, ""):
                row[key] = value
        rows.append(row)
    return rows


def is_failure(row: dict) -> bool:
    label = canon(row.get("unit_or_floorplan_label") or row.get("name") or row.get("label"))
    lowered = label.casefold()
    if lowered.startswith("(extraction failed") or lowered in {"extraction failed", "(failed)"}:
        return True
    if lowered.startswith("(") and "fail" in lowered:
        return True
    availability = canon(row.get("availability")).casefold()
    if not label and "extractor status:" in availability:
        return True
    return False


def lease_term_of(row: dict, availability: str) -> str:
    explicit = canon(row.get("lease_term") if row.get("lease_term") not in (None, "") else row.get("lease_terms"))
    if explicit:
        return explicit
    match = _TERM_RE.search(availability or "")
    if not match:
        return ""
    # The legacy availability string separates clauses with an em dash.
    # A hyphen also appears inside the date range, so only the em dash cuts.
    return canon(re.split(r"\s+—\s+", match.group(1), maxsplit=1)[0])


def _identity(row: dict, buildings: dict) -> tuple[str, str]:
    prop_id = canon(row.get("property_objectID"))
    name = canon(row.get("property_name"))
    if prop_id and not name:
        name = (buildings.get(prop_id) or {}).get("name") or prop_id
    if not name:
        oid = canon(row.get("objectID"))
        # Rebuild unit ids look like "crest-at-pearl__0"; those are not property names.
        if oid and "__" not in oid:
            name = oid
    key = prop_id or slug(name)
    display = name or (buildings.get(key) or {}).get("name") or key
    return key, display


def _fields(row: dict, property_key: str, buildings: dict) -> dict:
    base = canon(row.get("base_rent"))
    if not base:
        base = canon(row.get("price_min"))
    price_min = canon(row.get("price_min"))
    price_max = canon(row.get("price_max"))
    availability = canon(row.get("availability"))
    price_status = canon(row.get("price_status")).lower()
    if not price_status:
        price_status = "listed" if base else "not_publicly_listed"
    address = canon(row.get("address")) or (buildings.get(property_key) or {}).get("address", "")
    concessions_raw = canon(row.get("concessions_raw"))
    if not concessions_raw:
        concessions_raw = canon(row.get("concession"))
    values = {
        "address": address,
        "beds": canon(row.get("beds")),
        "baths": canon(row.get("baths")),
        "sqft": canon(row.get("sqft")),
        "base_rent": base,
        # Keep the range fields only when they say something base_rent does not,
        # so a rebuild row does not catalogue the same price twice.
        "price_min": price_min if price_min and price_min != base else "",
        "price_max": price_max if price_max and price_max != base else "",
        "total_price_with_mandatory_fees": canon(row.get("total_price_with_mandatory_fees")),
        "price_basis": canon(row.get("price_basis")),
        "concessions_raw": concessions_raw,
        "concessions_type": canon(row.get("concessions_type")),
        "concessions_value": canon(row.get("concessions_value")),
        "availability": availability,
        "lease_term": lease_term_of(row, availability),
        "layout_image_url": canon(row.get("layout_image_url")),
        "price_image_url": canon(row.get("price_image_url")),
        "concessions_image_url": canon(row.get("concessions_image_url")),
        "source_url": canon(row.get("source_url")),
        "source_type": canon(row.get("source_type")),
        "price_status": price_status,
        "rent_basis": canon(row.get("rent_basis")),
        "adapter": canon(row.get("adapter")),
    }
    return {field: values.get(field, "") for field in TRACKED_FIELDS}


def normalize_record(row: dict, buildings: dict | None = None) -> dict | None:
    """One source row -> one canonical record, or None when the row is a failure stub."""
    buildings = buildings or {}
    if row.get("_explicit_empty"):
        key, display = _identity(row, buildings)
        return {
            "property_key": key,
            "property_name": display,
            "label": "",
            "label_norm": "",
            "fields": {field: "" for field in TRACKED_FIELDS},
            "explicit_empty": True,
        }
    if is_failure(row):
        return None
    label = canon(row.get("unit_or_floorplan_label") or row.get("name") or row.get("label"))
    if not label:
        return None
    key, display = _identity(row, buildings)
    return {
        "property_key": key,
        "property_name": display,
        "label": label,
        "label_norm": label.casefold(),
        "fields": _fields(row, key, buildings),
        "explicit_empty": False,
    }


def classify(rows: list[dict], buildings: dict | None = None) -> tuple[list[dict], dict]:
    """Split source rows into real records and failure-only properties.

    ``failure_only`` maps property_key -> display name for properties whose
    only rows are extraction-failed stubs. Those properties were attempted,
    not emptied: the master keeps their last real listings.
    """
    buildings = buildings or {}
    records: list[dict] = []
    failures: dict[str, str] = {}
    for row in rows:
        if is_failure(row) and not row.get("_explicit_empty"):
            key, display = _identity(row, buildings)
            failures.setdefault(key, display)
            continue
        record = normalize_record(row, buildings)
        if record is None:
            continue
        records.append(record)
    real = {record["property_key"] for record in records}
    failure_only = {key: name for key, name in failures.items() if key not in real}
    return records, failure_only


def scraped_dates(rows: list[dict]) -> list[str]:
    from tools.scrape_archive.schema import DATE_RE
    found = []
    for row in rows:
        text = str(row.get("scraped_at") or "")
        match = DATE_RE.search(text)
        if match:
            found.append(match.group(1))
    return found
