#!/usr/bin/env python3
"""Offline checks for the Phase 0 groundwork. No network."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from enrich_listings import take_llm_if_better
from legacy_emit import FIELDS, property_record, slugify, unit_object_ids
from listing_post import apply_row_policy, clean_dedupe_rows, keep_row, saved_html_banned
from miss_causes import classify, rule
from pinned_sources import merge_detected, merge_listing_config, pin_from_property
from rescue_prices import map_prices, units_from_rescue


def test_fields_order():
    assert FIELDS[0] == "property_name" and FIELDS[-1] == "scraped_at"
    assert FIELDS.index("price_status") == 18
    assert FIELDS.index("source_type") == 17
    assert len(FIELDS) == 20


def test_clean_labels_merges_icon_dupes():
    rows = [
        {"unit_or_floorplan_label": "A1 1 Bed, Call for Pricing", "beds": "", "baths": "", "layout_image_url": ""},
        {"unit_or_floorplan_label": "A1", "beds": "1", "baths": "1", "layout_image_url": "http://img/a1.png"},
    ]
    out = clean_dedupe_rows(rows)
    assert len(out) == 1
    assert out[0]["unit_or_floorplan_label"] == "A1"
    assert out[0]["beds"] == "1"
    assert out[0]["layout_image_url"] == "http://img/a1.png"


def test_placeholder_kept_and_failure_stub():
    assert keep_row({"unit_or_floorplan_label": "(no public pricing on site)", "price_status": "not_publicly_listed"})
    assert not keep_row({"unit_or_floorplan_label": "(junk)", "price_status": "listed"})
    rows, ok = apply_row_policy([], {}, "ok")
    assert ok is False
    assert rows[0]["unit_or_floorplan_label"] == "(extraction failed)"
    assert "no rows" in rows[0]["availability"]
    kept, ok = apply_row_policy(
        [{"unit_or_floorplan_label": "(no public pricing on site)", "price_status": "not_publicly_listed",
          "availability": "site publishes no floor-plan pricing"}],
        {}, "ok")
    assert ok is True
    assert kept[0]["availability"].startswith("site publishes")


def test_saved_html_banned():
    assert saved_html_banned({"backend": "text_plan_list", "params": {}})
    assert saved_html_banned({"backend": "rentcafe_inline", "params": {"html_files": ["/tmp/x.html"]}})
    assert not saved_html_banned({"backend": "acc_lightning", "params": {"list_id": 1}})


def test_llm_does_not_keep_the_losing_adapter():
    rows, src, adapter, chosen = take_llm_if_better(
        [{"price_min": 1}], "first_party_site", "text_plan_list",
        {"backend": "text_plan_list", "url": "u", "params": {}},
        [{"price_min": 1}, {"price_min": 2}],
    )
    assert adapter == "llm_page_read"
    assert chosen is None
    assert len(rows) == 2
    rows, src, adapter, chosen = take_llm_if_better(
        [{"price_min": 1}, {"price_min": 2}], "first_party_site", "acc_lightning",
        {"backend": "acc_lightning"}, [{"price_min": None}],
    )
    assert adapter == "acc_lightning"
    assert chosen["backend"] == "acc_lightning"


def test_locked_pin_survives_detection():
    backends = {"acc_lightning": {"type": "http"}}
    existing = [{
        "objectID": "crest-at-pearl", "property_name": "Crest at Pearl", "locked": True,
        "backend": "acc_lightning", "url": "https://example/crest", "params": {"list_id": 675},
        "source_id": "src_10", "building_type": "student_housing",
    }]
    detected = [{
        "objectID": "crest-at-pearl", "property_name": "Crest at Pearl",
        "backend": "text_plan_list", "url": "https://example/other", "params": {"html_files": ["x"]},
        "source_id": "src_new", "building_type": "apartment",
    }, {
        "objectID": "brand-new", "property_name": "Brand New Hall",
        "backend": "sightmap", "url": "https://example/new", "params": {},
        "source_id": "src_z", "building_type": "apartment",
    }]
    merged = merge_detected(existing, detected)
    by = {p["objectID"]: p for p in merged}
    assert by["crest-at-pearl"]["url"] == "https://example/crest"
    assert by["crest-at-pearl"]["params"] == {"list_id": 675}
    assert by["crest-at-pearl"]["locked"] is True
    assert "brand-new" in by
    assert all(p["backend"] != "text_plan_list" for p in merged)


def test_import_keeps_fml_params():
    backends = {"entrata_pp": {"type": "dom"}, "wp_entrata_json": {"type": "http"}}
    fml = [{
        "property_name": "Torre", "address": "Austin", "source_id": "b3_18",
        "backend": "wp_entrata_json", "url": "https://torreatx.com/floor-plans/",
        "params": {"api_url": "https://torreatx.com/wp-json/gmh-student/floorplans/categories"},
    }]
    existing = [{"objectID": "torre", "property_name": "Torre", "backend": "wp_entrata_json",
                 "params": {"api_url": "x", "force_not_listed": True}, "url": "https://old",
                 "building_type": "student_housing", "source_id": "old"}]
    merged, added = merge_listing_config(existing, fml, backends)
    assert merged[0]["locked"] is True
    assert "force_not_listed" not in merged[0]["params"]
    assert merged[0]["params"]["api_url"].endswith("categories")
    assert merged[0]["objectID"] == "torre"
    assert added == []


def test_legacy_record_and_unit_id():
    prop = {"property_name": "Crest at Pearl", "address": "1 Pearl", "url": "https://example/crest",
            "source_type": "first_party"}
    rows = [{
        "unit_or_floorplan_label": "2 Bed - 2 Bath G", "beds": "2", "baths": "2", "sqft": "900",
        "base_rent": "1424", "total_price_with_mandatory_fees": "", "price_basis": "base",
        "concessions_raw": "", "concessions_type": "", "concessions_value": "",
        "availability": "Available", "layout_image_url": "http://img", "price_image_url": "",
        "concessions_image_url": "", "price_status": "listed",
    }]
    rec, flat = property_record(prop, rows, "2026-11-25T18:00:00+00:00", 1764028800)
    assert rec["objectID"] == slugify("Crest at Pearl") == "crest-at-pearl"
    assert rec["source_type"] == "first_party"
    assert rec["units"][0]["price_status"] == "listed"
    assert rec["units"][0]["base_rent"] == 1424
    assert list(flat[0]) == FIELDS
    ids = unit_object_ids(rec["objectID"], rec["units"])
    assert ids[0]["objectID"] == "crest-at-pearl__2-bed-2-bath-g-900"


def test_rescue_modes():
    base, total, basis, status, raw, ctype, cval = map_prices(
        "promo_current", {"base": 1949, "total": 1849, "starting": None, "rent": None}, None)
    assert status == "listed" and base == 1849 and total is None and ctype == "flat_discount"
    assert "was $1,949" in raw
    base, total, basis, status, raw, ctype, cval = map_prices(
        "split_total", {"base": 1000, "total": 1150, "starting": None, "rent": None}, None)
    assert basis == "total" and base == 1000 and total == 1150 and status == "listed"
    rows = units_from_rescue({"mode": "empty"})
    assert rows[0]["price_status"] == "not_publicly_listed"
    assert rows[0]["unit_or_floorplan_label"].startswith("(")


def test_causes_cover_the_known_holes():
    assert classify({"backend": "uptown_realty", "url": "https://uptownrealtyaustin.com/communities/x/", "property_name": "X"}) == "condo_unit_landlord"
    assert classify({"backend": "villas_wp", "url": "https://www.villasonguadalupe.com/floor-plans/", "property_name": "Villas on Guadalupe"}) == "leaseleads_markup"
    assert classify({"backend": "entrata_pp", "url": "https://www.quartersoncampus.com/austin/grayson/student/", "property_name": "Quarters on Campus – Grayson"}) == "entrata_bot_wall"
    assert classify({"backend": "no_public_pricing", "url": "https://example", "property_name": "Town Lake", "params": {"reason": "x"}}) == "layouts_only"
    assert classify({"backend": "yugo", "url": "https://yugo.com/x", "property_name": "Yugo Austin Rio", "params": {"gtm_name": "Yugo Austin Rio"}}) == "per_room_type"
    assert classify({"backend": "collegehouses_rates", "url": "https://collegehouses.org/laurel/", "property_name": "Laurel House Co-op", "params": {"house": "Laurel"}}) == "university_or_coop_table"
    for cause in ("condo_unit_landlord", "leaseleads_markup", "entrata_bot_wall", "layouts_only", "ranked_below_cut"):
        assert rule(cause)


def test_emit_roundtrip_types():
    prop = {"property_name": "Icon at Austin", "address": "A", "url": "https://icon", "source_type": "first_party",
            "backend": "entrata_pp", "params": {"clean_labels": True}}
    rows, ok = apply_row_policy([
        {"unit_or_floorplan_label": "S1 Studio, Call for Pricing", "beds": "", "baths": "", "base_rent": "",
         "price_status": "not_publicly_listed", "price_basis": ""},
        {"unit_or_floorplan_label": "S1", "beds": "0", "baths": "1", "base_rent": "",
         "price_status": "not_publicly_listed", "price_basis": "", "layout_image_url": "http://i"},
    ], prop["params"], "ok")
    assert ok and len(rows) == 1
    assert rows[0]["beds"] == 0
    assert rows[0]["layout_image_url"] == "http://i"
    rec, flat = property_record(prop, rows, "2026-11-25T00:00:00+00:00", 1)
    assert flat[0]["source_type"] == "first_party"
    assert flat[0]["price_status"] == "not_publicly_listed"
    with tempfile.TemporaryDirectory() as d:
        from legacy_emit import write_legacy
        paths = write_legacy([rec], flat, [], d, "2026-11-25")
        text = Path(paths["csv"]).read_text().splitlines()[0]
        assert text.split(",") == FIELDS


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print("ok", t.__name__)
        except Exception as e:
            failed += 1
            print("FAIL", t.__name__, e)
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
