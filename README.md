# FML Rebuild

Campus apartment-listing rebuild for UT Austin, Texas A&M, and later campuses.

## Scrape archive

`tools/scrape_archive/` saves every scrape and catalogues what changed between runs. A run that only refreshes some listings does not drop the rest: the master keeps last-seen values, `first_seen`, `last_seen`, and `last_changed`.

```bash
python3 -m tools.scrape_archive ingest --campus ut-austin --input scrape.csv
python3 -m tools.scrape_archive rebuild-history --campus ut-austin --fml-data /path/to/FML_Data
```

The archive is written to `tools/scrape_archive/output/` (not committed). `upload_plan.json` there maps each file to a path under the Google Drive folder `FML Scrape Archive`. Details, the change rules, and the optional Drive uploader are in `tools/scrape_archive/README.md`.
