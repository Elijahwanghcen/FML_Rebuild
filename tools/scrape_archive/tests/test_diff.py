"""Diff cases the archive has to get right: rename, reappear, carry-forward, price."""
import unittest

from tools.scrape_archive.diff import apply_run
from tools.scrape_archive.normalize import classify


def run(master, rows, day, **kwargs):
    records, failures = classify(rows)
    return apply_run(master, records, day, failure_only=failures, **kwargs)


def row(**overrides):
    base = {
        "property_name": "Alpha House",
        "address": "1 Guadalupe St",
        "unit_or_floorplan_label": "A1",
        "beds": "1",
        "baths": "1",
        "sqft": "500",
        "base_rent": "1000",
        "price_basis": "base",
        "availability": "Available — term: Fall 2026: Full Term (08/2026 - 07/2027)",
        "price_status": "listed",
        "layout_image_url": "https://cdn.example/a1.png",
    }
    base.update(overrides)
    return base


class DiffTest(unittest.TestCase):
    def test_price_change_updates_master_and_keeps_unchanged_sibling(self):
        master = {}
        run(master, [row(), row(unit_or_floorplan_label="A2", base_rent="800", sqft="420")], "2026-08-01")
        result = run(master, [
            row(base_rent="1200"),
            row(unit_or_floorplan_label="A2", base_rent="800", sqft="420"),
        ], "2026-08-08")

        price_changes = [change for change in result["changes"] if change["field"] == "base_rent"]
        self.assertEqual(len(price_changes), 1)
        self.assertEqual(price_changes[0]["old_value"], "1000")
        self.assertEqual(price_changes[0]["new_value"], "1200")
        self.assertEqual(price_changes[0]["change_type"], "changed")

        changed = master["alpha-house__a1"]
        sibling = master["alpha-house__a2"]
        self.assertEqual(changed["base_rent"], "1200")
        self.assertEqual(changed["last_changed"], "2026-08-08")
        self.assertEqual(changed["first_seen"], "2026-08-01")
        self.assertEqual(sibling["base_rent"], "800")
        self.assertEqual(sibling["last_seen"], "2026-08-08")
        self.assertEqual(sibling["last_changed"], "2026-08-01")
        self.assertEqual(result["counts"]["unchanged"], 1)

        # 1200.0 is the same price the master already holds.
        again = run(master, [
            row(base_rent="1200.0"),
            row(unit_or_floorplan_label="A2", base_rent="800.0", sqft="420"),
        ], "2026-08-15")
        self.assertEqual(again["changes"], [])
        self.assertEqual(master["alpha-house__a1"]["last_changed"], "2026-08-08")
        self.assertEqual(master["alpha-house__a1"]["last_seen"], "2026-08-15")

    def test_rename_is_not_an_add_and_a_removal(self):
        master = {}
        run(master, [row()], "2026-08-01")
        original_key = "alpha-house__a1"
        result = run(master, [row(unit_or_floorplan_label="A1 Deluxe")], "2026-08-08")

        kinds = [change["change_type"] for change in result["changes"]]
        self.assertEqual(kinds, ["renamed"])
        self.assertEqual(result["changes"][0]["old_value"], "A1")
        self.assertEqual(result["changes"][0]["new_value"], "A1 Deluxe")
        self.assertEqual(len(master), 1)
        listing = master[original_key]
        self.assertEqual(listing["label"], "A1 Deluxe")
        self.assertEqual(listing["previous_label"], "A1")
        self.assertEqual(listing["first_seen"], "2026-08-01")
        self.assertEqual(listing["last_seen"], "2026-08-08")
        self.assertEqual(listing["base_rent"], "1000")
        self.assertNotIn("alpha-house__a1 deluxe", master)

    def test_rename_requires_a_full_unique_signature(self):
        master = {}
        run(master, [row(sqft="")], "2026-08-01")
        result = run(master, [row(unit_or_floorplan_label="A1 Deluxe", sqft="")], "2026-08-08")
        kinds = sorted(change["change_type"] for change in result["changes"])
        self.assertEqual(kinds, ["added", "no_longer_advertised"])

    def test_reappear_after_leaving_the_advertised_set(self):
        master = {}
        run(master, [row(), row(
            unit_or_floorplan_label="B1", beds="2", baths="2", sqft="900", base_rent="2000",
        )], "2026-08-01")
        gone = run(master, [row(
            unit_or_floorplan_label="B1", beds="2", baths="2", sqft="900", base_rent="2000",
        )], "2026-08-08")
        self.assertEqual(
            [change["change_type"] for change in gone["changes"]],
            ["no_longer_advertised"],
        )
        hidden = master["alpha-house__a1"]
        self.assertEqual(hidden["advertised"], "no")
        self.assertEqual(hidden["removed_at"], "2026-08-08")
        self.assertEqual(hidden["base_rent"], "1000")
        self.assertEqual(hidden["last_seen"], "2026-08-01")

        back = run(master, [row(base_rent="1100"), row(
            unit_or_floorplan_label="B1", beds="2", baths="2", sqft="900", base_rent="2000",
        )], "2026-08-15")
        kinds = [(change["change_type"], change["field"]) for change in back["changes"]]
        self.assertIn(("reappeared", ""), kinds)
        self.assertIn(("changed", "base_rent"), kinds)
        self.assertEqual(master["alpha-house__a1"]["advertised"], "yes")
        self.assertEqual(master["alpha-house__a1"]["removed_at"], "")
        self.assertEqual(master["alpha-house__a1"]["base_rent"], "1100")
        self.assertEqual(master["alpha-house__a1"]["first_seen"], "2026-08-01")
        self.assertEqual(master["alpha-house__b1"]["advertised"], "yes")

    def test_partial_scrape_carries_untouched_property_forward(self):
        master = {}
        run(master, [
            row(),
            row(property_name="Beta Court", unit_or_floorplan_label="C1", base_rent="700", sqft="300"),
        ], "2026-08-01")
        result = run(master, [row(base_rent="1300")], "2026-08-08", full=False)

        beta = master["beta-court__c1"]
        self.assertEqual(beta["advertised"], "yes")
        self.assertEqual(beta["base_rent"], "700")
        self.assertEqual(beta["last_seen"], "2026-08-01")
        self.assertEqual(beta["last_changed"], "2026-08-01")
        self.assertEqual(beta["first_seen"], "2026-08-01")
        self.assertFalse(any(change["property_key"] == "beta-court" for change in result["changes"]))
        self.assertEqual(result["counts"]["carried_forward_listings"], 1)
        self.assertEqual(master["alpha-house__a1"]["base_rent"], "1300")
        self.assertEqual(result["counts"]["no_longer_advertised"], 0)

    def test_full_snapshot_marks_a_missing_property_not_advertised(self):
        master = {}
        run(master, [
            row(),
            row(property_name="Beta Court", unit_or_floorplan_label="C1", base_rent="700", sqft="300"),
        ], "2026-08-01", full=True)
        result = run(master, [row()], "2026-08-08", full=True)
        self.assertEqual(master["beta-court__c1"]["advertised"], "no")
        self.assertEqual(master["beta-court__c1"]["removed_at"], "2026-08-08")
        self.assertEqual(result["counts"]["no_longer_advertised"], 1)
        self.assertEqual(result["counts"]["carried_forward_listings"], 0)

    def test_extraction_failure_does_not_wipe_listings(self):
        master = {}
        run(master, [row()], "2026-08-01", full=True)
        failed = run(master, [{
            "property_name": "Alpha House",
            "unit_or_floorplan_label": "(extraction failed)",
            "availability": "extractor status: no rows",
            "price_status": "not_publicly_listed",
        }], "2026-08-08", full=True)
        listing = master["alpha-house__a1"]
        self.assertEqual(listing["advertised"], "yes")
        self.assertEqual(listing["base_rent"], "1000")
        self.assertEqual(listing["last_seen"], "2026-08-01")
        self.assertEqual(failed["changes"], [])
        self.assertEqual(failed["counts"]["properties_failed"], 1)

    def test_exact_duplicate_rows_are_one_listing(self):
        master = {}
        result = run(master, [row(), row(), row()], "2026-08-01")
        self.assertEqual(len(master), 1)
        self.assertEqual(result["counts"]["added"], 1)

    def test_image_and_lease_term_changes(self):
        master = {}
        run(master, [row()], "2026-08-01")
        result = run(master, [row(
            layout_image_url="https://cdn.example/a1-v2.png",
            availability="Available — term: Fall 2027: Full Term (08/2027 - 07/2028)",
        )], "2026-08-08")
        fields = {change["field"]: (change["old_value"], change["new_value"]) for change in result["changes"]}
        self.assertEqual(fields["layout_image_url"], (
            "https://cdn.example/a1.png", "https://cdn.example/a1-v2.png",
        ))
        self.assertEqual(fields["lease_term"][0], "Fall 2026: Full Term (08/2026 - 07/2027)")
        self.assertEqual(fields["lease_term"][1], "Fall 2027: Full Term (08/2027 - 07/2028)")
        self.assertIn("availability", fields)


if __name__ == "__main__":
    unittest.main()
