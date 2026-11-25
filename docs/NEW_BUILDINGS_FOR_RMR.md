# New UT buildings for Rate My Rent (handoff for the `rmr` MCP)

Generated 2026-11-18 from the FML_rebuild UT run (`data/ut_austin/out/`, built 11-18 17:42) compared against the live
UT listing catalog (145 buildings, `search_listings`) and FML_Data @ 2026-11-17.

**55 candidate buildings** the rebuild found that are not in the live UT catalog. Full records (building fields,
amenity features, floor plans with rent, sqft, availability, layout image, source URL) are in
`docs/new_buildings_for_rmr.json`, one object per building: `{building, features, plans, meta}`.

Matching was by name tokens + distance + street number. It is not perfect: **check each one before adding.**

## How to process each building (one at a time)

1. **Is it already there?** `search_listings` (name, each alias, street address) and
   `search_buildings campus=ut-austin`. If found under another name: add the new name with `update_listing`
   `aliases` (or `update_building`), do not create.
2. **Is it a real, rentable building?** Open `meta.website`. Skip it (and write the reason in the table below)
   if it is a leasing office, management company, realtor, closed, or not housing.
3. **Add the building:** `add_listing_record catalog=buildings` with `building` from the JSON. Fix first:
   - `area`: a live key (`west_campus`, `east_campus`, `north_campus`, `north_university`, `hancock`, `downtown`,
     `riverside`...). Rebuild's "Hyde Park" was mapped to `north_university`; check it. A null area = not shown.
   - `property_type`: live uses `apartment`, `condominium`, `co_op`, `student_housing`.
   - `meta.coord_review: true`: confirm the pin on a map first.
4. **Cover photo + gallery** (the rebuild has **no photos** for any of these): take from the building's own site
   (gallery page first), not from listing sites or stock. `upload_listing_image url=...`, then `update_listing`
   `buildingImage` + `gallery` (up to 40, `[{src,title}]`). No logos, no maps, no photos of other buildings.
5. **Floor plans:** `add_listing_record catalog=floor_plans` for each entry of `plans` (objectID is already
   `<building id>__<plan slug>`). Per-bed rents carry `[Per Installment/Person]` in `unit_label`. Rows with no
   `base_rent` = price on request; keep them. If `plans` is empty, read the site's floor-plan/rates page by hand.
   Layout images: `layout_image_url` (https only).
6. **Amenities:** `features` is in the live taxonomy (`apartment/community/premium` lists): set with
   `update_listing` `features`. Amenity scores (`amenities` catalog) come later from the scoring script.
7. Every write: `reason` = "New UT building from FML_rebuild 2026-11-18 audit; verified <what you checked>".

## Fix the names first

| Rebuild name | Use | Why |
|---|---|---|
| "EASTGATE CONDO, perfect for House Staff at Dell/St. David's…" | Eastgate Condominiums | Google name is an ad title |
| "Shane Michael Brooks" (2813 Rio Grande) | Rio Heights | Google name is a realtor; site gbatx.com/.../rio-heights |
| College Houses Cooperatives (1906 Pearl) | **not added** | the organization's office, not a building |

## Tier 1: West/East/North Campus, has plans with rent (add first)

| Building | Dist (m) | Type | Plans (priced) | Source | Notes |
|---|---|---|---|---|---|
| River Oaks | 781 | apartment | 2 (2) | duda_appfolio_feed | Rainier ATX |
| The Eastwood | 835 | apartment | 7 (7) | appfolio_smart | |
| Taos Co-op | 1041 | co_op | 5 (5) | AI page read | College Houses; check rates page |
| Casa Del Rio Apartments | 1056 | apartment | 12 (12) | appfolio_smart | |
| University Quarters | 1143 | apartment | 2 (2) | duda_appfolio_feed | |
| Lantana Apartments | 1222 | apartment | 22 (22) | appfolio_smart | |
| Mark Embers | 1235 | apartment | 7 (7) | appfolio_smart | 3106 Speedway; not The Mark |
| House of Commons | 1249 | co_op | 2 (2) | AI page read | ICC co-op |
| Whitis Lofts | 1302 | apartment | 9 (9) | duda_appfolio_feed | |
| Salado Place | 1313 | apartment | 1 (1) | uptown_realty | |
| Diplomat West Campus | 1325 | apartment | 1 (1) | appfolio_smart | Westside Group |
| Somerset | 1379 | condominium | 2 (2) | uptown_realty | |
| Rio Grande Square | 1380 | student_housing | 1 (1) | appfolio_smart | 2800 Rio Grande; not Sparq |
| Starwest Condos | 1681 | condominium | 3 (3) | uptown_realty | |
| Warwick Apartments | 1694 | apartment | 6 (6) | appfolio_smart | |
| Nob Hill Homes | 1737 | apartment | 1 (1) | appfolio_smart | |
| Pease Parkside Apartments | 1792 | apartment | 2 (2) | appfolio_smart | |
| Volume | 1851 | apartment | 7 (7) | rentcafe_inline | |
| Su Casa Apartment Homes | 1873 | apartment | 4 (4) | appfolio_smart | |
| North 40 | 1924 | apartment | 1 (1) | rentcafe_inline | |
| Alexan Waterloo | 1564 | apartment | 25 (10) | sightmap | 21 layout images |
| Metropolis | 2197 | apartment | 32 (11) | sightmap | downtown, 415 Colorado |

## Tier 2: close in, plans but no rent (read the site by hand)

Rio House Apartments (2 plans), Pearl Street Co-Op (5), The Hive Red River (6, 2 priced), Lenox Condos (4),
Barranca Square Student Apartments (1), West Ridge Condos (4, 914 W 26th; not Regents West), Melroy Apartments (1),
Fountain Terrace (3, layout images), The Kingston (1).

## Tier 3: close in, no plans found (building only; plans by hand)

Blackstone Apartments, The G, Texan 304, New Guild Co-operative, Helios Co-Op (ICC), Gateway 8 (no website),
31st Street Condominiums, 21st Co-Op, Sunchase Condos, Presidio at Judge's Hill, Eastgate Condominiums,
San Remo (2204 San Gabriel; no website), Rio Heights, Sandpiper Apartments, Rio Flats, The 34 at Helms (no website),
Capitol Living, Monticello Studios (306 W 38th; not Hyde Park Court).

## Tier 4: more than 2.5 km out (lowest priority; ask Elijah before adding)

Sentral East Austin, Oak Park Apartments (16 priced), Hyde Park Apartments, Avana Apartments (4 priced),
Mosaic at Mueller (3 priced, no area), Waterloo Flats (16 plans, 11 priced).

## Results log (fill in as you go)

| Building | Done / skipped | Live id | Photos | Plans | Note |
|---|---|---|---|---|---|
