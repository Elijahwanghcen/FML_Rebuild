# Post-mortem: floor plans published without layout images (Texas A&M, found 2026-11-24)

## Summary

On 2026-11-24 the Texas A&M site had 828 floor plans and only 460 had a layout image. 60 buildings were short:
50 had no plan image at all and 10 had some (368 plans in total). Most images were **not missing from the web**.
For about 40 of the 46 buildings fixed that day, the images were already in pages the crawler had saved. They were
lost inside the pipeline: extractors that never read an image, one adapter bug, an upload that ran before the
image-capable extractors existed, and no QC metric that would have shown the gap.

After the fix pass: 751 / 828 plans have an image (291 added to 46 buildings, each checked by eye). 12 buildings have
no plan image on their site (pricing or vacancy only); about 20 plans across 12 more buildings need a person
(see "Open items").

## Timeline

| Date | Event |
|---|---|
| 11-15 | First A&M run. Listings come mostly from the LLM page read: plan names and prices, no images. |
| 11-16 | `update_building` gains `floorPlans`; A&M plans uploaded from that run's `units.json` (41 images). |
| 11-17/18 | New deterministic extractors (`text_plan_list`, `appfolio_smart`, `rentcafe_inline`, `jsonld_offers`, `cg_synergy`, rescues). FML now holds 654 imaged rows, but the site is **not re-uploaded**. |
| 11-24 | Audit: 50 buildings with plans and no images. Push of the 11-18 rows (+301 images on existing plans), then an image-matcher pass (+291). Matcher, adapters and QC gates moved into the pipeline. |

## Root causes

Counts are buildings among the 60 short ones. A building can appear in more than one row.

| # | Cause | Buildings | Evidence |
|---|---|---|---|
| 1 | **Extractor never emits an image.** `text_plan_list` (21), `llm_page_read` (12), `headed_rescue` (9), `appfolio_smart`/`appfolio_listings` (7), `university_rates` (2) and `rentcafe_inline`'s `ysi.floorplansList` path (2) return name, beds, baths, sqft and price only. `text_plan_list` was built on 11-18 as the deterministic stand-in for the LLM read and copied its text-only output. | 53 | `adapter` in `raw/<slug>/listings.json`. RentCafe's `ysi` JSON has no image field; the image is only in the card HTML. |
| 2 | **Adapter bug.** `cg_synergy` read `files[].url` / `fileUrl`; the API sends `files[].source` (`fileType: "Floorplan"`). | 2 (12 North, Rev Northgate: 33 plans) | API response for `live12north.com`. Fixed 11-24. |
| 3 | **No re-upload after the extractors improved.** The 11-16 upload used the 11-15 data. 11-18 output had 514 images for buildings already on the site; none went up until 11-24. LLM-read plans have no source row to carry an image. | ~39 | RMR showed 41 images where FML had 514. |
| 4 | **Page or markup not captured.** The floor-plans page was never saved (Brazos Oaks: only `home.html`). Per-plan detail pages were not crawled (Charleston Mills). The image sat only in `<noscript>`/`<picture data-iesrc>` (Tower Park) or was given only in alt text (Razz: Limestone). Wix `srcset` URLs contain commas. Bot walls blocked Reveille, Global, Midtown and Sundance/Sausalito. | ~10 | `raw/<slug>/meta.json` pages, 5 KB bot-wall responses. |
| 5 | **Plan names don't match the site's.** "1 Bedroom Large" against "1x1 Lg" (Campus Village). Duplicate names that only sqft tells apart (Broadstone's three "2 BEDROOM"). Unit-level rows ("Unit 132", "3628 S Hampton Ct - 116", AppFolio addresses). Junk names ("In every home", "Only 1 Vacant Unit Left"). One building's plans on another's profile (Sausalito holds Sundance's). | ~12 | `unit_label`s on RMR against the site's card titles. |
| 6 | **The site has no plan images.** Pricing or vacancy only: Park Place, Thomas Park, Holleman by the Park, The Gardens, five AppFolio-only buildings. SOHO has house photos only. | 12 | Browser checks and saved pages. |
| 7 | **No QC signal or image gate.** `coverage_flags` and `qc_report.md` count rows and prices, never images. The first matcher got images wrong in ways only a look would catch: Parkway Circle shifted by one card; reslife captions sit under the images; covers, room photos and a placeholder were picked up. | all | Visual rejections on 11-24. |

## What went right

- Saved raw HTML made the fix cheap: about 40 of 46 buildings were fixed with no new crawling.
- Every pick was checked on a contact sheet before going up. That caught the Parkway shift, the White Creek
  mis-pairing, Charleston's exterior covers and The London's room photos.
- Each edit is in the building's history and can be undone with `revert_building_edit`.

## Fixes made (2026-11-24, uncommitted)

- `aggregator/plan_images.py`: no-LLM image matcher run after every adapter (`listing_adapters.attach_images`, hooked
  into `enrich_listings.py` and `refresh_listings.py`). `VERSION` is now 10, so cached listings are redone on the next run.
- `image_gate()`: download check (HTTP 200, real image, at least 200x150, final URL after redirects, full Chrome UA)
  plus a border-uniformity score that separates plans from photos. In the 11-24 sample, all 273 accepted plans scored
  0.43 or more and all 9 rejected photos scored 0.35 or less; the threshold is 0.40.
- New adapters and fingerprints: `jsonld_floorplans` (`"@type":"FloorPlan"`) and `elementor_fp_posts`
  (`type-floor_plans`, 8 A&M buildings on one manager's template).
- `cg_synergy` now reads `files[].source`.
- `data/texas_am/plan_image_overrides.json`: hand-checked map for sites that print the plan name only inside the
  image (Richmond Ridge).
- New flags: `plan_images_missing:N/M` and `plan_images_check_by_eye:N`.
- `PLAYBOOK_2 §4x`: contingency ladder (below).

## Still to do

1. Add `plan images: X / Y plans` per building and campus-wide to `qc_report.md`, so a gap shows up on the next run.
2. Page discovery (§2e): read `sitemap_index.xml` and save every floor-plan detail page.
3. RMR push: re-push plan images after every enrichment run, not only plans. Never push `check_by_eye` rows
   unreviewed.
4. Data cleanup: move Sundance's plans off Sausalito; clean the Midtown, West U Gardens and Richmond Ridge plan
   lists; decide on Pershing Pointe (images per home type, rows per address).
5. Run the same audit on UT: 249 of about 2,660 plans have no image.

## Open items (needs a person)

Pershing Pointe (images per home type), Richmond Ridge (8 duplicate or variant plans), Midtown (junk names; the image
is `/media/l/plans/mid-combined.png`), Sausalito (holds Sundance's plans), The Jane ("1x1 + Study": only image is named
2x1.5), The London (3 Premium plans: room photos only), White Creek (regular vs Premium 2x1), West U Gardens (junk
name). Variants with no image of their own: Park West "Large" x5, The Stack x3, Harbor "Lady Bird" x3, Apex "The
Harrow", Global "Deluxe", and Reveille 2x2a/2x2b/3x3 (bot wall).
