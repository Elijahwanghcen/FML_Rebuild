"""Archive layout, upload plan, and the two scrape shapes the backfill reads."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.scrape_archive.archive import ingest
from tools.scrape_archive.normalize import classify, read_rows


def _csv(path: Path, rows: list[dict]) -> None:
    fieldnames = [
        "property_name", "address", "unit_or_floorplan_label", "beds", "baths", "sqft",
        "base_rent", "total_price_with_mandatory_fees", "price_basis", "concessions_raw",
        "concessions_type", "concessions_value", "availability", "layout_image_url",
        "price_image_url", "concessions_image_url", "source_url", "source_type",
        "price_status", "scraped_at",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class ArchiveTest(unittest.TestCase):
    def test_ingest_writes_layout_and_skips_the_same_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "advertised_prices_2026-08-01.csv"
            second = root / "advertised_prices_2026-08-08.csv"
            base = {
                "property_name": "Alpha House",
                "unit_or_floorplan_label": "A1",
                "beds": "1", "baths": "1", "sqft": "500",
                "base_rent": "1000", "price_status": "listed",
                "availability": "Available",
                "scraped_at": "2026-08-01T00:00:00+00:00",
            }
            _csv(first, [base])
            _csv(second, [{**base, "base_rent": "1100", "scraped_at": "2026-08-08T00:00:00+00:00"}])
            out = root / "archive"
            first_result = ingest("ut-austin", first, out, scraper_commit="abc123")
            self.assertFalse(first_result["skipped"])
            snapshot = Path(first_result["snapshot_dir"])
            self.assertTrue((snapshot / "manifest.json").is_file())
            self.assertTrue((snapshot / first.name).is_file())
            manifest = json.loads((snapshot / "manifest.json").read_text())
            self.assertEqual(manifest["scraper_commit"], "abc123")
            self.assertEqual(manifest["sources"][0]["sha256"], first_result["source_sha256"])
            self.assertEqual(manifest["sources"][0]["rows"], 1)
            self.assertTrue((out / "ut-austin" / "changes" / "2026-08-01_changes.md").is_file())
            self.assertTrue((out / "ut-austin" / "changes" / "2026-08-01_changes.json").is_file())
            self.assertTrue((out / "ut-austin" / "master" / "master_2026-08-01.csv").is_file())

            again = ingest("ut-austin", first, out)
            self.assertTrue(again["skipped"])

            second_result = ingest("ut-austin", second, out)
            self.assertEqual(second_result["counts"]["field_changes"], 1)
            with (out / "ut-austin" / "changes_log.csv").open(newline="", encoding="utf-8") as handle:
                log_rows = list(csv.DictReader(handle))
            self.assertEqual(len(log_rows), 2)  # the add, then the price change
            self.assertEqual(log_rows[-1]["field"], "base_rent")
            self.assertEqual(log_rows[-1]["old_value"], "1000")
            self.assertEqual(log_rows[-1]["new_value"], "1100")

            plan = json.loads((out / "upload_plan.json").read_text())
            self.assertEqual(plan["root_folder_name"], "FML Scrape Archive")
            drives = [item["drive_path"] for item in plan["files"]]
            self.assertIn("ut-austin/master/master_latest.csv", drives)
            self.assertTrue(all("\\" not in item["drive_path"] for item in plan["files"]))
            self.assertNotIn("upload_plan.json", drives)
            self.assertTrue(all(Path(item["local_path"]).is_file() for item in plan["files"]))

    def test_nested_json_and_rebuild_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "advertised_prices_2026-08-06.json"
            nested.write_text(json.dumps([{
                "objectID": "alpha-house",
                "property_name": "Alpha House",
                "address": "1 Guadalupe",
                "source_url": "https://example/floor-plans",
                "source_type": "first_party",
                "scraped_at": "2026-08-06T12:00:00+00:00",
                "units": [{
                    "unit_or_floorplan_label": "A1",
                    "beds": 1, "baths": 1, "sqft": 500, "base_rent": 1000,
                    "availability": "Available — term: Fall 2026: Full Term (08/2026 - 07/2027)",
                    "price_status": "listed",
                }, {
                    "unit_or_floorplan_label": "(extraction failed)",
                    "availability": "extractor status: timeout",
                    "price_status": "not_publicly_listed",
                }],
            }]), encoding="utf-8")
            records, failures = classify(read_rows(nested))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["property_key"], "alpha-house")
            self.assertEqual(records[0]["fields"]["base_rent"], "1000")
            self.assertEqual(records[0]["fields"]["lease_term"], "Fall 2026: Full Term (08/2026 - 07/2027)")
            self.assertEqual(failures, {})

            rebuild = root / "units_2026-11-18.json"
            rebuild.write_text(json.dumps([{
                "objectID": "alpha-house__0",
                "property_objectID": "alpha-house",
                "name": "A1",
                "beds": 1, "baths": 1, "sqft": 500,
                "price_min": 1000, "price_max": 1100, "base_rent": 1000,
                "availability": "Available",
                "rent_basis": "per_bed",
                "adapter": "acc_lightning",
                "source_url": "https://example/floor-plans",
                "scraped_at": "2026-11-18",
            }]), encoding="utf-8")
            buildings = {"alpha-house": {"name": "Alpha House", "address": "1 Guadalupe"}}
            records, _failures = classify(read_rows(rebuild), buildings)
            self.assertEqual(records[0]["property_name"], "Alpha House")
            self.assertEqual(records[0]["property_key"], "alpha-house")
            self.assertEqual(records[0]["fields"]["base_rent"], "1000")
            self.assertEqual(records[0]["fields"]["price_max"], "1100")
            self.assertEqual(records[0]["fields"]["price_min"], "")
            self.assertEqual(records[0]["fields"]["adapter"], "acc_lightning")


if __name__ == "__main__":
    unittest.main()
