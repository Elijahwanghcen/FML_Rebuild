# Photo pass: working scripts from the first hand-run (reference, not wired into `run_campus.sh`)

These are the scripts used once to fill property photos for a campus. They are kept so the next run
does not start from nothing. Method and rules: `docs/PLAYBOOK_2_ENRICHMENT.md` section 5.

Input: `targets.json`, a list of `{id, name, website}` for buildings that lack property photos.

| Step | File | What it does |
|---|---|---|
| 1 | `crawl.py` | Plain-HTTP read of each site's home page plus gallery/photo/amenity links; writes `crawl/crawl.json` |
| 1b | `browser_collect_images.js` + `recv_window_name.py` | Same, inside a real browser, for sites that block scripts. Reads lazy-loaded images, CSS backgrounds, script JSON and fetches the site's own gallery links |
| 1c | ~~`browser_collect_listing_site.js`~~ | Withdrawn 2026-11-18: listing aggregators (Zumper etc.) are not a photo source. Do not run it |
| 2 | `dl.py [ids]` | Downloads candidates, drops small and odd-shaped images, makes thumbnails; writes `crawl/cands.json` |
| 3 | `filt.py` | Drops images that are mostly white or black (floor plans, logos) |
| 4 | `sheet.py <n> [ids]` | Numbered contact sheets, two buildings per sheet, for the visual check |
| 5 | `pick.py <id> "<n>:<caption>" ...` | Records the photos chosen by eye, with captions, in `picks.json` |

Browser hand-off: `python3 recv_window_name.py <out_dir>` listens on 127.0.0.1:8777. The page script
stores its result in `window.name`; navigating the same tab to `http://127.0.0.1:8777/recv` posts it
to disk. This avoids reading long results through the browser tool, which cuts output at about 1,000
characters and withholds text that looks like a query string.

Known limits: no vision model call (the agent looked at the sheets itself); the publish step is
destination-specific and is not included; thresholds are in the code, not in a config.
