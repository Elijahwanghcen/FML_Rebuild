# Prompt: Reverse-engineer + rebuild the FML campus listing aggregator

## Goal
We are rebuilding Find My Lease's listing aggregator so it can be stood up at a NEW campus
(large SEC schools first). The UT Austin build in `~/FML_scraper` grew slowly from
student-submitted rents. A new campus won't have that, so buildings must be discovered from
scratch. Your job: reverse-engineer what the UT build did (including the small, non-obvious
care that made the data accurate), prove a blind process can reproduce it, then write it up
as two playbooks. Another Claude will refine your MDs, and an AI will then use them to build
the final aggregator. Write for an AI reader: explicit steps, decision rules, file:line
evidence, no vague advice.

## Inputs (read-only, never modify)
- `~/FML_scraper` (rentright_buildings/, amenities_scored/, austin_leases_units/,
  properties.csv = 143-building roster, RESTRUCTURE_CHANGELOG.md, every README /
  CLAUDE_BUILD.md / CLAUDE_WEEKLY.md / qc_report.md, config files, AND git history:
  `git log -p` often shows why something was fixed)
- Other repos if they hold vital rebuild logic (aliases, coords, entity resolution, catalog
  shape): `~/rate-my-rent` (building aliases, coordinates), findmylease Algolia catalog,
  UT Housing Hub entity resolution, RMR_processing `properties.csv` whitelist.
- OUT OF SCOPE: student reviews and student rent reports (they won't exist at a new campus).

## Tools + constraints
- Live web OK. Use Playwright first (global install: `NODE_PATH=$(npm root -g)`). If
  Cloudflare or a bot wall blocks it, fall back to Claude in Chrome.
- Google Places API: key in env var `GOOGLE_PLACES_API_KEY`. Never write the key into any
  file, log, or MD. Log every Places call (endpoint + count) and stop to ask if estimated
  spend goes over $25.
- Write all outputs under `~/FML_rebuild/`. Don't touch existing repos.

## Scope rules (what counts as a building)
- INCLUDE, in priority order: (1) purpose-built student housing, (2) conventional apartment
  complexes students commonly rent, (3) co-ops and private dorms, (4) condo buildings with
  a real rental market (often found through local realtor/property-manager sites, e.g. UT's
  condos like Vanderbilt came via uptownrealtyaustin.com; find each campus's equivalent).
- EXCLUDE: Greek houses, single standalone houses, anything more than a 30-min drive from campus.
- Area = the campus's commonly named student neighborhoods (UT: West Campus, North Campus,
  Hyde Park, Riverside, etc.). For a new campus, work out these names from Reddit, the
  university's off-campus housing pages, and realtor sites.
- Target: at least 150 buildings for large SEC campuses (firm floor). If a smaller campus truly
  has fewer (~90), that's acceptable, but show evidence that the search was exhausted.

## Field nuance from the user (high priority: bake into both playbooks)
These are lessons the user learned building UT by hand. Treat them as rules, and look in the
repos for evidence of each one.

**Coordinates are the hardest part and the most important.**
- Don't trust coords from property sites, aggregators, or plain geocoding. They often come
  from Google's default geocoder, which pins the street-address centroid, not the building.
- The user's method: open Google Maps, find the actual building, right-click it, and copy the
  exact lat/lng to at least 5 decimal places.
- Automate this as far as possible: Places API place pin → check it against the satellite/map
  view of the actual building footprint (Claude in Chrome / Playwright screenshot) → correct it
  by hand if it's off. Record `coord_method` (manual_rightclick / places_verified /
  geocode_unverified) and never ship geocode_unverified as final.
- Multi-building complexes and buildings with a leasing office somewhere else need extra care:
  pin the residential building, not the office.

**Listings are often unstructured. Read them liberally.**
- Many sites, especially small realtor sites like uptownrealtyaustin.com, offer no JSON/XML
  feed or API. Parse the HTML loosely (prose descriptions, tables, free text) and OCR
  screenshots when prices or plans exist only as images.
- If a listing has no layout image or no floorplan detail, accept that as everything the
  source offers. Record what's there, leave the rest blank/unknown, and don't invent it.

**Discovery sources.**
- Reddit has been a strong source for apartments: students name buildings, nicknames, and
  complaints. Mine campus subreddits and housing threads.
- Condos are more hidden. Comb small local realtor / property-manager sites (Uptown Realty
  type) and find others in each new area that use different listing platforms (AppFolio,
  Buildium, Rentvine, ShowMojo, plain HTML, etc.). If a condo's address is inside the target
  neighborhoods, add it.

**Amenities: chase the implied and the tiny.**
- Lots of amenities are only implied in marketing text (e.g. "pet spa" → pet washing station,
  "game day on the big screen" → jumbotron/theater). Pull those out, not just bulleted lists.
- Hunt for small or rare amenities by name: pool, rooftop lounge, yoga studio, dance room,
  spin/cycle room, hot tub/jacuzzi, sauna, pet shower/washing station, jumbotron, golf
  simulator, study rooms, package lockers, etc.
- Review photo galleries and virtual tours with vision to confirm amenities the text doesn't
  mention (sauna, spin room, hot tub).
- Use unit count / building size as a prior. A large building with many listings probably has
  a big amenity set, so search it exhaustively (amenities page, gallery, tour, Google
  photos/reviews). The prior decides how hard to look, not what to record: an amenity
  without evidence stays `unknown`, not `present`.
- Record evidence per amenity: `stated` / `implied_text` / `seen_photo`, plus the source URL.

## Target per-building schema
canonical_name, aliases[] (rebrands, former names, street-address names, student slang,
sub-buildings of one complex), address, lat/lng (exact building pin, at least 5 decimals, not a
geocoded street address) + coord_method + google place_id, unit_count, website_url, management_company, site_platform
(Entrata/RealPage/AppFolio/Yugo/...), building_type (student/conventional/co-op/private
dorm/condo), neighborhood, distance_to_campus, amenities (3-state: present / absent /
unknown, never treat unknown as absent; each with evidence type stated/implied_text/seen_photo
+ source URL), floorplans (beds, baths, sqft, plan image), rent +
rent_basis (per-bed vs per-unit) + concessions, photos, source_urls[] (provenance for every field).

## Phase A: Reverse-engineer the UT build (evidence)
Mine code, configs, qc reports, changelogs, and git history for every non-obvious technique
and failure mode. At minimum cover:
- Coordinates: how exact pins were captured (e.g. copied from the Google listing), where
  geocoding failed, and how multi-building complexes were pinned.
- Aliases + identity: rebrands (ion → University House, Ballpark East → Collective on
  Riverside), same-name collisions (Elan 24 ≠ Elan East), one site serving many buildings
  (The Block via LocationFilter), many names for one building, price-file aliasing.
- Amenities: where the facts really live (Entrata /amenities/ one path segment above
  /student/, photo-tour captions, prose descriptions on realtor sites, HousingScout
  li.yes/li.no), the 3-state rule, and marketing-mention bias (e.g. AC looks rare only
  because nobody advertises it).
- Listings/rent: per-bed vs per-unit basis, strikethrough discounts, image-only prices,
  concession popups, defunct/stale detection, platform APIs (SightMap, RentCafe ysi, Knock,
  RealPage proxy...).
- Blocking: which sites were walled and what beat them.
Mark each finding CONFIRMED (cite file:line or commit) or INFERRED.

## Phase B: Blind discovery test on UT (no peeking)
1. Without reading properties.csv, independently discover every qualifying building around
   UT using only sources available at a new campus: Google Places (grid/text search across
   the neighborhoods), Google Maps, local realtor + property-manager sites, and Reddit (r/UTAustin and similar threads, for slang
   names and buildings people complain about or recommend). Listing aggregators (apartments.com, Zillow,
   HotPads, Zumper, HousingScout) and the university's off-campus directory (RentCollegePads / CoStar) are
   NOT scraping destinations for any fact about a building; at most the directory is a lead list of
   names and addresses (docs/PLAYBOOK_1_DISCOVERY.md Source 4).
2. Record which source(s) found each building. Save as `ut_blind_roster.csv`.
3. Only now compare against the 143-building roster (+ any other repo catalogs). Report:
   recall (roster buildings you missed), extras (found but not in the roster: are they valid?),
   per-source coverage %, the smallest source combo that reaches 95% or more, and buildings
   that only one source found.
4. For every miss, diagnose WHY (wrong name, outside your radius, condo only on a realtor
   site, not tagged "apartment" in Places, etc.) and add a search rule that would have caught
   it. Re-run until recall stops improving. These rules feed Playbook 1.

## Phase C: Enrichment accuracy test on UT
Pick about 20 roster buildings spanning every platform and building type. Rebuild their
coords, aliases, amenities, and listing fields independently using the Phase A techniques
(the existing scrapers can be reused as-is; no need to rewrite them). Diff your results
against the current master/catalog output and report agreement per field. For coords, report
the distance in meters between your pin and the existing pin, and also measure how far plain
geocoding would have been off. That number shows why the manual-pin rule exists. For
amenities, report how many came from implied text or photos and wouldn't have been found by
reading lists alone. Every
disagreement either becomes a new rule or is explained.

## Phase D: Pilot on Texas A&M
Run Playbook 1 on Texas A&M (College Station; work out the neighborhood names, e.g. Northgate,
Southside, Wolf Pen Creek, Harvey Rd / Holleman corridors). Report the count reached vs the 150
floor, the source breakdown, and the condo/realtor sources found. Enrich a sample of about 10
buildings with Playbook 2 and list what broke. Save `tamu_roster.csv`.

## Deliverables (in ~/FML_rebuild/)
1. `PLAYBOOK_1_DISCOVERY.md`: campus-agnostic process to find all qualifying buildings:
   defining neighborhoods, sources in priority order, Places query/grid strategy, Reddit
   mining, realtor/condo hunting, dedupe + alias resolution, inclusion/exclusion rules,
   completeness checks, and the stop condition. Include UT blind-test metrics + miss analysis
   and TAMU pilot results as evidence.
2. `PLAYBOOK_2_ENRICHMENT.md`: how to get exact location, aliases, amenities, and listing/rent
   data for each building: per-platform recipes, the 3-state amenity rule, rent-basis rules,
   anti-bot fallbacks, QC checklist per building, and the target schema. Include Phase A
   findings + Phase C accuracy table.
3. Data: `ut_blind_roster.csv`, `ut_coverage_diff.csv`, `tamu_roster.csv`, `places_call_log.csv`.
Each MD section ends with a `<!-- VERBAL NUANCE: -->` slot for the user to add notes later.
Start each MD with a short "known gaps / open questions" list.

## Working style
- Checkpoint after Phase A and after Phase B with a short summary, then keep going.
- Don't guess facts. If something can't be verified, mark it unknown and say why.
