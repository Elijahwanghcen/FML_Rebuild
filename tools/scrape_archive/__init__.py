"""Save every scrape and catalogue what changed between runs.

Run from the repo root::

    python -m tools.scrape_archive ingest --campus ut-austin --input scrape.csv
    python -m tools.scrape_archive rebuild-history --campus ut-austin --fml-data /path/to/FML_Data
"""

__version__ = "1.0.0"
