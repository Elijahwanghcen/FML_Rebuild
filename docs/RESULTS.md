# Measured results (run of 2026-11-14 / 15)

All numbers come from the scripts in `aggregator/` and the files in `data/<campus>/`.

## Known gaps

- **Policy change 2026-11-18:** aggregators and campus directories (RentCollegePads, CoStar, Zillow, Zumper) are no longer a source for
  rent, floor plans, amenities, photos or websites. The measurements below that mention directory rows, directory features or a listing-
  site photo fallback are historical (UT: 255 directory rows over 47 buildings, 709 A&M directory rows, 'directory features' in the
  amenity table) and no longer reproducible. See docs/PLAYBOOK_1_DISCOVERY.md Source 4.

- Photo review with vision is not built. Captions and alt text only. Property photos were collected once by hand
  (`reference/photo_pass/`); the visual check was done by the agent, not by a scripted model call.
- Rents come from the campus directory and an AI read of floor-plan pages. The UT per-platform scrapers
  (`reference/legacy_ut_scraper/`) are not wired in, so prices rendered only by a JavaScript widget are missed.
- `rent_basis` is inferred from building type when the page does not say person or unit. Spot-check it.
- A&M's directory rows were collected without floor plans or prices (name, address, coordinates, per-bed flag only).
- 10 A&M buildings still carry a raw Google pin (`pin_unverified`). Replace them by hand before publishing coordinates.
- Runs were interrupted by usage limits several times. Steps now refuse to save a result when the AI read fails, but
  the final amenity pass used a smaller text window (50k characters per building) than the 22-building test (95k).

## UT Austin: blind rebuild vs the existing 143-building roster

Discovery (roster buildings found without looking at the roster):

| Stage | Found | Note |
|---|---|---|
| Google Places only | 123 / 143 (86%) | ~525 calls |
| Overture places only | 37 / 143 (26%) | |
| + campus directory + name fixes | 126 / 143 (88%) | |
| + realtor sites + address recovery + Reddit | **128 / 143 (90%)** | |

The 15 misses: 12 are 4.8–42 km from campus (Round Rock, San Marcos, Wells Branch, far north and south Austin);
Palmetto Condominiums (no Google listing, no realtor page found); Gateway Apartments (university family housing);
Park Place Condominiums (named on a realtor page with no address).

Volume: 1,454 candidate records merged into 830 buildings, 733 inside the named neighborhoods. Tier A 235, tier B 274.
The top 150 by student-relevance score contain 97 buildings from the old roster. The other 53 are buildings the
old roster did not have (co-ops, West Campus mid-rises, condo buildings).

Source volumes: 243 realtor/manager sites picked, 116 returned buildings (776 raw candidates, 67 name-only ones
given an address). Reddit: 120 threads, 187 distinct building names, 88 named in two or more threads.

Coordinates (97 rebuilt buildings matched to hand-curated pins): median 22 m apart, 58 within 25 m, 9 more than
100 m. 105 of the 143 hand pins are rounded to 4 decimals (~11 m). On the two hardest cases the address-point
method landed 0.3 m (Texan & Vintage) and 6 m (Buena Vista) from the hand pin. 138 of 150 used
address point + outline center; 12 used Google pin + outline center; 6 flagged for manual review.

Amenities:

| Test | Buildings | Old terms recovered | Note |
|---|---|---|---|
| First pass | 20 | 72% | lists page only |
| + floor-plan detail page + directory features | 20 | 81% | 184 extra terms with quotes |
| Full top-150 run | 93 comparable | 74% overall, 83% median per building | smaller text window |

Most-missed terms are in-unit appliances (dishwasher, microwave, refrigerator, disposal, ceiling fans). In the
22-building test 52 terms came from implied text and 20 from photo captions.

Final UT output (`data/ut_austin/out/`): 150 buildings (90 apartment, 34 condo, 15 student housing, 9 co-op,
2 dorm); 141 with amenities (median 18); 109 with a public price; 1,474 unit rows (765 from first-party
pages, 709 from the campus directory); 50 buildings with aliases. Sites: 140 read, 7 blocked or empty, 3 no website.

## Texas A&M: first new campus

Sources: Places 877 candidates (373 calls); AggieSearch 564 listings, 415 named places after dropping sublets and
shared rooms, 132 in College Station and 38 in Bryan (the rest are other A&M campuses); 229 realtor/manager
sites picked, 51 returned buildings (179 candidates); Reddit r/aggies 120 threads, 207 building names, 107 in two
or more threads.

Roster: 570 records merged into 310 buildings, 293 in the named areas. **173 in tiers A and B** (floor is 150):
112 apartments, 37 condos, 21 purpose-built student housing, 3 private dorms. By area: Northgate 41, Wolf Pen
Creek 40, Holleman 33, West Villa Maria 12, Southside 11, Eastgate 9, South Bryan 7, Southwest Parkway 5,
Harvey Mitchell South 4, campus core 3, outside 8.

Final A&M output (`data/texas_am/out/`): 173 buildings; 117 with amenities (median 13); 69 with a public
price; 649 unit rows; 33 with aliases. Sites: 140 read, 30 no website, 3 blocked or empty. Coordinates: 133
address point + outline center, 27 Google pin + outline center, 3 address point only, 10 unverified pin; 50
flagged for a manual check.

Aliases found automatically: Ion College Station = Aspire College Station; The Aria = Gateway at College Station;
The Doce = The District on Luther; EVER College Station = Casa Del Sol; Fifteen12 = College Edge; The Grand 1501 =
Plantation Oaks. Merges to check by hand: Arbors at Wolf Pen Creek / "Kiest Hall - Dorm 2"; Hidden Bridge
Condominiums / River Oaks Townhomes; The Atrium / Campus View / Pearl Apartments / The Marc.

What broke at A&M and the rule it produced:

| Problem | Rule |
|---|---|
| Rent College Pads had 8 listings; the real directory is on the CoStar platform and blocks scripts | Check both directory platforms; collect CoStar ones through the user's Chrome |
| 41 on-campus residence halls ranked as "dorms" | Drop halls near campus known only from map data |
| Personal map pins ("Charlie", "Grace and Joey's") merged in as aliases | Drop zero-review, no-website Places without a building-like name |
| Senior living, leasing offices, realtor teams in the roster | Name filter |
| Directory covers other system campuses (Fort Worth, Galveston) | Cut by `max_radius_m` |
| College town is spread out; one core radius misses clusters | Set neighborhoods from where directory listings cluster |

### Website and photo check after import (2026-11-16, 162 published profiles)

Campus-specific numbers only. The rules they produced are written campus-neutral in the playbooks.

| Check | Result |
|---|---|
| Profiles with no property photo (floor-plan images not counted) | 100 of 162 |
| Filled by reading home pages only | 54 |
| Filled after also reading gallery pages and using a listing site as fallback | 71 |
| Still without a photo, each with a reason | 29 |
| Website was the campus off-campus directory | 7 |
| Website was a spam or lapsed domain | 4 |
| Exact same website on more than one profile | 9 profiles in 4 groups |
| Entries that should not be separate buildings | 4 (2 probable former names of another entry, 1 locator service, 1 office and retail centre) |

Domain probe (`resolve_website.py`), run afterwards: on 108 profiles whose own site was already known it
confirmed 49 on the same domain, returned 10 more as leads, confirmed 5 on a different domain that was also the
right building, and confirmed 0 on a wrong building. On the 29 profiles left without a photo it confirmed a site
for 4 that a name search had reported as having none.

| Problem | Rule (playbook section) |
|---|---|
| One name search per building; a summary said "no official site" for sites on the obvious domain | Website ladder with a domain probe and a real search (P2 2b) |
| Searching with the campus city for buildings in the next city | Take the city from the address; `neighbor_cities` in the config (P1 1) |
| Campus directory stored as the website | Website classes; a directory is a listing page (P2 2a) |
| Stored URLs never re-fetched; spam and lapsed domains shipped | Fetch and read every stored URL each run (P2 2c) |
| Only the home page was read for photos; galleries missed | Gallery page first; read lazy-load, script and background images (P2 5b) |
| Floor plans counted as images | Three separate photo counts (P2 5a) |
| Stock, logos, other properties in the candidate pile | Mandatory visual check on contact sheets (P2 5d) |
| A listing page's first image list belonged to nearby listings | Use the media list that starts with the page's main image (P2 5b) |
| Unverifiable names published as empty pages | Publish gate; verify before counting (P1 5a, P2 6) |

## Cost

Google Places at list price: UT $19.15 (547 calls), A&M $13.06 (373 calls). Monthly free tiers may cover part.
Overture, the address index, and the campus directories are free.
