"""Shared columns, campus registry, and value canonicalization.

The legacy scraper (FML_Data ``run.py``) writes a 20-column flat file. Rebuild
units use a different shape; both are stored here as one tracked field set so
a later run can be diffed against the master regardless of which scraper
produced it.
"""
from __future__ import annotations

import re

# Flat CSV header written by austin_leases_units/scraper/run.py.
LEGACY_FIELDS = [
    "property_name", "address", "unit_or_floorplan_label", "beds", "baths",
    "sqft", "base_rent", "total_price_with_mandatory_fees", "price_basis",
    "concessions_raw", "concessions_type", "concessions_value", "availability",
    "layout_image_url", "price_image_url", "concessions_image_url",
    "source_url", "source_type", "price_status", "scraped_at",
]

# Compared on every matched listing. Label is identity, not a tracked field:
# a label change is a rename, reported on its own.
TRACKED_FIELDS = [
    "address",
    "beds", "baths", "sqft",
    "base_rent", "total_price_with_mandatory_fees", "price_basis",
    "concessions_raw", "concessions_type", "concessions_value",
    "availability", "lease_term",
    "layout_image_url", "price_image_url", "concessions_image_url",
    "source_url", "source_type", "price_status",
    "rent_basis", "price_min", "price_max", "adapter",
]

META_FIELDS = [
    "listing_key", "campus", "property_key", "property_name", "label",
    "previous_label", "advertised", "first_seen", "last_seen", "last_changed",
    "removed_at",
]

MASTER_COLUMNS = META_FIELDS + TRACKED_FIELDS

CHANGE_COLUMNS = [
    "run_date", "run_id", "campus", "change_type",
    "property_name", "property_key", "listing_key", "label",
    "field", "old_value", "new_value",
    "beds", "baths", "sqft", "base_rent", "availability", "price_status",
]

# Machine change types. Markdown spells no_longer_advertised out in words.
CHANGE_TYPES = (
    "added",
    "reappeared",
    "renamed",
    "changed",
    "no_longer_advertised",
)

DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")

DEFAULT_DRIVE_ROOT = "FML Scrape Archive"

# Known campuses. Any other filesystem-safe slug is accepted so a future
# campus does not require a code change; it just gets its own archive folder.
CAMPUSES = {
    "ut-austin": {
        "name": "University of Texas at Austin",
        "aliases": ["ut", "ut-austin", "ut_austin", "utaustin", "austin"],
        "data_dirs": ["ut_austin"],
        # Path fragments that identify this campus inside an FML_Data checkout.
        "path_tokens": ["austin_leases_units", "ut_austin", "ut-austin"],
    },
    "texas-am": {
        "name": "Texas A&M University",
        "aliases": ["tamu", "texas-am", "texas_am", "a&m", "college-station", "college_station"],
        "data_dirs": ["texas_am"],
        "path_tokens": ["texas_am", "texas-am", "college_station", "college-station", "tamu"],
    },
}


def resolve_campus(raw: str) -> tuple[str, dict]:
    """Return ``(slug, meta)``. Unknown slugs are kept so new campuses work."""
    text = (raw or "").strip().lower().replace("_", "-")
    text = re.sub(r"\s+", "-", text)
    by_alias = {}
    for slug, meta in CAMPUSES.items():
        for alias in [slug, *meta["aliases"]]:
            by_alias[alias.lower().replace("_", "-")] = slug
    if text in by_alias:
        slug = by_alias[text]
        return slug, CAMPUSES[slug]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,48}", text or ""):
        raise ValueError(
            f"campus must be a slug like ut-austin or texas-am, got {raw!r}"
        )
    return text, {
        "name": raw.strip(),
        "aliases": [text],
        "data_dirs": [text.replace("-", "_")],
        "path_tokens": [text, text.replace("-", "_")],
    }


def slug(name: str) -> str:
    """Same folding the legacy runner uses for property objectIDs."""
    folded = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return folded or "unknown"


def canon(value) -> str:
    """Compare values so ``1424``, ``1424.0`` and ``\"1424\"`` are one price."""
    if value is None or isinstance(value, bool):
        return "" if not isinstance(value, bool) else ("true" if value else "false")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        if value.is_integer():
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")
    text = str(value).strip()
    if text.lower() in {"none", "null", "nan"}:
        return ""
    numeric = text.replace(",", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", numeric):
        number = float(numeric)
        if number.is_integer():
            return str(int(number))
        return f"{number:.4f}".rstrip("0").rstrip(".")
    return re.sub(r"\s+", " ", text)


def signature(fields: dict) -> tuple[str, str, str] | None:
    """Beds/baths/sqft identity used only when all three are present.

    A blank sqft matches too many plans (several properties repeat a bed/bath
    pair across floor plans), so rename fallback refuses a partial signature.
    """
    beds, baths, sqft = fields.get("beds", ""), fields.get("baths", ""), fields.get("sqft", "")
    if not (beds and baths and sqft):
        return None
    return (beds, baths, sqft)
