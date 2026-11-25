"""Diff one scrape against the cumulative master and update it in place.

A run touches a property only when it contains at least one real listing for
that property (or an explicit empty ``units`` list). Extraction-failed stubs
do not touch the property. Listings of properties the file never touched are
carried forward with the same first_seen, last_seen, and last_changed.

Inside a touched property, listings match on ``{property}__{label}``. A label
that disappeared is paired with a new label only when beds, baths, and sqft
all agree and that signature is unique on both sides — a rename, not an
add plus a removal. A listing that was already marked no-longer-advertised
and comes back is a reappearance.
"""
from __future__ import annotations

from collections import defaultdict

from tools.scrape_archive.schema import CHANGE_TYPES, TRACKED_FIELDS, signature

# Not-advertised rows lose a same-label match to a live row unless the new
# scrape has more rows than live ones (the extra row is the reappearance).
_REAPPEAR_PENALTY = 1_000_000


def _blank(campus: str) -> dict:
    record = {field: "" for field in (
        "listing_key", "campus", "property_key", "property_name", "label",
        "previous_label", "advertised", "first_seen", "last_seen", "last_changed",
        "removed_at", *TRACKED_FIELDS,
    )}
    record["campus"] = campus
    record["advertised"] = "yes"
    return record


def _dedup(records: list[dict]) -> list[dict]:
    """Collapse exact copies. The legacy CSV repeats some floor plans three times."""
    seen = set()
    out = []
    for record in records:
        if record.get("explicit_empty"):
            out.append(record)
            continue
        stamp = (
            record["property_key"],
            record["label_norm"],
            tuple(record["fields"][field] for field in TRACKED_FIELDS),
        )
        if stamp in seen:
            continue
        seen.add(stamp)
        out.append(record)
    return out


def _price(fields: dict) -> float | None:
    raw = fields.get("base_rent") or ""
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _group(rows: list[dict], label_of) -> dict[str, list]:
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[label_of(row)].append(row)
    return grouped


def _assign(olds: list[dict], news: list[dict]) -> list[tuple[dict, dict]]:
    """Pair same-label rows. Live listings win over already-removed ones."""
    scored = []
    for i, old in enumerate(olds):
        for j, new in enumerate(news):
            score = 0.0
            old_price, new_price = _price(old), _price(new["fields"])
            if old_price is not None and new_price is not None:
                score += abs(old_price - new_price)
            elif (old_price is None) != (new_price is None):
                score += 10_000
            old_sig, new_sig = signature(old), signature(new["fields"])
            if old_sig and new_sig and old_sig != new_sig:
                score += 5_000
            if old.get("advertised") != "yes":
                score += _REAPPEAR_PENALTY
            scored.append((score, i, j))
    scored.sort()
    used_old, used_new = set(), set()
    pairs = []
    for _score, i, j in scored:
        if i in used_old or j in used_new:
            continue
        used_old.add(i)
        used_new.add(j)
        pairs.append((olds[i], news[j]))
    return pairs


def _unique_signatures(rows: list[dict], fields_of) -> dict[tuple, dict]:
    grouped: dict[tuple, list] = defaultdict(list)
    for row in rows:
        sig = signature(fields_of(row))
        if sig is None:
            continue
        grouped[sig].append(row)
    return {sig: group[0] for sig, group in grouped.items() if len(group) == 1}


def _allocate_key(master: dict, property_key: str, label_norm: str) -> str:
    base = f"{property_key}__{label_norm}"
    if base not in master:
        return base
    number = 2
    while f"{base}#{number}" in master:
        number += 1
    return f"{base}#{number}"


def _snapshot(record: dict) -> dict:
    return {
        "property_name": record.get("property_name", ""),
        "property_key": record.get("property_key", ""),
        "listing_key": record.get("listing_key", ""),
        "label": record.get("label", ""),
        "beds": record.get("beds", ""),
        "baths": record.get("baths", ""),
        "sqft": record.get("sqft", ""),
        "base_rent": record.get("base_rent", ""),
        "availability": record.get("availability", ""),
        "price_status": record.get("price_status", ""),
    }


def _change(change_type: str, record: dict, **extra) -> dict:
    row = _snapshot(record)
    row.update({
        "change_type": change_type,
        "field": "",
        "old_value": "",
        "new_value": "",
    })
    row.update(extra)
    return row


def _apply_fields(record: dict, new: dict) -> None:
    record["property_name"] = new["property_name"]
    record["label"] = new["label"]
    for field in TRACKED_FIELDS:
        record[field] = new["fields"][field]


def apply_run(
    master: dict,
    records: list[dict],
    run_date: str,
    *,
    full: bool = False,
    campus: str = "",
    failure_only: dict | None = None,
) -> dict:
    """Update ``master`` (keyed by listing_key) with one scrape.

    ``full=False`` (default): a property that is absent from the file is
    untouched. ``full=True``: a property that is absent — and was not an
    extraction failure — has its advertised listings marked no longer
    advertised. Failure-only properties are carried forward in both modes.
    """
    failure_only = failure_only or {}
    incoming = _dedup([record for record in records if not record.get("explicit_empty")])
    explicit_empty = {record["property_key"] for record in records if record.get("explicit_empty")}

    by_property: dict[str, list] = defaultdict(list)
    names: dict[str, str] = {}
    for record in incoming:
        by_property[record["property_key"]].append(record)
        names[record["property_key"]] = record["property_name"]
    for key in explicit_empty:
        names.setdefault(key, key)
    touched = set(by_property) | explicit_empty

    master_by_property: dict[str, list] = defaultdict(list)
    for record in master.values():
        master_by_property[record["property_key"]].append(record)

    changes: list[dict] = []
    buildings: dict[str, dict] = {}

    def building(property_key: str, property_name: str) -> dict:
        slot = buildings.get(property_key)
        if slot is None:
            slot = {
                "property_key": property_key,
                "property_name": property_name,
                "added": 0,
                "no_longer_advertised": 0,
                "reappeared": 0,
                "renamed": 0,
                "field_changes": 0,
                "unchanged": 0,
            }
            buildings[property_key] = slot
        return slot

    carried_listings = 0
    carried_properties = 0
    for property_key, olds in master_by_property.items():
        if property_key in touched or property_key in failure_only:
            continue
        if full:
            for old in olds:
                if old.get("advertised") != "yes":
                    continue
                old["advertised"] = "no"
                old["removed_at"] = run_date
                old["last_changed"] = run_date
                changes.append(_change(
                    "no_longer_advertised", old,
                    new_value="no_longer_advertised",
                ))
                building(property_key, old.get("property_name") or property_key)["no_longer_advertised"] += 1
        else:
            carried_properties += 1
            carried_listings += sum(1 for old in olds if old.get("advertised") == "yes")

    # Failure-only properties were attempted and failed. Keep last real values.
    for property_key in failure_only:
        if property_key in touched:
            continue
        olds = master_by_property.get(property_key, [])
        if olds:
            carried_properties += 1
            carried_listings += sum(1 for old in olds if old.get("advertised") == "yes")

    unchanged = 0
    for property_key in touched:
        news = by_property.get(property_key, [])
        olds = list(master_by_property.get(property_key, []))
        property_name = names.get(property_key) or (olds[0]["property_name"] if olds else property_key)
        slot = building(property_key, property_name)

        old_by_label = _group(olds, lambda row: row["label"].casefold())
        new_by_label = _group(news, lambda row: row["label_norm"])
        matched_old = set()
        matched_new = set()

        for label in set(old_by_label) & set(new_by_label):
            pairs = _assign(old_by_label[label], new_by_label[label])
            paired_old = {id(old) for old, _new in pairs}
            paired_new = {id(new) for _old, new in pairs}
            for old, new in pairs:
                matched_old.add(id(old))
                matched_new.add(id(new))
                _observe(old, new, run_date, changes, slot, renamed=False)
            # Leftover copies of a label that still exists are adds/removes,
            # not renames: the label did not change, the count did.
            for old in old_by_label[label]:
                if id(old) not in paired_old:
                    matched_old.add(id(old))  # keep them out of the rename pool
                    if old.get("advertised") == "yes":
                        _remove(old, run_date, changes, slot)
            for new in new_by_label[label]:
                if id(new) not in paired_new:
                    matched_new.add(id(new))
                    _add(master, new, run_date, campus, changes, slot)

        rename_olds = [
            old for old in olds
            if id(old) not in matched_old and old["label"].casefold() not in new_by_label
        ]
        rename_news = [
            new for new in news
            if id(new) not in matched_new and new["label_norm"] not in old_by_label
        ]
        old_sigs = _unique_signatures(rename_olds, lambda row: row)
        new_sigs = _unique_signatures(rename_news, lambda row: row["fields"])
        for sig, new in new_sigs.items():
            old = old_sigs.get(sig)
            if old is None:
                continue
            matched_old.add(id(old))
            matched_new.add(id(new))
            _observe(old, new, run_date, changes, slot, renamed=True)

        for new in rename_news:
            if id(new) in matched_new:
                continue
            _add(master, new, run_date, campus, changes, slot)
        for old in rename_olds:
            if id(old) in matched_old:
                continue
            if old.get("advertised") == "yes":
                _remove(old, run_date, changes, slot)

        unchanged += slot["unchanged"]

    advertised = sum(1 for row in master.values() if row.get("advertised") == "yes")
    counts = {
        "input_rows": len(records),
        "deduped_rows": len(incoming),
        "properties_touched": len(touched),
        "properties_failed": len([key for key in failure_only if key not in touched]),
        "properties_carried_forward": carried_properties,
        "carried_forward_listings": carried_listings,
        "added": sum(slot["added"] for slot in buildings.values()),
        "no_longer_advertised": sum(slot["no_longer_advertised"] for slot in buildings.values()),
        "reappeared": sum(slot["reappeared"] for slot in buildings.values()),
        "renamed": sum(slot["renamed"] for slot in buildings.values()),
        "field_changes": sum(slot["field_changes"] for slot in buildings.values()),
        "listings_with_field_changes": len({
            change["listing_key"] for change in changes if change["change_type"] == "changed"
        }),
        "unchanged": unchanged,
        "master_listings": len(master),
        "master_advertised": advertised,
    }
    by_building = sorted(buildings.values(), key=lambda slot: (slot["property_name"].lower(), slot["property_key"]))
    order = {name: index for index, name in enumerate(CHANGE_TYPES)}
    changes.sort(key=lambda change: (
        change.get("property_name", "").lower(),
        change.get("label", "").lower(),
        order.get(change["change_type"], 99),
        change.get("field", ""),
    ))
    return {"changes": changes, "counts": counts, "by_building": by_building}


def _observe(old: dict, new: dict, run_date: str, changes: list, slot: dict, *, renamed: bool) -> None:
    was_advertised = old.get("advertised") == "yes"
    field_diffs = [
        (field, old.get(field, ""), new["fields"][field])
        for field in TRACKED_FIELDS
        if old.get(field, "") != new["fields"][field]
    ]
    if not was_advertised:
        changes.append(_change("reappeared", old, label=new["label"], new_value=new["label"]))
        slot["reappeared"] += 1
        old["advertised"] = "yes"
        old["removed_at"] = ""
    if renamed and old.get("label", "").casefold() != new["label_norm"]:
        changes.append(_change(
            "renamed", old,
            label=new["label"],
            field="unit_or_floorplan_label",
            old_value=old.get("label", ""),
            new_value=new["label"],
        ))
        slot["renamed"] += 1
        old["previous_label"] = old.get("label", "")
    for field, before, after in field_diffs:
        changes.append(_change(
            "changed", old,
            label=new["label"],
            field=field,
            old_value=before,
            new_value=after,
            beds=new["fields"]["beds"],
            baths=new["fields"]["baths"],
            sqft=new["fields"]["sqft"],
            base_rent=new["fields"]["base_rent"],
            availability=new["fields"]["availability"],
            price_status=new["fields"]["price_status"],
        ))
        slot["field_changes"] += 1
    _apply_fields(old, new)
    old["last_seen"] = run_date
    if field_diffs or renamed or not was_advertised:
        old["last_changed"] = run_date
    else:
        slot["unchanged"] += 1


def _add(master: dict, new: dict, run_date: str, campus: str, changes: list, slot: dict) -> None:
    key = _allocate_key(master, new["property_key"], new["label_norm"])
    record = _blank(campus)
    record["listing_key"] = key
    record["property_key"] = new["property_key"]
    record["first_seen"] = run_date
    record["last_seen"] = run_date
    record["last_changed"] = run_date
    record["advertised"] = "yes"
    _apply_fields(record, new)
    master[key] = record
    changes.append(_change(
        "added", record,
        new_value=record["base_rent"],
    ))
    slot["added"] += 1


def _remove(old: dict, run_date: str, changes: list, slot: dict) -> None:
    if old.get("advertised") != "yes":
        return
    old["advertised"] = "no"
    old["removed_at"] = run_date
    old["last_changed"] = run_date
    changes.append(_change("no_longer_advertised", old, new_value="no_longer_advertised"))
    slot["no_longer_advertised"] += 1
