# A&M: moving 44 saved-HTML buildings to live adapters (2026-11-25)

The refresh refuses saved HTML (`saved_html_banned`), so 44 A&M buildings that only had a `text_plan_list` or a
`rentcafe_inline` reading `raw/<slug>/*.html` produced nothing on a fresh clone. Each site was opened in Chrome to see
where its plans and prices really come from (network requests, page data). Only adapters that work **without a
browser** (or with the existing headless DOM ladder) went into the config. 39 of 44 now run live.

## What each kind of site needs

| Site type (how to spot it) | Buildings | Adapter | Notes |
|---|---|---|---|
| Plans printed in the page HTML (`N bed \| N bath \| N sqft`); plain HTTP answers 200 | 20 | `text_plan_live` (new) | Same parser as `text_plan_list`, on the live page. Includes the 8 RealPage-managed `liveat<name>collegestation.com` sites, which publish **no prices** at all (the leasing link is a resident login at `<name>.loftliving.com`), so unpriced rows are correct there. |
| RentCafe (`fp-container`, `rentcafe.com`); plain HTTP gets a 403 bot wall | 4 | `rentcafe_ysi` (headless DOM) | Real and headless Chrome load fine (Arbors, Willow Oaks, The Wick, EnVue). |
| RentCafe "oculus" theme (`data-floorplan-price` on card links); 403 to plain HTTP | 4 | `rentcafe_cards` (new, headless) | No `ysi.floorplansList`, no fee buttons, so `rentcafe_ysi` returns nothing. Rebuild-owned script `aggregator/dom_rentcafe_cards.js` (the synced `dom_extract.js` must stay a byte copy of FML_Data). 100 Park, Dwell at 1600, Southgate Village, Sundance. |
| Entrata ProspectPortal `/<city>/<property>/student/`; plain HTTP 403 | 4 | `entrata_pp` (headless DOM) | Existing adapter works headless (Domain, Enclave, Reveille Ranch, Global). |
| Landmark "lv-master-template" WordPress (`lv-master-template-theme`) | 1 | `lv_fp_ajax` (new) | Page is a shell; `floorplan.js` POSTs `action=fp_submit_search` to `/wp-admin/admin-ajax.php` (no nonce) and gets the cards. The Heights. |
| LeaseLeads iframe (`LeaseLeadsEmbed('<uuid>')`) | 1 | `leaseleads_embed` (new) | `embed.leaseleads.co/<uuid>/floor-plans` returns 403 without the property site as `Referer`, 200 with it; the HTML holds the `floorPlans` JSON (prices, beds, baths, size, status, images). The Landing. Cambridge Hall uses LeaseLeads cards on its own page: `villas_wp`. |
| Duda site with AppFolio listings (`SiteAlias: '<id>'`, `appfolio-listings`) | 2 | `duda_appfolio_feed` (existing) | `/rts/collections/public/<SiteAlias>/runtime/collection/appfolio-listings/query-data`. A management company's feed covers every property: filter with `address_match` (31Thirty). |
| `"$inventory"` store with `"models":[…]` on `/models` (ResMan behind it) | 1 | `inventory_models` (new) | Cards are drawn by JS from JSON already in the HTML. Limestone Terrace (Razz likely the same). |
| beSwifty WordPress (`beswifty-core`) | 1 | `swifty_fp_ajax` (new) | POST `action=swifty_floorplan_section_details_with_ajax&pageType=floorplans`; cards are `div.single-floorplan[listing-price][listing-sqft]`. West University Gardens. |
| Wrong URL stored | 2 | — | Tower Park: `http://www.` 403s, `https://` answers. Barracks: the stored URL was one plan's page; `/floorplans/` lists all ten. |

Detection (`listing_adapters.detect`) now proposes `lv_fp_ajax`, `leaseleads_embed`, `inventory_models`,
`swifty_fp_ajax` and `rentcafe_cards` from their markers. `write_listing_config` freezes a `text_plan_list` win as `text_plan_live` and a
saved-page `rentcafe_inline` win as `rentcafe_ysi`, so a build no longer writes configs that the refresh refuses.

## Still on saved HTML (skipped by the refresh)

- SOHO Lofts: stored site is the manager's whole portfolio of individual houses (oakforestmanagement.com); no SOHO plans.
- Cherry Hill: aggievillas.net does not load (also hidden on Rate My Rent 11-25).
- North Ramparts: manager homepage; plans are on bcsonlinerealestate.com/alltwo.php (needs a small adapter).
- Copper Creek, Lakeridge: condo communities sourced from realtor pages; individual units, not floor plans.

## Known gaps after the move

- Saddlewood and Midtown lose prices live: Saddlewood prints `Rent` / `$899` about 10 lines below the plan line;
  Midtown loads per-bedroom prices with JS. Rows are kept, unpriced.
- North Ramparts' one row ("3500 Sq Ft") is junk from the manager homepage.
