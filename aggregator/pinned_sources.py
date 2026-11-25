"""Locked listing pins imported from FML_Data properties_config.json.

A locked pin keeps its backend, url, params and source_type. write_listing_config
merges: detection may add a building, and may not replace a locked source.
ADD / added_buildings.json insert buildings the rank cut never kept.
"""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FML_CONFIG = ROOT / "reference" / "legacy_ut_scraper" / "properties_config.json"


def slugify(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# FML_Data display name -> a Rebuild roster/listing name for the same building.
# Used only to avoid a second row. Town Lake's three FML names stay separate.
ROSTER_ALIAS = {
    "The Block on 25th East": "The Block on 25 East",
    "The Block on 25th West": "The Block on 25 West",
    "Quarters on Campus – Grayson": "The Quarters Grayson House",
    "Quarters on Campus – Nueces": "The Quarters Nueces House",
    "Quarters on Campus – Karnes House": "The Quarters Karnes House",
    "Quarters on Campus – Sterling House": "The Quarters Sterling House",
    "1883 at Cameron House": "1883 at Cameron",
    "1883 at Montgomery House": "1883 at Montgomery",
    "21 Rio": "21 Rio Apartments",
    "2400 Nueces": "2400 Nueces Apartments",
    "San Gabriel Square": "San Gabriel Square Apartments",
    "Buena Vista Condominiums": "Buena Vista Condo",
    "Texan Shoal Creek Condominiums": "Texan Shoal Creek",
    "Piazza Navona Condominiums": "Piazza Navona Condos",
    "Orange Tree Condominiums": "Orange Tree Condos",
    "Texan Tower": "Texan Tower Condos",
    "The Standard": "The Standard at Austin",
    "Rambler Apartments": "Rambler Austin",
    "Sabina Condominiums": "Sabina",
    "Vanderbilt Condominiums": "Vanderbilt Condos",
    "Waterford Condominiums": "Waterford Condos",
    "Centennial Condos": "Centennial",
    "Croix Condominiums": "Croix",
    "Parapet Condominiums": "Parapet",
}


def norm_key(name):
    """Identity key for pins. Drops only 'the' / city noise so Town Lake Condos and
    Town Lake Apartments stay different buildings."""
    s = (name or "").lower().replace("&", " and ").replace("–", " ").replace("—", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    drop = {"the", "austin", "tx"}
    return " ".join(t for t in s.split() if t not in drop)


def load_fml(path=None):
    data = json.loads(Path(path or FML_CONFIG).read_text())
    return data["backends"], data["properties"]


def building_type_for(prop):
    b = prop.get("backend") or ""
    if b in ("acc_lightning", "entrata_pp", "yugo", "ion_wp", "gogetter_wc_floorplans"):
        return "student_housing"
    if b in ("collegehouses_rates",):
        return "co_op"
    if b in ("ut_housing_nueces", "ut_housing_dobie", "ut_rates_table"):
        return "dorm"
    if "condo" in (prop.get("property_name") or "").lower():
        return "condo"
    return "apartment"


def pin_from_property(prop, backends, object_id=None):
    params = prop.get("params") or {}
    return {
        "objectID": object_id or slugify(prop["property_name"]),
        "property_name": prop["property_name"],
        "address": prop.get("address") or "",
        "building_type": building_type_for(prop),
        "source_id": prop["source_id"],
        "backend": prop["backend"],
        "extractor_type": backends[prop["backend"]]["type"],
        "url": prop["url"],
        "params": params,
        "source_type": prop.get("source_type") or "first_party",
        "locked": True,
        "locked_from": "fml_data_properties_config",
    }


def roster_names(buildings):
    keys = {}
    for b in buildings:
        keys[norm_key(b.get("canonical_name") or b.get("property_name") or "")] = b
        for a in b.get("aliases") or []:
            keys.setdefault(norm_key(a), b)
    return keys


def merge_listing_config(existing_props, fml_props, backends):
    """Return (merged_properties, added_pins). Locked fields on a matched row are replaced by the pin.

    Unmatched existing rows stay, unlocked. A later detection pass must not overwrite locked rows;
    see merge_detected().
    """
    by_key = {}
    order = []
    for p in existing_props:
        k = norm_key(p.get("property_name"))
        if k not in by_key:
            order.append(k)
        by_key[k] = dict(p)
    added = []
    for prop in fml_props:
        k = norm_key(prop["property_name"])
        alias = ROSTER_ALIAS.get(prop["property_name"])
        prev = by_key.get(k) or (by_key.get(norm_key(alias)) if alias else None)
        if prev and k not in by_key:
            k = norm_key(alias)
        oid = prev.get("objectID") if prev else None
        pin = pin_from_property(prop, backends, oid)
        if prev:
            pin["building_type"] = prev.get("building_type") or pin["building_type"]
            pin["objectID"] = prev.get("objectID") or pin["objectID"]
        else:
            order.append(k)
            added.append(pin)
        by_key[k] = pin
    return [by_key[k] for k in order], added


def merge_detected(existing_props, detected_props):
    """Keep every locked row. Detection may add or replace only unlocked rows."""
    locked = [dict(p) for p in existing_props if p.get("locked")]
    locked_keys = {norm_key(p.get("property_name")) for p in locked}
    locked_ids = {p.get("objectID") for p in locked}
    rest = []
    for p in detected_props:
        if p.get("objectID") in locked_ids or norm_key(p.get("property_name")) in locked_keys:
            continue
        if p.get("backend") in ("llm_page_read", "text_plan_list"):
            continue
        if (p.get("params") or {}).get("html_files"):
            continue
        rest.append(p)
    # unlocked existing rows that detection did not see again are dropped on purpose:
    # the build rewrites the unlocked set. Locked rows always remain.
    return locked + rest


def added_building_record(pin, cause, campus_center):
    return {
        "canonical_name": pin["property_name"],
        "aliases": [],
        "address": pin.get("address") or "",
        "website": pin.get("url"),
        "website_locked": True,
        "floorplans_url": pin.get("url"),
        "building_type": pin.get("building_type") or "apartment",
        "source_families": ["manual", "fml_pin"],
        "neighborhood": None,
        "pin_lat": campus_center[0],
        "pin_lng": campus_center[1],
        "dist_campus_m": None,
        "rating_count": 0,
        "needs_review": True,
        "resolution_status": "ADD",
        "miss_cause": cause,
        "locked_backend": pin.get("backend"),
        "locked_source_id": pin.get("source_id"),
    }


def missing_from_roster(pins, buildings):
    known = roster_names(buildings)
    missing = []
    for pin in pins:
        alias = ROSTER_ALIAS.get(pin["property_name"])
        if norm_key(pin["property_name"]) in known:
            continue
        if alias and norm_key(alias) in known:
            continue
        missing.append(pin)
    return missing
