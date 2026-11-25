# Phase 0 parity — 2026-11-25

Reference set: the owner's fresh `run.py` baseline. Full pass on FML_Data `402b54a` = 2,538 rows. The four `villas_wp` buildings re-run on `a953774` (LeaseLeads parser) bring the derived merge to **2,627 rows / 145 properties**. Remaining placeholders: Villas on 26th (HTTP 403), 1883 at Montgomery House (`no_rows`), Texan 26 (no public pricing). No CAPTCHA or Cloudflare challenge was bypassed.

Extractors are synced to `a953774`. Playwright is not installed here, so the DOM `villas_wp` parser was not re-executed. Baseline counts for those four are 45, 15, 15, and 18.

## Tier A — same cassette, both code paths

36 HTTP-feed buildings. **36 exact.** `scraped_at` was the same stamp, so every one of the 20 columns matched.

## Tier B — live, FML extractor then Rebuild extractor

Same 36 buildings, fetched live back to back. **36 exact, 0 unreachable.** This is code parity, not a comparison to the morning baseline.

## Tier B against the morning baseline

The cassette recorded this afternoon was replayed through Rebuild and compared to `advertised_prices_2026-11-25.merged-402b54a-plus-a953774-villas.json`. Numbers were normalized (`1424` vs `1424.0`) and `scraped_at` was ignored. **36 of 36 HTTP-feed buildings match the baseline on every other column.** No rent drift showed up between the morning scrape and this recording for that family.

## Tier A detail

Cassette URLs recorded: 60

# Tier A cassette replay (HTTP-feed family)

exact 36, mismatch 0, unreachable 0

| Building | Backend | Result | FML rows | Rebuild rows |
|---|---|---|---|---|
| The Block on 25th East | `acc_lightning` | exact | 26 | 26 |
| The Block on 25th West | `acc_lightning` | exact | 28 | 28 |
| The Block on 28th | `acc_lightning` | exact | 17 | 17 |
| The Block on Pearl North | `acc_lightning` | exact | 15 | 15 |
| The Block on Pearl South | `acc_lightning` | exact | 19 | 19 |
| The Block 23 | `acc_lightning` | exact | 21 | 21 |
| 26 West | `acc_lightning` | exact | 13 | 13 |
| Crest at Pearl | `acc_lightning` | exact | 26 | 26 |
| The Castilian | `acc_lightning` | exact | 3 | 3 |
| Callaway House | `acc_lightning` | exact | 19 | 19 |
| Skyloft Austin | `fp_units_modal_v2` | exact | 36 | 36 |
| 21 Rio | `wp_entrata_json` | exact | 84 | 84 |
| The Sondery | `sightmap` | exact | 69 | 69 |
| Montage Apartments | `appfolio_listings` | exact | 1 | 1 |
| Avon at 22nd | `appfolio_listings` | exact | 1 | 1 |
| Penthouse Apartments | `duda_appfolio_feed` | exact | 1 | 1 |
| Troubadour | `jonah_detail_json` | exact | 14 | 14 |
| Presidium Tech Ridge Apartments | `sightmap` | exact | 52 | 52 |
| Keystone Apartments | `knock_doorway` | exact | 22 | 22 |
| Preserve at Wells Branch | `knock_doorway` | exact | 46 | 46 |
| VEER Apartments | `appfolio_listings` | exact | 1 | 1 |
| Estates at East Riverside | `jonah_detail_json` | exact | 3 | 3 |
| Elan East Apartments | `realpage_cms_proxy` | exact | 251 | 251 |
| Haus 535 (Haus 5350) | `jonah_detail_json` | exact | 10 | 10 |
| Torre | `wp_entrata_json` | exact | 47 | 47 |
| Villas on 24th | `wp_entrata_json` | exact | 11 | 11 |
| Lone Star Lofts | `appfolio_listings` | exact | 4 | 4 |
| Texan Pearl | `duda_appfolio_feed` | exact | 10 | 10 |
| Texan & Vintage West Campus | `acc_lightning` | exact | 21 | 21 |
| Camino Flats | `realpage_cms_proxy` | exact | 69 | 69 |
| Leon Place Condominiums | `appfolio_listings` | exact | 15 | 15 |
| Hilltop | `wp_entrata_json` | exact | 24 | 24 |
| The Block on Rio | `acc_lightning` | exact | 15 | 15 |
| The Block on Leon | `acc_lightning` | exact | 30 | 30 |
| Village at East Riverside | `jonah_detail_json` | exact | 3 | 3 |
| Preservation Square | `appfolio_listings` | exact | 2 | 2 |

## Tier B detail

# Tier B live shadow (HTTP-feed family)

exact 36, mismatch 0, unreachable 0

| Building | Backend | Result | FML rows | Rebuild rows |
|---|---|---|---|---|
| The Block on 25th East | `acc_lightning` | exact | 26 | 26 |
| The Block on 25th West | `acc_lightning` | exact | 28 | 28 |
| The Block on 28th | `acc_lightning` | exact | 17 | 17 |
| The Block on Pearl North | `acc_lightning` | exact | 15 | 15 |
| The Block on Pearl South | `acc_lightning` | exact | 19 | 19 |
| The Block 23 | `acc_lightning` | exact | 21 | 21 |
| 26 West | `acc_lightning` | exact | 13 | 13 |
| Crest at Pearl | `acc_lightning` | exact | 26 | 26 |
| The Castilian | `acc_lightning` | exact | 3 | 3 |
| Callaway House | `acc_lightning` | exact | 19 | 19 |
| Skyloft Austin | `fp_units_modal_v2` | exact | 36 | 36 |
| 21 Rio | `wp_entrata_json` | exact | 84 | 84 |
| The Sondery | `sightmap` | exact | 69 | 69 |
| Montage Apartments | `appfolio_listings` | exact | 1 | 1 |
| Avon at 22nd | `appfolio_listings` | exact | 1 | 1 |
| Penthouse Apartments | `duda_appfolio_feed` | exact | 1 | 1 |
| Troubadour | `jonah_detail_json` | exact | 14 | 14 |
| Presidium Tech Ridge Apartments | `sightmap` | exact | 52 | 52 |
| Keystone Apartments | `knock_doorway` | exact | 22 | 22 |
| Preserve at Wells Branch | `knock_doorway` | exact | 46 | 46 |
| VEER Apartments | `appfolio_listings` | exact | 1 | 1 |
| Estates at East Riverside | `jonah_detail_json` | exact | 3 | 3 |
| Elan East Apartments | `realpage_cms_proxy` | exact | 251 | 251 |
| Haus 535 (Haus 5350) | `jonah_detail_json` | exact | 10 | 10 |
| Torre | `wp_entrata_json` | exact | 47 | 47 |
| Villas on 24th | `wp_entrata_json` | exact | 11 | 11 |
| Lone Star Lofts | `appfolio_listings` | exact | 4 | 4 |
| Texan Pearl | `duda_appfolio_feed` | exact | 10 | 10 |
| Texan & Vintage West Campus | `acc_lightning` | exact | 21 | 21 |
| Camino Flats | `realpage_cms_proxy` | exact | 69 | 69 |
| Leon Place Condominiums | `appfolio_listings` | exact | 15 | 15 |
| Hilltop | `wp_entrata_json` | exact | 24 | 24 |
| The Block on Rio | `acc_lightning` | exact | 15 | 15 |
| The Block on Leon | `acc_lightning` | exact | 30 | 30 |
| Village at East Riverside | `jonah_detail_json` | exact | 3 | 3 |
| Preservation Square | `appfolio_listings` | exact | 2 | 2 |
