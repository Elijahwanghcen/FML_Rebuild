"""Entrata / headed-rescue price modes from FML_Data ingest_headed_rescues.py.

Modes: split_total, base_only, promo_current, installment, unpriced, empty.
A rescue file is either legacy `{"rows": [...]}` or the plan schema
`{"floor_plans": [...], "mode": "split_total"}`. This module does not scrape
and does not solve a challenge.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reference" / "legacy_ut_scraper" / "extractors"))
import http_extractors as HX  # noqa: E402


def to_num(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return int(f) if f.is_integer() else f
    s = str(value).strip().replace(",", "")
    if not s or s in {"—", "-", "N/A", "n/a"}:
        return None
    if re.fullmatch(r"studio", s, re.I):
        return 0
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def blank(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip() in {"", "—", "-", "–", "n/a", "N/A"}:
        return True
    return False


def clean_text(value):
    if blank(value):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def concession_fields(raw):
    raw = clean_text(raw)
    if not raw:
        return None, None, None
    ctype, cval = HX.parse_concession(raw)
    return raw, (ctype or None), to_num(cval) if cval not in ("", None) else None


def beds_of(value):
    if isinstance(value, str) and re.fullmatch(r"studio", value.strip(), re.I):
        return 0
    return to_num(value)


def offer_prices(obj):
    return {
        "base": to_num(obj.get("base_rent")),
        "total": to_num(obj.get("total_monthly")),
        "starting": to_num(obj.get("starting_rent")),
        "rent": to_num(obj.get("rent")),
    }


def has_price(prices):
    return any(prices[k] is not None for k in ("base", "total", "starting", "rent"))


def priced_variants(plan):
    out, seen = [], set()
    for variant in plan.get("variants") or []:
        prices = offer_prices(variant)
        if not has_price(prices):
            continue
        key = (
            clean_text(variant.get("room_type")),
            prices["base"], prices["total"], prices["starting"], prices["rent"],
            clean_text(variant.get("availability")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(variant)
    return out


def map_prices(mode, prices, specials):
    """Return base, total, price_basis, price_status, concessions_raw, type, value."""
    base, total, starting, rent = prices["base"], prices["total"], prices["starting"], prices["rent"]
    raw, ctype, cval = concession_fields(specials)
    if mode == "unpriced":
        return None, None, None, "not_publicly_listed", raw, ctype, cval
    if mode == "promo_current":
        current = total if total is not None else base
        struck = base if (base is not None and total is not None and base > total) else None
        if current is None:
            return None, None, None, "not_publicly_listed", raw, ctype, cval
        bits = []
        if raw and not re.search(r"struck-through", raw, re.I):
            bits.append(raw)
        if struck is not None:
            shown = f"{struck:,}" if isinstance(struck, int) else f"{struck:,.2f}"
            bits.append(f"was ${shown}")
            diff = struck - current
            ctype = "flat_discount"
            cval = int(diff) if float(diff).is_integer() else diff
            raw = "; ".join(bits) if bits else None
        return current, None, "base", "listed", raw, ctype, cval
    if mode == "installment":
        amount = total if total is not None else (base if base is not None else (rent if rent is not None else starting))
        if amount is None:
            return None, None, None, "not_publicly_listed", raw, ctype, cval
        return amount, None, "base", "listed", raw, ctype, cval
    if mode == "base_only":
        amount = base if base is not None else (starting if starting is not None else (rent if rent is not None else total))
        if amount is None:
            return None, None, None, "not_publicly_listed", raw, ctype, cval
        return amount, None, "base", "listed", raw, ctype, cval
    if total is not None and base is not None:
        return base, total, "total", "listed", raw, ctype, cval
    if total is not None:
        return None, total, "total", "listed", raw, ctype, cval
    amount = base if base is not None else (starting if starting is not None else rent)
    if amount is not None:
        return amount, None, "base", "listed", raw, ctype, cval
    return None, None, None, "not_publicly_listed", raw, ctype, cval


def label_for(name, room):
    name = clean_text(name) or "Floor plan"
    room = clean_text(room)
    if not room or room.lower() in name.lower():
        return name
    return f"{name} ({room})"


def empty_stub():
    return {
        "unit_or_floorplan_label": "(extraction failed)",
        "beds": "", "baths": "", "sqft": "",
        "base_rent": "", "total_price_with_mandatory_fees": "", "price_basis": "",
        "concessions_raw": "", "concessions_type": "", "concessions_value": "",
        "availability": "extractor status: no_rows",
        "layout_image_url": "", "price_image_url": "", "concessions_image_url": "",
        "price_status": "not_publicly_listed",
    }


def row_from(plan, variant, mode, global_specials):
    source = variant or plan
    prices = offer_prices(source if variant is not None else plan)
    name = clean_text(plan.get("floor_plan") or plan.get("name") or plan.get("code"))
    room = clean_text((variant or {}).get("room_type") if variant else None)
    if room is None:
        room = clean_text(plan.get("room_type"))
    specials = None
    for src in (variant, plan):
        if src and clean_text(src.get("specials")):
            specials = clean_text(src.get("specials"))
            break
    if specials is None:
        specials = clean_text(global_specials)
    base, total, basis, status, raw, ctype, cval = map_prices(mode, prices, specials)
    avail = clean_text((variant or {}).get("availability")) or clean_text(plan.get("availability")) or "See site"
    return {
        "unit_or_floorplan_label": label_for(name, room),
        "beds": beds_of(plan.get("beds")) if plan.get("beds") not in (None, "") else "",
        "baths": to_num(plan.get("baths")) if plan.get("baths") not in (None, "") else "",
        "sqft": to_num(plan.get("sqft")) if plan.get("sqft") not in (None, "") else "",
        "base_rent": "" if base is None else base,
        "total_price_with_mandatory_fees": "" if total is None else total,
        "price_basis": basis or "",
        "concessions_raw": raw or "",
        "concessions_type": ctype or "",
        "concessions_value": "" if cval is None else cval,
        "availability": avail,
        "layout_image_url": "",
        "price_image_url": "",
        "concessions_image_url": "",
        "price_status": status,
    }


def units_from_rescue(data, mode=None):
    mode = mode or data.get("mode") or "split_total"
    if mode in ("empty", "marketing"):
        return [empty_stub()]
    if data.get("rows") and not data.get("floor_plans"):
        return data["rows"]
    meta = data.get("metadata") or {}
    plans = data.get("floor_plans") or data.get("plans") or []
    rows = []
    for plan in plans:
        variants = priced_variants(plan)
        if variants:
            for variant in variants:
                rows.append(row_from(plan, variant, mode, meta.get("global_specials")))
        else:
            rows.append(row_from(plan, None, mode, meta.get("global_specials")))
    return rows or [empty_stub()]
