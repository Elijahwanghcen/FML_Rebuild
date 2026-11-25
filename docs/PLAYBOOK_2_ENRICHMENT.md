# Playbook 2: Get the facts for each building

Input: `roster_final.json` from Playbook 1. Output: per building an exact location, aliases,
website and platform, amenities with evidence, floor plans and rent, photos. Reviews and
student rent reports are out of scope.

Findings marked CONFIRMED cite the UT build in `~/FML_scraper` (file or commit) or a test run
in this repo. INFERRED means it follows from the evidence but was not directly verified.
Measured results are in `docs/RESULTS.md`.

## Known gaps / open questions

- Photos (section 5) were done once by hand with the scripts in `reference/photo_pass/`. They
  are not wired into `run_campus.sh`, and the visual check was done by the agent looking at
  contact sheets, not by a scripted vision call.
- Website resolution (section 2) has one scripted step, `resolve_website.py` (domain probe).
  The search step and the "follow the link on a manager or listing page" step are still
  manual. The probe alone confirms about half of the sites that exist.
- The publish gate (section 6) is specified here and not yet enforced by `build_json.py`.
- Listings come from the building's own site (platform feed adapters) or its local realtor /
  property-manager firm's page, never from an aggregator or campus directory (RentCollegePads,
  CoStar, Zillow, Zumper; `common.is_ils`). The LLM read is a last resort.
- Hand-verified coordinates in the UT data are mostly rounded to 4 decimals (~11 m), so the
  coordinate test cannot separate methods finer than about 20 m.
- "Absent" is only knowable from an explicit yes/no checklist. Without one, everything not
  found is unknown.

<!-- VERBAL NUANCE: -->

## Target schema (per building)

`canonical_name, aliases[], address, lat, lng, coord_method, coord_review, google_place_id,
property_type (apartment | student_housing | condo | co_op | dorm), area (neighborhood),
dist_campus_m, units_est, floors_est, website_url, website_class, website_status,
website_checked_at, management_company, site_platform[],
photos[{src, kind, caption, source_url, source_type}], source_urls[],
amenities{term: {status, evidence, evidence_type, source_url}},
units[{name, beds, baths, sqft, price_min, price_max, rent_basis, availability, concession,
layout_image_url, source_url, source_type}], publish_status, publish_reason`.

`photos[]` holds property photos only. Floor-plan and layout images live on the unit rows
(`layout_image_url`) and are never counted as photos (section 5).

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

The website is the door to everything else (amenities, rents, photos). A wrong or missing
website silently empties the rest of the record, so this step gets its own ladder, its own
check, and its own status fields.

### 2a. What counts as the website

Set `website_class` on every building:

| Class | Meaning | Allowed as `website_url` |
|---|---|---|
| `own_site` | A domain for this one property (or for two or three sister properties run together) | Yes |
| `operator_page` | This building's own page on its operator's or manager's site | Yes |
| `official_org_page` | The owning institution's page for the building (a university housing department page for a hall it runs) | Yes |
| `portal` | A hosted leasing or resident portal on the property's own subdomain | Yes, when nothing better exists |
| `listing_page` | The building's page on a listing site or a campus off-campus directory | No. Never stored, never crawled, never read for data (`common.is_ils`) |
| `generic_page` | A manager, realtor or owners' association home page or search page that does not name the building | No |
| `none` | Nothing found after the full ladder | Leave null |

Rules:

- A campus off-campus directory is a listing site even when it sits on the university's own
  domain. It is run by a listing company. Never store it as the website. The university's
  housing department page for a building the university runs is a different thing and is fine.
- Never judge a URL by its root domain alone. Ten buildings on one root can be ten good
  operator pages, one directory, or one realtor search page pasted ten times.
- Strip tracking query strings before storing.

### 2b. Finding it: run every rung, stop at the first verified hit

CONFIRMED by test (second-campus pass, 2026-11-16). The first attempt used one web search per
building ("name + city") and reported "no official site" for buildings whose site loads with a
plain request on the obvious domain.

1. **Google `websiteUri`** and the landlord website a source supplied, if present. Aggregator and directory URLs are dropped before this step. Both go through the
   check in 2c like any other candidate. Google's value is right for purpose-built student
   housing and wrong for most condos (CONFIRMED in test: Croix pointed to its manager's home
   page, Orange Tree to its owners' association).
2. **Domain probe** (`resolve_website.py`). Build the name slug (drop "the", drop type words
   such as apartments, condos, townhomes) and request the common shapes: `<slug>.com`,
   `<slug>apartments.com`, `<slug>apts.com`, `live<slug>.com`, `liveat<slug>.com`,
   `liveat<slug><city>.com`, `<slug>living.com`, `<slug><city>.com`, `<slug>townhomes.com`,
   `.net` variants, and hosted portals that answer "unknown account" for a wrong name
   (`<slug>.managebuilding.com`). Measured on 108 buildings whose site was already known: 49
   confirmed on the same domain, 10 more returned as leads, 5 confirmed on a different domain
   that was also the right building, 0 confirmed on a wrong building. It resolved 4 of 29
   buildings the search step had given up on. It is cheap and precise; it is not complete.
3. **Search, done properly.** One query is not a search.
   - Use the city in the building's **address**, not the campus city. Properties across a
     city line are common and a query with the wrong city returns only listing sites.
   - Query with the street address and with the phone number as well as the name.
   - Exclude listing-site domains from the results, or the first page is nothing else.
   - Read the result URLs. Do not accept a summary that says no official site exists.
4. **Follow the link out.** A manager's property page, a listing page, and a third-party
   leasing page usually carry a "visit website" link or a `communityWebsiteUrl`-style field
   in the page source. An email address on any page (`leasing@<domain>`) names the domain.
5. **Portfolio sites.** If the seed is a multi-building site, follow the link whose text is
   the building's name; prefer any known URL whose path names the building. For condos, read
   every page that names the building and union the results.
6. Only after all five rungs fail set `website_class = none`.

### 2c. Checking that the page is this building

A candidate is accepted when the page shows the building's **street address**, or its
**name and its city** on a page that is clearly about housing. Record which. Otherwise it is
a lead for a person, not a result.

Traps seen in test, each with its rule:

| Trap | Rule |
|---|---|
| Same name, different town (a national brand or a common name) | Name alone never confirms. Require the address or the city |
| Lapsed domain now selling something else, a gambling page, or a throwaway TLD copy of the name | Fetch every stored URL and read the title and text. Unrelated content means clear the field. A stored URL is a claim, not a fact |
| Domain marketplace or parked page | Reject when the final URL lands on a domain seller or the page offers the domain for sale |
| Hosts that answer every subdomain the same way (a bot challenge for any name) | No signal. Do not probe them |
| Property page on a manager's site that later returns 404 | Re-check on every run. Store `website_status` (ok, redirected, blocked, dead, unrelated) and `website_checked_at` |
| A page that redirects to a new path | Store the final URL |
| One site for two sister properties | Keep the shared home page as the website for both, and find each property's own sub-page for photos, plans and amenities. Do not copy one property's content onto the other unless the site says it is shared |
| The old-name domain shows a new brand | This is a rebrand. The entry is a duplicate of the new name: merge and keep the old name as an alias (Playbook 1 section 3) |
| The "building" site is a locator or referral service | The entry is not a building. Drop it (section 6) |
| The site is for an office or retail centre with the same name | Not housing. Drop it |

After the pass, list every `website_url` used by more than one building. Each group is one of:
sister properties (fine), a rebrand duplicate (merge), or a generic page (clear it).

### 2d. Fetching

Plain HTTP first; headless Playwright when the page is client-rendered or Cloudflare-fronted
(many pass in headless Chromium); a real browser session for the ones that still block. A
403 with a "just a moment" page is a bot challenge, not a missing site: the site exists and
loads in a normal browser. Image and media hosts usually stay open even when the page itself
is challenged, so image URLs read in the browser can be downloaded by script afterwards.

Reading a page inside the user's browser: have the page script put its result in
`window.name`, then navigate the same tab to a localhost receiver that writes it to disk
(`reference/photo_pass/recv_window_name.py`). Browser tools cut long output and withhold text
that looks like a query string, so do not try to read results back through the tool.

Do not solve CAPTCHAs. Queue those sites and ask the user to save the page HTML into
`raw/<slug>/`.

### 2e. Platform fingerprint and page discovery

> Floor-plan images depend on this step: save the floor-plans page, every per-plan page from `sitemap_index.xml`, and keep `<noscript>`/`<picture>`/JSON-LD intact. See §4x A1-A4.

- Fingerprint the leasing platform from page source: Entrata, RentCafe/Yardi, RealPage,
  SightMap, AppFolio, Jonah, Knock, G5, LeaseLeads, Buildium, Rentvine, ShowMojo, plus the
  site builder. Twenty-two UT test sites: Entrata 13, WordPress 11, AppFolio 4, Duda 4,
  RentCafe 3.
- Check that the site is the right property: same-name properties in other parts of town
  are common (Elan 24 vs Elan East).

Page discovery order (CONFIRMED, UT commit history and `amenities/pipeline/common.py`):

1. Navigation links whose text or path says amenities, floor plans, gallery, photos,
   photo gallery, media, tour. Small sites use `/gallery`, `/photos`, `/photogallery`,
   `/Gallery.aspx`. Always open the gallery page: the home page often shows one stock hero
   image while the gallery holds twenty real ones.
2. **Sibling-path rule.** Entrata-style sites hang `/amenities/` one path segment above the
   seed's `/student/` or `/conventional/` path. `{seed}/amenities/` silently redirects to
   the floor-plans page, so also try the parent path. Nine UT buildings had empty amenities
   until this was fixed.
3. One floor-plan detail page. In-unit appliance lists (dishwasher, microwave) usually live
   one click below the floor-plans list.
4. Some sites have no amenities page at all (UT: Icon). Photo-tour captions are then the
   only source.

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
page; gallery captions; realtor description prose
(Uptown Realty's 33 UT buildings state amenities only in a prose Description).

**Small and rare amenities to look for by name:** pool, rooftop pool, hot tub, sauna, cold
plunge, yoga studio, spin room, dance room, golf simulator, climbing wall, pet spa, dog
run, jumbo screen, sky lounge, study rooms, package lockers, EV charging.

**Size as a prior.** A large building with many listed units almost always has a long
amenity list. Use the unit estimate to decide how hard to look (gallery, tour, Google
photos). It never sets a value: no evidence means unknown.

**Photos as amenity evidence.** Captions and alt text are read now. Once section 5 has
collected and checked a building's photos, the same images can be shown to a vision model
with the vocabulary (`evidence_type = seen_photo`, the image URL as evidence). Do this for
buildings with 40+ estimated units and fewer than 15 amenities.

<!-- VERBAL NUANCE: -->

## 4. Listings and rent (`enrich_listings.py`, `reference/legacy_ut_scraper/`)

Order of preference per building:

1. **Platform JSON endpoint.** The UT scraper has one adapter per platform, 14 backends for
   112 properties: ACC API, Entrata, SightMap, RentCafe (`window.ysi`), Knock, RealPage,
   AppFolio listings, Jonah detail JSON, and static parsers. Prefer the structured endpoint
   the floor-plans page calls over parsing HTML. Capture each floor-plan variant as its own row.
   This step is wired in `aggregator/listing_adapters.py`: `detect()` finds the feed from
   markers in the crawled HTML and builds the adapter's parameters itself (no per-property
   config), then calls the legacy extractor. It runs before any LLM read.
2. **Liberal read.** Only when no adapter returned priced rows. Many realtor sites (Uptown Realty and similar) have no JSON or XML
   feed. Read the HTML loosely, and OCR screenshots when a price or plan exists only as an
   image. If a listing has no layout image, that is all the site has. Leave it null. Never
   guess a price; set `price_status = not_publicly_listed`.
3. **No third step.** There is no directory or aggregator fallback. If the building's own site and
   its local realtor's page show no price, the building is `not_publicly_listed` and its units
   stay empty. An aggregator's number is not a substitute (RentCollegePads at UT gave 255 rows
   for 47 buildings that the original scraper had read from Uptown Realty, Landmark sites and
   Quarters portals instead).

   **Local realtor / PM firms are first-party for this purpose.** Their per-building page is the
   seed (`merge_candidates` keeps it as `website`/`other_urls`; `discover_pm_sites.sitemap_pages`
   finds every page of a firm), and the firm's parser supplies rows: `uptown_realty`
   (`uptownrealtyaustin.com/communities/<slug>/`, static `ampti` cards), `westside_prose` +
   AppFolio portal, `duda_appfolio_feed`, `appfolio_smart`. Original scraper rows for the UT
   condos (Croix, Dos Rios, Littlefield, Orange Tree, Parapet, Treehouse, Vanderbilt,
   Waterford, Buena Vista) all came this way.

**Build phase vs weekly refresh (taken from FML_scraper, the most reliable UT system).**

| | Build: `enrich_listings.py` | Refresh: `refresh_listings.py` |
|---|---|---|
| When | New campus, new building, or a building that keeps failing | Every week |
| Reads | Crawled pages, `resolutions.json`, `rescues/` | `listing_config.json` only |
| Does | Detect the platform, try adapters, freeze the winner | Run the frozen adapter |
| LLM | Only with `--llm`, one building at a time | Never |
| Writes | `raw/<slug>/listings.json`, `listing_config.json` | `out/units_<date>.json`, `out/refresh_<date>.md` |

Order of attempts per building in the build phase. Each step runs only if the previous
found nothing:

1. Feed markers in the saved HTML (`detect()`), including the Entrata portal path rule below.
2. Network fingerprint (`fingerprint.js`, ported from FML_scraper): open the floor-plans
   page, record its JSON/XHR calls, and map them to an adapter (SightMap, Knock, ACC,
   wp-json Entrata, RealPage, G5).
3. Cloudflare ladder for browser adapters: headless, then headless with the persistent
   profile `~/.fml_dom_profile` (a clearance cookie survives between runs), then a visible
   browser. Interactive CAPTCHAs are never solved.
4. Hand-saved rescue `data/<campus>/rescues/<objectID>.json` (`{"source_url", "rows": [...]}`
   in the legacy row schema), the same idea as FML_scraper's `ingest_headed_rescues.py`.
5. Nothing found: the building is flagged `needs_case_by_case`. An LLM read happens only when
   someone runs `--llm` for it.

**Entrata portal path.** The plans are on `/<city>/<property-slug>/(student|conventional)/`,
not the marketing "Floor Plans" page. FML_scraper always pointed `entrata_pp` there. The
rule accepts a portal link only when its slug shares a word with the building name and
its path names the campus city or a `neighbor_cities` entry. Camber Villas: marketing page
0 rows, portal page 4 priced plans.

Refresh rules kept from FML_scraper `CLAUDE_WEEKLY.md`: no new extractors and no site
debugging during a refresh. A failure keeps an explicit stub row with its status. A
source shared by several buildings is fetched once. Big price or row-count moves are
listed for a person, not corrected.

Row schema is the legacy one, kept whole: `base_rent`, `total_price_with_mandatory_fees`,
`price_basis`, `concessions_raw/type/value`, `layout_image_url`, `price_image_url`,
`concessions_image_url`, plus `price_min/max`, `rent_basis`, `adapter`.

**Why the adapter step is mandatory (CONFIRMED, UT comparison 2026-11-16).** The first
rebuild skipped step 1 and read only page text with an LLM: 1,474 rows against the legacy
scraper's 2,396. The page-text read loses listings in four ways:

- The plans are not in the HTML. A widget loads them after the page opens (Repli360/RRAC,
  Knock, RentCafe, RealPage, SightMap, Yugo, Entrata). A plain fetch that returns a few
  hundred characters of menu text looks like a successful page.
- The plans are in a `<script>` JSON block or a JSON API (ACC lightning, wp-json Entrata,
  Jonah `jd-fp`, Duda collections, RealPage CMS proxy). Text extraction drops scripts.
- One plan has many rows: rate tiers, room types, each available unit. An LLM asked for
  floor plans returns one row per plan, and long pages are cut off.
- The wrong page is read: a loose link match picked Contact or a global Rooms page.

**Extractor catalog** (`detect()` in `listing_adapters.py`; add a row when a new platform shows
up). "Where the data really is" is the important column: it is often not the page a person
reads, and not the site's own domain.

| Marker in saved HTML / network | Adapter | Where the data really is | Nuance |
|---|---|---|---|
| `/api/lightning/floorplans/<id>` | `acc_lightning` | ACC JSON API | Multi-building feed (The Block) split by `LocationFilter`; a building with no own page is matched through a sister's feed only if its name also carries the community name |
| `{site}/wp-json/theme/entrata/v1/floor-plans` answers | `wp_entrata_json` | WordPress JSON | GMH variant at `/wp-json/gmh-student/floorplans/categories` (Torre) |
| `/<city>/<slug>/(student\|conventional)/` link, slug shares a word with the name, path names the campus city or a `neighbor_cities` entry | `entrata_pp` | Entrata portal page | Template leftovers link other properties' portals (Scandia → Indianapolis, `entrata.elaraflagstaff.com` on three A&M sites); the slug/city check rejects them |
| Entrata portal in an `<iframe>` | `entrata_pp` | iframe page | FML_scraper Noble 2500 |
| Only an Apply link to `<x>.prospectportal.com` or `entrata.<site>` | (Chrome, see below) | `https://<host>/Apartments/module/application_authentication/` links to `/<city>/<slug>/`; plans at `<base>student/` or `<base>conventional/` | Slugs are not guessable (`woodlands-apartments-721`). Portal hosts are almost always Cloudflare-protected |
| `CmsSiteManager/callback.aspx` | `realpage_cms_proxy` | RealPage WS via site proxy | |
| `sightmap.com/embed/<code>` | `sightmap` | SightMap API (embed page names it) | gzip |
| `app.repli360.com/admin/rrac-website-script/<token>` | `repli360_feed` | `POST app.repli360.com/admin/template-render` with `site_id` from the script | Off the property's domain, so it works when the site blocks headless browsers (Marq Uptown, 2026-11-17). The widget repeats each card under every bedroom tab: dedupe on (name, price, size); the old browser parser double-counted |
| `knockDoorway.init(...)`, `doorway-api.knockrentals.com/v1/property/<id>` | `knock_doorway` | Knock API | Needs the numeric property id from the network call, not the `community` id in `init()`. Units may carry no price |
| `jd-fp` | `jonah_detail_json` | detail-page JSON | |
| `ysi.floorplansList` | `rentcafe_inline` | JSON inside the page | Reads the crawler's saved copy first; RentCafe sites 403 plain requests |
| `a.show-inclusive-fee-button` | `rentcafe_inline` (fee buttons) | button attributes | Gives base, mandatory fees and total separately (FML_scraper Duval Villas) |
| `id="fp-container-<n>"` or `card-title` + `resource.rentcafe.com` | `rentcafe_inline` (cards) | server-rendered cards | 2026 RentCafe template (Dwell at 1600, 100 Park, Sundance/Sausalito). A card ends at its own "Schedule a Tour"; "Call for details" means no price |
| `"@type":"Offer"` JSON-LD with `itemOffered` | `jsonld_offers` | schema.org data in the page | Vendor-neutral; found on apts247 sites and all three ResMan sites, so ResMan needed no adapter |
| `cgsynergyapi…/api/community/<domain>` in network | `cg_synergy` | open JSON API keyed by site domain | Rev Northgate, The Tradition |
| `<x>.appfolio.com` | `appfolio_smart` | portal `markers` JSON | Match order: portal property filter by name → listing within 150 m of the building (markers carry lat/lng) → same street, number ±80. One address string misses complexes that span numbers (Richmond Ridge 3620 vs units 3628/3629). `$0` rents = unpriced |
| `SiteAlias` + `appfolio-listings` | `duda_appfolio_feed` | Duda collection | |
| `*.managebuilding.com` | `buildium_search` | ApartmentSearch Key/Value list | Whole-house rentals, priced per unit |
| `(reslife\|housing).<univ>.edu` page | `university_rates` | one rate page for every hall | Section picked by the building's name in a heading; keeps per person vs whole apartment and month vs semester; semester rates are not converted |
| `themes/landmark-`, `product-tile`, `floor-plan-card`, `fp-option-rates`, G5 … | browser parsers in `dom_extract.js` | rendered page | Headless first, saved Chromium profile second |
| none of the above | `text_plan_list` | printed lines "name / N bed \| N bath \| N sqft / $X" | Last deterministic step. Wins only with more priced rows. Junk names fall back to "N bed / N bath"; >60 rows means a multi-listing page and is rejected |
| page states only a range | `advertised_range` | "Starting at $X" | One row, labelled as a range (FML_scraper `fallback_range`) |
| Manager site with its own layout | `HOST_ADAPTERS`, or `listing_adapters` in the campus config | | |
| `data-ll-floor-plan-lease-terms` | `villas_wp` (DOM, synced from FML_Data `a953774`) | JSON on `[data-ll-floor-plan-card]`: `base_rent`, `price`, `price_with_fees` | The old `.floor-plan-card` selector returned no rows. The synced parser reads the attribute. An HTTP skim of the same JSON is not auto-selected: it under-counts and would block the DOM parser |
| `/wp-json/gmh-student/floorplans/categories` | `wp_entrata_json` with that `api_url` | GMH JSON | Torre. The theme path `/wp-json/theme/entrata/v1/floor-plans` is a different feed. `force_not_listed` is honored only when the pin sets it. FML_Data's current Torre pin does not set it |
| `housing.utexas.edu` path `nueces-rates` / `dobie` / other rate table | `ut_housing_nueces`, `ut_housing_dobie`, `ut_rates_table` | the rate table | `university_rates` is the generic fallback, not a replacement for these |
| `collegehouses.org` | `collegehouses_rates` | `https://collegehouses.org/rates/` | `params.house` selects the block. One fetch for every house |
| `product-tile` and a residence `gtm_name` | `yugo` | rendered tiles, one row per room type | Pin `gtm_name`. Not `text_plan_list` |

**Locked pins.** `listing_config.json` rows with `"locked": true` are the FML_Data source (backend, url, params, source_type, source_id). `write_listing_config` merges: detection adds unlocked buildings and does not replace a locked source. New buildings that discovery never ranked use status `ADD` in `resolutions.json` or `added_buildings.json`. `include_pinned.py` unions them into the enrich slice.

**Post-processing hooks** (`aggregator/listing_post.py`), driven by the pin:

| Hook | When |
|---|---|
| `clean_labels` | Icon. Merge overlapping Entrata cards and keep the copy that has the image |
| `no_public_pricing` / a label starting with `(` and `price_status=not_publicly_listed` | Keep the placeholder and `params.reason`. Do not drop it |
| `force_not_listed` | Inside `wp_entrata_json`. Clears rents only when the pin sets the flag |
| failure stub | No rows or a bad status becomes `(extraction failed)` with the status in `availability` |

**Rescue modes** (`aggregator/rescue_prices.py`), on a hand-saved file. Nobody solves a challenge.

| Mode | Meaning |
|---|---|
| `split_total` | Base and total monthly are both real. `price_basis` is `total` |
| `base_only` | One advertised figure |
| `promo_current` | Struck price is a `flat_discount`; the current figure stays in `base_rent` |
| `installment` | The per-installment figure is the rent, not a fee total |
| `unpriced` | Keep the plan, no invented rent |
| `empty` | Bot wall with no inventory. One unpriced stub |

**Production refresh** (`refresh_listings.py`) refuses `text_plan_list` and any `params.html_files`. Those re-parse a snapshot that is not on the bot. The run prints `saved_html_banned` and exits non-zero. Locked pins are emitted as the 20-column CSV and nested JSON FML_Data writes (`aggregator/legacy_emit.py`). Unit ids for the Algolia / discrepancy-updater shape are `{property-slug}__{label-slug}` in the sibling `*.unit_ids.json`. `source_type` and `price_status` are copied from the pin and the row. They are not rewritten.

**Frozen-adapter bug.** If an LLM read returns more priced rows than the adapter that just ran, `take_llm_if_better` clears `source_config`. The frozen file must not claim `text_plan_list` produced the LLM rows.

**Price basis.** `convert()` treats a total-only row (base blank, total present) as priced, so an Entrata "Total Monthly" card is not marked unlisted.

**When nothing matches: open the site once in the user's Chrome (Claude in Chrome).** This is
a build step, not a weekly one, and it is how five of the adapters above were found.

1. Open the floor-plans page. Read `performance.getEntriesByType('resource')` for XHR/fetch
   calls and look for the one that carries plans (rent, beds, sqft). Prefer a call to another
   host (Repli360, Knock, CG Synergy, SightMap): those hosts are not behind the property's
   Cloudflare, so the weekly run can call them directly. Write an adapter and a `NET_RULES`
   or `detect()` rule for it.
2. If the data is in the page itself (JSON in a script, JSON-LD, server-rendered cards),
   write a parser that reads the crawler's saved copy.
3. If the only route is a protected page (Entrata portals), save the rendered page:
   `window.name = html`, navigate the tab to `http://127.0.0.1:8767/send?name=<slug>` while
   `recv_pages.py` runs, then `rescue_from_page.py <campus> <slug> <backend>`. The rescue is
   a snapshot and is re-collected when the refresh report shows it failing.
4. Record what was found in `resolutions.json` (`floorplans_url`, `listing_note`), so the next
   build goes straight to it.
5. Tool limits: tool output stops at about 1,000 characters and blocks query strings, so return
   hosts and paths, not full URLs. Wait about 4 s after a navigation before running script
   (portals redirect across domains). A user-solved CAPTCHA does not carry over to headless
   runs: Cloudflare ties clearance to the browser fingerprint.

**What the LLM read got wrong, measured against the extractors:** The Jay 29 rows vs 41,
prices up to $70 low; Cambridge Hall 6 "priced" rows built from the price-filter dropdown, the
site publishes none; The Jane 0 priced vs 6. Keep it for case-by-case use only (`--llm`).

**Sites that publish no prices** (stay unpriced, not a parser gap): RealPage-managed
"liveat<name>collegestation.com" WordPress sites (plans plus "contact us about availability"),
Cambridge Hall, Lory of Bryan, Arena Group rooms (`$0`), pre-leasing buildings (The Penny).

Checks that run on every building (`coverage_flags` in `listings.json`, listed in the QC report
under "Listings likely undercounted"):

- A feed platform is fingerprinted but no adapter returned rows: a parser is missing or the
  markers changed. Fix the adapter; do not accept the LLM rows as complete.
- The page shows more distinct prices than twice the rows extracted.
- A building with no site of its own: the sister-feed pass checks whether a multi-building feed
  found through another building carries it. A building known only from a directory row stays
  unpriced and is flagged for a realtor / owner search by address.

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

### 4x. Floor-plan images: capture, contingencies, QC (`aggregator/plan_images.py`, VERSION 10)

Why this section exists: `docs/POSTMORTEM_PLAN_IMAGES_2026-11-24.md`. On A&M, 368 plans across 60 buildings had no
image. The images were mostly in pages we had already saved, but the extractors dropped them.

**Rules**

- Every plan row should carry `layout_image_url`, or a recorded reason why it can't.
- Run every step below in order and stop at the first that passes the gates. No LLM reads. No external browser, VM or
  Chrome extension. Steps marked (HTTP) are plain requests with the full Chrome UA in `plan_images.UA`; a short UA
  gets 403 on some hosts.
- An adapter that has the image must return it. The post-pass is a safety net, not the primary source.

#### A. At crawl time (page discovery, §2e): save what the image steps need

| Step | Method | Notes |
|---|---|---|
| A1 | Save the floor-plans page itself, not just the home page. Find it from the nav link "Floor Plans", then the `FP_PATHS` probes: `/floor-plans/`, `/floorplans/`, `/rates-floorplans`, `/models`, `/apartments`, `/units`, `/availability`. | Brazos Oaks had only `home.html`; its `/floor-plans/` page lists every plan in JSON-LD. |
| A2 | (HTTP) Read `sitemap_index.xml`. If missing, try `/wp-sitemap.xml`, then `/sitemap.xml`. Save every URL under `/floor-plans/<x>/`, `/floorplans/<x>/`, `/floor_plans/<x>/` or `/units/<x>`, plus the `<image:loc>` list for each. | Yoast and Rank Math sitemaps list each plan page with its images (Charleston: `/floorplans/magnolia/` -> `Magnolia-1st-Floor.jpg`). |
| A3 | Keep raw HTML whole. Do not strip `<noscript>`, `<picture>`, `<source>`, `data-*` attributes, or JSON-LD/state `<script>` blocks. | Tower Park's only real `src` is inside `<noscript>`. |
| A4 | Keep the `fingerprint.json` network log; the steps below replay it. | |

#### B. Primary: the leasing platform's own feed (adapter), then structured data

| Step | Source | Field with the image |
|---|---|---|
| B1 | Platform feed adapters (§4 catalog) | `cg_synergy`: `files[].source` (`fileType: Floorplan`); `sightmap`: floor plan image in the unit API; `acc_lightning`; `repli360_feed`: card `<img>`; Entrata `fp-card`: `<a data-url>` (full size) or `fit-in/WxH` img; G5 inventory GraphQL; Knock; RealPage CMS; `jd-fp`. If you add or fix an adapter, map its image field and test it returns images. |
| B2 | schema.org `FloorPlan` JSON-LD (`jsonld_floorplans`) | `layoutImage` per `name` / `isPlanForApartment` |
| B3 | schema.org `Offer` JSON-LD (`jsonld_offers`) | `itemOffered.accommodationFloorPlan.image` |
| B4 | (HTTP) Replay the JSON/XHR calls recorded in `fingerprint.json` (§A4) | plan objects carrying `image`, `imageUrl`, `floorPlanImage`, `layoutImage`, `media`, `files` |
| B5 | Embedded app state in the saved HTML: `__NEXT_DATA__`, `__NUXT__`, `window.__INITIAL_STATE__`, Wix warmup data, Duda collections | plan name next to an image URL in the same object |
| B6 | (HTTP, WordPress) `/wp-json/wp/v2/<plan post type>?per_page=100&_embed` -> `_embedded["wp:featuredmedia"][0].source_url`. Find the type at `/wp-json/wp/v2/types`. | Often not exposed (`rest_no_route` on the Elementor template). Optional. |

#### C. Fallback: the saved HTML (`attach_images` -> `plan_images.find_images`, runs after every adapter)

| Step | Method | Catches |
|---|---|---|
| C1 | `<img>` whose alt or title is the plan name | Tower Park "Floor Plan A", Duda/Wix |
| C2 | DOM card walk: the deepest element showing the plan name, climb to the first plan-like image, stop at another plan's name; duplicate names must also match their sqft | most templates (Elementor, Entrata, Webflow, RentCafe cards, ion, Rise) |
| C3 | Unique beds/baths in the alt text ("2 Bedroom, 2 Bathroom") | Razz unit lists labelled "Unit 132" |
| C4 | Beds-baths in the file name (`floorplan_whitecreek_4-2`). Also drops a pick whose file name disagrees with the plan. | TAMU reslife (captions under the images) |
| C5 | One plan plus exactly one image the page calls a floor plan | Fox Meadows |
| C6 | (HTTP) Follow the card's link to the plan's own page and take that page's plan image. Also used when C2 found a photo. | Charleston Mills |
| C7 | Image URL clean-up before use: largest `srcset` entry (split on ", " because Wix URLs contain commas); `data-src`, `data-lazy-src`, `data-iesrc`, `<source>`; WordPress `-300x300` -> original; Wix `/v1/fill/...` -> original; Uploadcare `/-/preview/...` -> original; relative -> absolute with the page URL; `http` -> `https`; follow redirects to the final URL. | |

#### D. When the page itself is blocked or empty

| Step | Method |
|---|---|
| D1 | (HTTP) Fetch the feed or image host directly; it is usually not behind the site's bot wall (Entrata `medialibrary*.entrata.com`, `resource.rentcafe.com`, `app.repli360.com`, CG Synergy API). |
| D2 | (HTTP) Entrata portal path `/<city>/<slug>/student/` or `/conventional/`, on the property domain and on `*.prospectportal.com`. |
| D3 | (HTTP) The same page from the sitemap's `<image:loc>` list (§A2). The image host is often open even when the page isn't. |
| D4 | (HTTP) Last snapshot from the Wayback Machine (`web.archive.org/web/2026/<url>`) to find the image file name. Check that the image URL still answers today (gate G1). Mark the row `layout_image_how: archived page`. |
| D5 | PDF only ("Download Floorplan PDF", Lark): render page 1 locally (`pdftoppm -png -r 110 -f 1 -l 1`), upload with `upload_listing_image`, keep the PDF as `source_url`. Use this only when no image exists. |
| D6 | Hand-checked override in `data/<campus>/plan_image_overrides.json`, for sites that print the plan name only inside the image (Richmond Ridge). Match on `name_regex`, `sqft` or `beds`; record `checked` and `source`. A person looks; no LLM. |
| D7 | Give up with a reason: record `pricing_only`, `vacancy_listing_photos_only`, `bot_wall` or `no_plan_page`, with the page URL. Rows stay without an image and are not retried every week. |

#### E. Gates every image must pass (no LLM)

| Gate | Rule |
|---|---|
| G1 | `image_gate()`: HTTP 200, decodes as an image, at least 200x150, final URL after redirects. Reads up to 40 MB (some plan PNGs are over 15 MB). |
| G2 | Border uniformity of 0.40 or more counts as a plan (diagrams and 3D renders sit on one flat colour). Below 0.40 counts as a photo. 11-24 sample: 273/273 plans scored 0.43 or more; 9/9 photos 0.35 or less. If a photo-like image came from C2, try C6. If it was only the card's image, drop it. Otherwise keep it and flag `check by eye`. |
| G3 | Reject by file name or alt: logo, icon, `coming[-_ ]soon`, placeholder, `.svg`/`.gif`, cover, exterior, hero, banner, gallery, photo; unless the name or alt says "floor plan". |
| G4 | An image used by 60% or more of a building's plans (and at least 3) is page chrome; drop it. |
| G5 | Beds/baths in the file name must agree with the row (C4 veto). |
| G6 | Before any push to RMR, a person looks at a contact sheet of every new image (labelled grid, as in the 11-24 run). Rows flagged `check by eye` never go up unreviewed. |

#### F. Matching rows to RMR plans when pushing

- Match by plan name with "[Per Installment/Person]" and parentheses removed, plus beds. Also try the version with
  the parentheses kept: "5 Bath* (Standard)" = "5 Bath - Standard".
- Unit rows "Unit 0205 (2 bed/1 bath)" take the image of the plan named inside the parentheses.
- Plan names that the site spells differently ("1x1 Lg" vs "1 Bedroom Large") go to manual review. Don't guess.

#### G. Flags and QC

- `coverage_flags`: `plan_images_missing:N/M`, `plan_images_check_by_eye:N`, `plan_images_error:...`.
- `qc_report.md` should list image coverage per building and for the campus (to do, from the post-mortem).
- Each row records `layout_image_how`: the step that produced it.

## 5. Photos (`reference/photo_pass/`)

CONFIRMED by test (second-campus pass, 2026-11-16, 162 buildings). 100 buildings had no
property photo. A first pass that read only home pages filled 54. Reading gallery pages and
falling back to a listing site filled 71 (this fallback is withdrawn; see 5b step 5). The remaining 29 each have a recorded reason.

### 5a. What a property photo is

A photo of the place: entrance sign, building exterior, grounds, pool and other amenity
spaces, a unit's rooms. Set `kind` to one of `sign, exterior, grounds, amenity, interior,
rendering`.

Not a property photo, never stored in `photos[]`:

- Floor plans, 3D layout renders, site maps. They belong on unit rows.
- Logos, text banners, pattern backgrounds, promo graphics.
- Stock lifestyle images (people laughing, coffee cups, a bicycle against a wall).
- Staff portraits and team photos.
- The campus, the stadium, the water tower, the neighbourhood, a skyline.
- A photo with a large logo or badge laid over the building.
- Photos of other properties. Manager and realtor sites show their whole portfolio, and
  some property sites still carry image files named after a different property.

Count them separately everywhere. "Has an image" is not a useful number: a building with
six floor-plan drawings and nothing else has no photos. Report `with_property_photo`,
`with_layout_image_only`, `with_nothing`.

Renderings are allowed for buildings not yet open, with "Rendering:" at the start of the
caption. Virtually staged rooms say so in the caption.

### 5b. Where the photos are

In order. Do not stop at the first page that has an image.

1. The gallery page (section 2e). Then amenities, then the home page, then one floor-plan
   detail page for interiors.
2. Read every way a page can carry an image, not just `<img src>`: `srcset` (take the
   largest), `data-src` and other lazy-load attributes, CSS background images, lightbox
   links, and image URLs inside script JSON. Scroll the page first when in a browser.
   Gallery pages on hosted leasing platforms render two or three `<img>` tags and keep the
   rest in script data.
3. Normalise CDN URLs to one full-size variant (about 1,600 px wide). Many CDNs encode the
   crop in the path; a 70 px thumbnail and the original are the same photo.
4. Sister properties on one site: use each property's own sub-page. Use shared photos (a
   shared pool or clubhouse) for both only when the site presents them as shared.
5. **Fallback when the building has no usable site:** its operator's or local realtor's page for
   it. Do not use a listing aggregator (Zumper, Zillow, Apartments.com, RentCollegePads, a campus
   directory) as a photo source. A building with no site and no realtor page is recorded with
   a reason (`no_site_found`, 5e) and left without photos.

### 5c. Filters before the visual check

- Minimum 500 px wide and 300 px tall. Small condo and owners' association sites top out
  near 450 to 600 px; a 700 px floor drops their only real photos.
- Aspect ratio between 1:1.6 and 3.2:1.
- Drop images that are more than half near-white or near-black (floor plans, logos).
- De-duplicate by content hash, then by a perceptual hash, per building.

These filters only cut the pile. They do not decide what is a property photo.

### 5d. The visual check is mandatory

File names, alt text and captions are not evidence of what an image shows. Make numbered
contact sheets (`sheet.py`) and have a vision-capable reviewer look at every candidate
before anything is stored. In test the look caught, among others: stock people on a third
of sites, a T-shirt shop on a lapsed domain, gambling adverts, a manager's office building,
a neighbouring property's clubhouse set, a tenant's cluttered snapshots, and a building
photo covered by a logo.

When the look shows the site is not this property at all, go back and fix `website_url`
(section 2c). The photo pass is the best website check there is.

### 5e. Selection and done-ness

- Store 4 to 5 per building, in this order: sign or exterior, grounds or pool, an amenity
  space, a unit interior. The first one is the cover.
- One outdoor photo of the place matters more than five room shots. If only interiors
  exist, keep looking through 5b before settling.
- Caption each with what it shows ("Swimming pool and clubhouse"), not marketing text.
- Keep `source_url` and `source_type` (`own_site, operator_page`) on every
  photo so a set can be pulled if an owner objects.
- A building is done when it has 3 or more property photos, or a reason from this list:
  `no_site_found, site_has_no_photos, site_blocked, only_layouts, only_stock,
  not_yet_built, wrong_entity`. Fewer than 3 with no reason means the ladder was not
  finished.

<!-- VERBAL NUANCE: -->

## 6. Final build and QC (`build_json.py`)

Outputs in `data/<campus>/out/`: `buildings.json`, `amenities.json`, `units.json`,
`qc_report.md`. The shapes mirror the three UT catalogs the app reads (buildings, amenity
scores, units).

### Publish gate

A first pass must be clean before it is big. Every building gets `publish_status`:

| Status | When | Effect |
|---|---|---|
| `publish` | Identity verified: a street address, plus an accepted website (2a) or two independent listing sources that agree on name and address | Shown |
| `hold` | Real, but not ready: not yet built or open, or identity verified but nothing else found | Kept in the data, not shown |
| `drop` | Not a building for this product, or cannot be verified | Removed from the output, kept in a rejects file with the reason |

Drop reasons: `no_address_no_source` (a name with nothing behind it after the full ladder),
`duplicate_rebrand`, `locator_or_service`, `non_residential`, `not_housing_hub` (an
institution's dining or services building), `out_of_range`.

An unknown entry does more harm shown than missing. A name with no address, no site and no
listing page is dropped, not published empty. The 150 target in Playbook 1 counts
`publish` rows only; do not pad it with holds or unverified names.

Report at the end of every run: counts by `publish_status` and reason, by `website_class`
and `website_status`, `website_url` values shared by more than one building, and the three
photo counts from section 5a.

Per-building checklist:

- [ ] Name is the building's own, not a unit title or a management company
- [ ] Aliases include former names, the Google name if different, the street-address name
- [ ] Coordinate method is not `pin_unverified`; `coord_review` items were checked by hand
- [ ] The point sits on the residential building, not the leasing office
- [ ] Website is the building's page, not a manager's home page, a directory or a listing
      site; it was fetched this run and its text names the building's address or city
- [ ] At least 3 property photos checked by eye, or a recorded reason; no layouts among them
- [ ] `publish_status` is set, with a reason when it is not `publish`
- [ ] Amenity count is plausible for the building's size; zero means "unknown", say why
- [ ] Every amenity has a quote and a source URL
- [ ] Rent basis is set on every row; no guessed prices
- [ ] Blocked sites are listed for manual capture

<!-- VERBAL NUANCE: -->

## 7. Run order

```
python3 resolve_website.py --roster <rows.json>    # buildings with no accepted website
python3 enrich_site.py <campus> [roster_file]
python3 enrich_amenities.py <campus> [roster_file]
python3 enrich_listings.py <campus> [roster_file]
python3 build_json.py <campus> [roster_file]
python3 eval_amenities.py <campus> <legacy amenities_features.json>   # UT only
```

Photos are run by hand for now; see `reference/photo_pass/README.md`.

<!-- VERBAL NUANCE: -->
