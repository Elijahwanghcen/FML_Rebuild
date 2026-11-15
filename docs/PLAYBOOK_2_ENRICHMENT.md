# Playbook 2: Get the facts for each building

Input: `roster_final.json` from Playbook 1. Output: per building an exact location, aliases,
website and platform, amenities with evidence, floor plans and rent, photos. Reviews and
student rent reports are out of scope.

Findings marked CONFIRMED cite the UT build in `~/FML_scraper` (file or commit) or a test run
in this repo. INFERRED means it follows from the evidence but was not directly verified.
Measured results are in `docs/RESULTS.md`.

## Known gaps / open questions

- Photo review with vision is specified here but not implemented. Image captions and alt
  text are read; the pixels are not.
- Listings use the campus directory and a liberal LLM read of the floor-plans page. The
  per-platform JSON adapters from the UT scraper are in `reference/legacy_ut_scraper/` and
  are not yet wired to the platform fingerprint.
- Hand-verified coordinates in the UT data are mostly rounded to 4 decimals (~11 m), so the
  coordinate test cannot separate methods finer than about 20 m.
- "Absent" is only knowable from an explicit yes/no checklist. Without one, everything not
  found is unknown.

<!-- VERBAL NUANCE: -->

## Target schema (per building)

`canonical_name, aliases[], address, lat, lng, coord_method, coord_review, google_place_id,
property_type (apartment | student_housing | condo | co_op | dorm), area (neighborhood),
dist_campus_m, units_est, floors_est, website_url, management_company, site_platform[],
photos[], source_urls[], amenities{term: {status, evidence, evidence_type, source_url}},
units[{name, beds, baths, sqft, price_min, price_max, rent_basis, availability, concession,
layout_image_url, source_url, source_type}]`.

Every value carries where it came from. Aliases and prices also need a first-seen and
last-seen date once the pipeline runs on a schedule.

<!-- VERBAL NUANCE: -->

## 1. Coordinates (the part that is easiest to get wrong)

**Problem (CONFIRMED, `rentright_buildings/places/manual_overrides.json`, `qc_report.md`).**
Property sites, aggregators and plain geocoders pin the street-address centroid or the
wrong place entirely. UT examples:

- "Buena Vista Condominiums" matched "Buena Vista at Riata", 15 km away.
- "Pecan Walks" matched a greenbelt.
- "Texan & Vintage West Campus" got the address and pin of Crest at Pearl.
- "Hyde Park Court", "2400 Nueces", "Duval Villas" matched a street or an empty shell.
- "The Block" is one Google place for eight buildings; the leasing office is not the building.
- `walk_to_campus.py` notes that Google matches were wrong for Park Place and Duval Villas,
  so walking distance was computed from a separate hand-curated `property_coords.csv`.

The user's fix was to right-click the actual building in Google Maps and copy the point to
five or more decimals.

**Method that replaces most of the manual work (CONFIRMED by test, `aggregator/geo.py`).**

1. Geocode the street address against Overture's `address` layer (US National Address
   Database points, public domain). On the hard UT cases this landed 0.3 m from the
   hand-verified pin for Texan & Vintage (904 W 22 1/2 St) and 6 m for Buena Vista.
2. Find the Overture building outline that contains that point (or the nearest one within
   reach). Store the outline's center as `lat, lng`.
   `coord_method = nad_address+footprint_centroid`.
3. If the address is not in NAD, use the Google pin only to pick the outline and still store
   the outline's center. `coord_method = places_pin+footprint_centroid`.
4. Set `coord_review = true` when the NAD point and the Google pin disagree by more than
   60 m, or no outline is found. Those get the manual right-click, recorded in
   `coord_overrides.json` as `manual_rightclick`.
5. Never ship `pin_unverified` as final.

Why this is also the right legal choice: Google's Places terms allow storing `place_id`
forever, lat/lng for 30 days, and nothing else. Outline centers and NAD points are openly
licensed and can be kept.

Address normalization that mattered: "West 28th Street" = "W 28 St"; "22 1/2" and "22nd
Half" are the same; a trailing "Austin TX 78705" without a comma must be cut at the street
type; unit numbers are dropped.

Do not use the US Census geocoder. It interpolates along the street and reproduces the
original problem.

Multi-building complexes: pin each residential building, not the leasing office. When one
Google listing covers several buildings, take each building's own address from the
operator's site and geocode each separately.

<!-- VERBAL NUANCE: -->

## 2. Website resolution and platform fingerprint (`enrich_site.py`)

- Google's `websiteUri` is right for purpose-built student housing and wrong for most
  condos (CONFIRMED in test: Croix pointed to its manager's home page, Orange Tree to its
  owners' association).
- Rule: prefer any known URL whose path names the building (a realtor community page). If
  the seed is a multi-building site, follow the link whose text is the building's name.
  For condos, read every page that names the building and union the results.
- Strip tracking query strings. Check that the site is the right property: same-name
  properties in other parts of town are common (Elan 24 vs Elan East).
- Fingerprint the leasing platform from page source: Entrata, RentCafe/Yardi, RealPage,
  SightMap, AppFolio, Jonah, Knock, G5, LeaseLeads, Buildium, Rentvine, ShowMojo, plus the
  site builder. Twenty-two UT test sites: Entrata 13, WordPress 11, AppFolio 4, Duda 4,
  RentCafe 3.

Page discovery order (CONFIRMED, UT commit history and `amenities/pipeline/common.py`):

1. Navigation links whose text or path says amenities, floor plans, gallery.
2. **Sibling-path rule.** Entrata-style sites hang `/amenities/` one path segment above the
   seed's `/student/` or `/conventional/` path. `{seed}/amenities/` silently redirects to
   the floor-plans page, so also try the parent path. Nine UT buildings had empty amenities
   until this was fixed.
3. One floor-plan detail page. In-unit appliance lists (dishwasher, microwave) usually live
   one click below the floor-plans list.
4. Some sites have no amenities page at all (UT: Icon). Photo-tour captions are then the
   only source.

Fetching: plain HTTP first; headless Playwright when the page is client-rendered or
Cloudflare-fronted (many pass in headless Chromium); a headed browser for the few that
still block (UT: Troubadour, The Waller, Texan 26). Do not solve CAPTCHAs. Queue those
sites and ask the user to save the page HTML into `raw/<slug>/amenities.html`.

Archive every raw page under `data/<campus>/raw/<slug>/`. Everything downstream re-extracts
from disk.

<!-- VERBAL NUANCE: -->

## 3. Amenities (`enrich_amenities.py`)

Fixed vocabulary: 77 terms in 8 groups (`aggregator/assets/taxonomy.json`), each assigned
to a layer (apartment, community, premium) in `scoring_weights.json`. Never invent a term.

**Three states, never two (CONFIRMED, `amenities/README.md`).** A property site says what it
has. It never says "no sauna". Record present, select-units, optional, and leave everything
else unknown. Absent is recorded only from an explicit yes/no checklist (at UT, HousingScout
`li.yes` / `li.no` for 45 buildings). Air conditioning showed up at 12% of UT buildings
because nobody advertises it. That is a marketing artifact, not absence.

Extraction runs two passes and unions them:

- **A. Lists.** Collect list items, card headings, figure captions, `span.caption`, image
  alt text. Normalize and look up in `alias_map.json` (1,954 strings hand-mapped during the
  UT build, including which strings are not amenities). `evidence_type = stated`.
- **B. Liberal read.** Give an LLM the page prose plus captions and the vocabulary. It must
  return a verbatim quote for each term. A quote that is not on the page is discarded, which
  blocks invented amenities. `evidence_type` is `stated`, `implied_text` or `seen_photo`.

Rules the reader must follow (CONFIRMED, Rambler worked example, 2026-08-17):

- Gym equipment lists (treadmills, TRX, plyo boxes) roll up to Fitness Center. Furniture
  lists roll up to Furnished Units. Navigation and footer text is not an amenity. Of 58
  strings harvested from Rambler, 11 were gym equipment and 20 were furniture or page chrome.
- Implied amenities count when the text supports them: a published pet fee means Pets
  Allowed; "available for a fee" parking is On-Site Parking with status optional; an on-site
  café with a resident discount is Coffee Bar; "pet spa" is Pet Spa/Grooming; a 17th-floor
  lounge is VIP/Sky Lounge.
- "Select units" and "for an additional fee" change the status, not the term.
- Nearby businesses and neighborhood attractions are not building amenities.

Sources of amenity text, in order: the amenities page(s); home page; floor-plan detail
page; gallery captions; the campus directory's feature checklist; realtor description prose
(Uptown Realty's 33 UT buildings state amenities only in a prose Description).

**Small and rare amenities to look for by name:** pool, rooftop pool, hot tub, sauna, cold
plunge, yoga studio, spin room, dance room, golf simulator, climbing wall, pet spa, dog
run, jumbo screen, sky lounge, study rooms, package lockers, EV charging.

**Size as a prior.** A large building with many listed units almost always has a long
amenity list. Use the unit estimate to decide how hard to look (gallery, tour, Google
photos). It never sets a value: no evidence means unknown.

**Photos.** Captions and alt text are read now. The planned vision pass: for buildings with
40+ estimated units and fewer than 15 amenities, download up to 12 gallery images and ask a
vision model for the same vocabulary with `evidence_type = seen_photo`, quoting the image
URL as evidence.

<!-- VERBAL NUANCE: -->

## 4. Listings and rent (`enrich_listings.py`, `reference/legacy_ut_scraper/`)

Order of preference per building:

1. **Platform JSON endpoint.** The UT scraper has one adapter per platform, 14 backends for
   112 properties: ACC API, Entrata, SightMap, RentCafe (`window.ysi`), Knock, RealPage,
   AppFolio listings, Jonah detail JSON, and static parsers. Prefer the structured endpoint
   the floor-plans page calls over parsing HTML. Capture each floor-plan variant as its own row.
2. **Campus directory floor plans** (beds, baths, min/max rent, per-person flag).
3. **Liberal read.** Many realtor sites (Uptown Realty and similar) have no JSON or XML
   feed. Read the HTML loosely, and OCR screenshots when a price or plan exists only as an
   image. If a listing has no layout image, that is all the site has. Leave it null. Never
   guess a price; set `price_status = not_publicly_listed`.

Rent basis (CONFIRMED, UT `master.json` pricing notes):

- Purpose-built student sites price **per bed**. A 4-bed plan shows a lower number than a
  1-bed. Broker and conventional sites price **per unit**.
- The words person, bed or installment force per-bed. Record `rent_basis` on every row.
- Keep base rent and total-with-mandatory-fees separate when both are shown.
- Concessions lower the price and are separate from fees. Keep the raw text. Entrata promo
  popups are image-only: store the image URL.
- Strikethrough prices are the old price; the live price is beside them.
- A listings feed photo is not a floor-plan image. Leave `layout_image_url` blank for
  AppFolio and similar feeds.
- Weekly refreshes should run without an LLM where an adapter exists. The LLM read is for
  the first build and for sites with no feed.

Platform quirks worth knowing (CONFIRMED, UT build notes): SightMap responses are gzip;
RealPage image URLs contain a `%s` size token; Jonah floor-plan cards never hydrate in
headless, use the detail JSON; ASP.NET sites wrap the page in one `<form>`; Yugo cards are
`div.amenities-desc` with no list items.

<!-- VERBAL NUANCE: -->

## 5. Final build and QC (`build_json.py`)

Outputs in `data/<campus>/out/`: `buildings.json`, `amenities.json`, `units.json`,
`qc_report.md`. The shapes mirror the three UT catalogs the app reads (buildings, amenity
scores, units).

Per-building checklist:

- [ ] Name is the building's own, not a unit title or a management company
- [ ] Aliases include former names, the Google name if different, the street-address name
- [ ] Coordinate method is not `pin_unverified`; `coord_review` items were checked by hand
- [ ] The point sits on the residential building, not the leasing office
- [ ] Website is the building's page, not a manager's home page
- [ ] Amenity count is plausible for the building's size; zero means "unknown", say why
- [ ] Every amenity has a quote and a source URL
- [ ] Rent basis is set on every row; no guessed prices
- [ ] Blocked sites are listed for manual capture

<!-- VERBAL NUANCE: -->

## 6. Run order

```
python3 enrich_site.py <campus> [roster_file]
python3 enrich_amenities.py <campus> [roster_file]
python3 enrich_listings.py <campus> [roster_file]
python3 build_json.py <campus> [roster_file]
python3 eval_amenities.py <campus> <legacy amenities_features.json>   # UT only
```

<!-- VERBAL NUANCE: -->
