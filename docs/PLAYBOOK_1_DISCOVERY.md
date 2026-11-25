# Playbook 1: Find every student-relevant building around a campus

Audience: an AI agent (or engineer) standing up the listing aggregator at a new campus.
Goal: a deduplicated roster of **150+ buildings** (purpose-built student housing first, then
conventional apartments students rent, co-ops and private dorms, then condo buildings), each
with a canonical name, aliases, address and an owned coordinate. No Greek houses, no single
houses, nothing more than a 30-minute drive away.

Everything here was tested by rebuilding UT Austin blind (without looking at the existing
143-building roster) and then scoring against it. Code lives in `aggregator/`. Measured
results are in `docs/RESULTS.md`.

## Known gaps / open questions

- Reddit cannot be read unattended (see Source 5). It needs the user to log in once per machine.
- Listing aggregators (ILS) are not scraped for anything: not apartments.com / CoStar, Zillow,
  Redfin, Zumper, not RentCollegePads, not CoStar-run campus directories (aggiesearch.tamu.edu).
  `common.is_ils()` lists them. Rent, floor plans, amenities, photos and a building's website
  come only from the building's own site or from a local realtor / property-manager firm
  (Uptown Realty in Austin, Westside Group, a College Station PM). The one remaining use of a
  campus directory is a lead list in Source 4 (name, address, coordinates).
- The student-relevance ranking is a heuristic tuned on one campus (UT). Treat the tier cut-offs
  as a starting point.
- Buildings far outside the named neighborhoods (UT had ~12 at 5–40 km, added by student rent
  submissions) are not discoverable by area search. They only arrive through Reddit mentions
  or later user submissions.
- Discovery produces names. It does not prove each name is a real, separate, residential
  building. The verification rules in section 5a are specified and are not yet enforced by
  `select_roster.py`; a second-campus check found duplicates of rebranded buildings, a
  locator service, an office centre and names with nothing behind them in the roster.

<!-- VERBAL NUANCE: -->

## 0. How the UT roster was really built (and why that can't be repeated)

The UT list of 143 grew from student-submitted rents over time. Each new name was then looked
up by hand. A new campus has no submissions, so discovery has to be done from area sources.
The blind test below shows which sources replace the student signal.

<!-- VERBAL NUANCE: -->

## 1. Write the campus config (`campuses/<slug>.json`)

Fields: `name`, `short` names, `city`, `state`, `center` (lat, lng of the academic core),
`core_radius_m`, `max_radius_m` (30-minute drive cap; 15 km for a college town, 30 km for a
metro), `neighborhoods` (name, center, radius), `subreddits`, `city_words` (stripped when
comparing names), `neighbor_cities` (every other city or town inside `max_radius_m`),
`rcp_urls` / `ocp_base` (campus directory), `extra_pm_sites`.

`neighbor_cities` matters more than it looks. Student housing routinely sits across a city
line. Any search, site check or address match that uses only the campus city fails for
those buildings: the query returns listing sites only, and the building's own page (which
names the other city) is rejected as "wrong town". Always take the city from the
building's address first and fall back to this list.

How to choose neighborhoods:

1. Run Source 1 (Google Places) once over the whole `max_radius_m` and bucket the residential
   results on a 0.01° grid. The dense cells are the student neighborhoods (A&M: Northgate,
   Holleman/Jones Butler, Wolf Pen Creek, the Barracks area). The directory lead list in
   Source 4 shows the same clusters if you already have it.
2. Cross-check names with the campus subreddit wiki/FAQ ("where should I live") and the
   university's off-campus housing page.
3. Give each neighborhood a center and a radius that covers its cluster. Overlap is fine.

Dense urban campus (UT): `core_radius_m` 2,600. Spread-out college town (A&M): 3,500 plus
several outlying neighborhoods.

<!-- VERBAL NUANCE: -->

## 2. Sources, in the order to run them

| # | Source | Script | UT roster found alone | What it is good for |
|---|---|---|---|---|
| 1 | Google Places (New) grid + text search | `discover_places.py` | 86% | The backbone. Finds almost everything that has a Google listing |
| 2 | Overture Maps places + buildings + addresses | `discover_overture.py` | 26% | Weak for discovery; essential for free coordinates and for finding realtor offices |
| 3 | Local realtor / property-manager sites | `discover_pm_sites.py`, `resolve_addresses.py` | adds condos | The only way condos without a Google listing appear |
| 4 | Campus off-campus directory (LEAD LIST ONLY) | `discover_rcp.py`, `discover_ocp.py` | strong student signal | Names, addresses, coordinates. Never rent, floor plans, features, photos or a website |
| 5 | Reddit | `reddit_fetch.js`, `discover_reddit.py` | student signal + nicknames | Which buildings students actually talk about, slang names |

Combined UT result: **128 of 143 (90%)**. Of the 15 misses, 12 are 4–40 km from campus and
outside every named neighborhood, and 3 are in range (see section 5).

### Source 1: Google Places

- **Nearby Search returns at most 20 results and has no paging.** A fixed grid silently
  truncates dense blocks. Use a quadtree: search a square; if it returns 20, split into four
  and recurse until a cell is not full or is under 70 m. Types:
  `apartment_building, apartment_complex, condominium_complex, housing_complex`.
- Run the quadtree over the core square and over each neighborhood.
- Then Text Search (3 pages = 60 results) per neighborhood for: student apartments,
  apartments, student housing, condominiums, condos for rent, housing co-op, private
  dormitory, apartment complex. This catches places Google types as something else. Dobie
  Twenty21 (a private dorm) is typed `shopping_mall`.
- Cache every response and log every call (`places_call_log.csv`). UT cost about $18 at list
  price for ~525 calls.
- Store only `place_id` long-term. Google's terms allow lat/lng for 30 days and nothing else.
  Use the pin to pick a building outline, then store the outline's center (Playbook 2).

Filters applied to Places results (`merge_candidates.py`):

- Drop hotels, lodging, hostels, schools.
- Drop names that are companies, not buildings (realty, management, locators, LLC, group).
- Drop listing titles posing as places ("Massive 1,670 sqf West Campus Condo - 11min Walk to UT").
- A non-residential type is kept only if a student-housing text query returned it and it is
  inside the core; it is flagged `needs_review`.

<!-- VERBAL NUANCE: -->

### Source 2: Overture Maps (free, storable)

`overturemaps download --bbox … -t place|building|address`.

- `place`: residential categories become weak candidates. Realtor / property-management
  places within `pm_radius_m` of campus become the site list for Source 3. Uptown Realty
  (the source of 32 UT condo buildings) was found this way, not through Places types.
- `building`: footprint polygons with height. Used for coordinates and size.
- `address`: US National Address Database points. This is a free rooftop geocoder (Playbook 2).

The Overture schema changes between releases. In late 2026 the category lives in
`basic_category` and `taxonomy.primary`, not `categories.primary`.

<!-- VERBAL NUANCE: -->

### Source 3: Local realtor and property-manager sites (where condos hide)

Condos are individually owned. They have no leasing office, often no Google listing, and no
website. They do appear on the "communities" or "properties" page of the two or three local
firms that lease them (UT: uptownrealtyaustin.com, gbatx.com, westsidegroup.com,
condojoe.com, realtyprosaustin.com).

Site selection rule (campus-agnostic):

1. Any Places or Overture candidate near campus typed real-estate agency / property
   management, or whose name contains realty, properties, management, leasing, locator.
2. Any website domain shared by two or more residential candidates (portfolio operators such
   as American Campus, Yugo, a local co-op network).
3. A few web searches per campus: "<neighborhood> condos for rent <city> property management",
   "<campus> pre-lease condos". Add what turns up to `extra_pm_sites`. AppFolio portals
   (`<firm>.appfolio.com/listings`) show up here and parse well.
4. Deny list: national brokerages, short-term rental brands, social media, commercial real estate.

Then for each site, two passes:

1. **Sitemap pass (no LLM).** Read `/sitemap.xml`, keep sub-sitemaps whose name says
   communities / properties / buildings / condos (skip posts, agents, per-unit rentals and homes
   for sale), and take every page in them as one building: name from the page's `<h1>`, url kept.
   This is how a firm with 30+ condo pages is covered completely. UT: uptownrealtyaustin.com has
   a `communities-sitemap.xml`; the home page plus four portfolio pages through an LLM found only
   12 of its communities and mislabelled others.
2. **Portfolio-page read.** The home page plus up to four links that look like portfolio pages
   (communities, properties, listings, condos, availability), text handed to an LLM for
   `{name, address, type, url}` of multi-unit buildings in the city. Read liberally: some firms
   have no sitemap.

Local realtor / PM firms are read like a first-party site later on: their per-building page is
the website seed when the building has no site of its own, and the firm's page parser
(`uptown_realty`, `westside_prose`, AppFolio portals) supplies rent. They are not aggregators.

Follow-ups that mattered:

- Many pages give a name with no address. `resolve_addresses.py` opens the building's own
  page on that site and takes the first street address that exists in the NAD index. An
  address that appears on more than three building pages of one site is the firm's office
  and is ignored. UT: 67 of 267 name-only candidates recovered.
- A listing titled "ADDRESS Unit 203" is a unit, not a building. Strip the unit and use the
  street address as the name. It will merge with the building later by address.

UT numbers: 243 sites picked, 116 returned buildings, 776 raw candidates.

<!-- VERBAL NUANCE: -->

### Source 4: Campus off-campus directory (lead list only)

The university's off-campus housing directory (RentCollegePads or its white-labels such as
housing.offcampus.utexas.edu, or a CoStar / Off Campus Partners site such as aggiesearch.tamu.edu)
is a listing aggregator. It is **not a scraping destination** for anything about a building.

What it may be used for: knowing that a building exists. `discover_rcp.py` / `discover_ocp.py`
keep only name, street address, coordinates and the per-bed flag, and `merge_candidates.py`
uses them as one more source family for dedupe and for the student-relevance score.

What it may not be used for, anywhere in the pipeline:

- Rent, floor plans, availability. There is no directory fallback in `enrich_listings.py`. A building
  whose own site or local realtor shows nothing is `not_publicly_listed`.
- Amenities / feature checklists, photos, management company.
- The building's website. A directory URL is never a seed: `merge_candidates.py` drops any
  aggregator URL from `website`, and `enrich_site.py` refuses one as a crawl seed.

How the real data is found instead (this is what the original FML scraper did): follow the
building to wherever it actually leases. Two cases.

1. Purpose-built and conventional communities: the community's own website, then its leasing
   platform's feed (Playbook 2 section 4).
2. Condos and small buildings with no site: the **local realtor / property-manager firm** that
   leases them. UT: uptownrealtyaustin.com has one page per condo (`/communities/<slug>/`) and
   the original scraper read each one directly. Source 3 finds those pages (see below).

If a directory is the only place a building appears, keep the row as a lead (`REVIEW`) and look
for its owner or realtor by address. Do not copy the directory's numbers.

Dropping Source 4 entirely costs discovery recall, not data quality. To run a campus without it,
leave `rcp_urls` / `ocp_base` out of the campus config.

<!-- VERBAL NUANCE: -->

### Source 5: Reddit

Students name the buildings they live in, including nicknames ("Callaway", "26 West",
"Villas on St Gabe").

Access: script requests get 403, headless and automated Chrome get a human check, the
`.json` endpoints return 403 even when logged in, and both the Claude Chrome extension and
web search refuse reddit.com. What works: `reddit_fetch.js` opens a normal Chrome window
with its own profile, the user logs in once, and the script reads old.reddit.com search
pages and threads as rendered HTML at a slow rate.

Queries per subreddit: apartment recommendations, best apartments, where to live,
"<neighborhood> apartment", condo, co-op, apartments to avoid, worst apartment, housing
advice, cheap apartment, quiet apartment, private dorm, apartment review, which apartment.
Read the 120 most-commented threads.

`discover_reddit.py` then asks an LLM for building names per thread, counts threads per
name, and looks up names no other source has with one Places Text Search each (only names
in two or more threads). UT: 120 threads, 187 distinct names, 88 in two or more threads,
23 lookups, 16 located.

Thread counts are the best available stand-in for "students live here". They feed the ranking.

<!-- VERBAL NUANCE: -->

### Sources tested and rejected

- apartments.com, apartmentfinder.com, forrent.com: Akamai "Access Denied" for scripts.
- zumper, rent.com, apartmentguide, uloop, collegerentals: listing aggregators. Not used for
  discovery, rent, amenities, photos or websites. A building with no site of its own is
  found through its local realtor (Source 3), not through an aggregator.
- homes.com / redfin neighborhood condo pages surface condo building names in web search
  results. A manual hint only. Nothing from them is stored.

<!-- VERBAL NUANCE: -->

## 3. Merge, dedupe and aliases (`merge_candidates.py`)

Dedupe is the core of the system. Buildings get renamed when they change owners, one Google
listing can stand for several buildings, and one building has many names.

Rules:

- Compare only candidates within 200 m of each other.
- Merge when: same Google place_id; or same street-number address; or within 60 m and name
  similarity ≥ 85; or within 200 m and similarity ≥ 92.
- Never merge on distance alone. 1883 at Cameron House and 1883 at Montgomery House are 30 m apart.
- Name similarity: strip filler words (apartments, condos, the, at, student, living, city
  name) but keep identity words (house, place, square). Compare with spaces removed too
  ("Windtree" = "Wind Tree", "Treehouse" = "Tree House"). **Do not trust token-subset
  matching for one-word names**: "Salado Place", "Casa De Salado" and "The Salado
  Apartments" are three buildings and a subset score rates them 100.
- Every surviving name becomes an alias. Keep every source for provenance.
- Canonical name preference: campus directory, then the Google listing with the most
  ratings, then realtor sites, Reddit, Overture.

Alias cases seen at UT that the rules must survive:

| Case | Example |
|---|---|
| Rebrand | Ion Austin = University House; Ballpark East = Collective on Riverside; Pointe on Rio = Tradition on Rio |
| Google uses a different name | Haus 535 is "Haus 5350"; The Marian Condominiums is "The Salado Apartments" |
| Same name, different building | Elan 24 (livingatelan.com) is not Elan East; Buena Vista near campus vs "Buena Vista at Riata" 15 km away |
| One listing, many buildings | "The Block" is one Google place for eight buildings; "Halstead Co-op & Nueces" |
| Name matches a street | "Hyde Park Court", "2400 Nueces", "Duval Villas" return a street or an empty shell unless queried with "Apartments" and the address |
| Two buildings, one pin | Texan & Vintage got the pin of Crest at Pearl |

Rebrands cannot be resolved by rules alone. When two names share an address or outline, the
merge handles it. When Google simply uses another name, a person or an LLM check of the
building's own page has to confirm it; record the result as an alias.

Rebrand signals that only show up once websites are fetched (Playbook 2 section 2c). Feed
them back into the merge:

- The old name's domain loads a page branded with the new name.
- Two roster entries resolve to the same website and are not sister properties.
- A listing site shows one address under a different name than the roster's.

In each case keep one building, under the name its own site uses today, and move the other
names to aliases. Do not carry the old entry forward as a second building.

Aliases come from sources of very different quality. A name taken from a directory row, a
realtor page or a listing site can belong to the building next door. Store each alias with
its source, and only publish aliases that share the building's address or appear on the
building's own site. A wrong alias is worse than a missing one: it routes another
building's students and reviews to this page, and some destinations cannot remove an alias
once it is imported.

<!-- VERBAL NUANCE: -->

## 4. Coordinates, size and ranking (`select_roster.py`)

Coordinates are covered in Playbook 2 section 1. In short: NAD address point, then the
building outline it falls in, store the outline's center, flag disagreements for a manual
right-click check.

Size: outline area × floors (height ÷ 3.2 m) ÷ 75 m² gives a rough unit count. Used to rank
and to decide how hard to look for amenities. A building under 220 m² known from one source
is almost certainly a house and is pushed down.

Student-relevance score (higher = more evidence students rent there):

| Signal | Points |
|---|---|
| In the campus directory | +3 |
| Reddit threads mentioning it | +1 each, max 3 |
| Each extra independent source family | +1 |
| Within 1.5 km of campus / within the core | +2 / +1 |
| 20+ Google ratings | +1 |
| 40+ estimated units | +1 |
| Student housing, co-op or dorm type | +1 |
| Has a website | +0.5 |
| Needs review / tiny single-source building | −2 / −3 |

Tier A is score ≥ 4, B is ≥ 2, C is the rest. Buildings outside every neighborhood are kept
only if the directory or Reddit names them.

UT check: the merged set held 905 buildings (816 ranked). The top 150 ranked buildings
contained 96 buildings from the old roster; the rest of the top 150 are real student
buildings the old roster never had (Taos Co-op, 21st St Co-op, The Hive Red River).

The score ranks candidates. It does not verify them. Verification is section 5a.

<!-- VERBAL NUANCE: -->

## 5. Completeness checks and the stop condition

### 5a. Verify before counting (clean first, then big)

A roster entry counts toward the 150 only when all of these hold. Check them before
enrichment spends time on the entry, and again after websites are fetched.

1. **It has a street address** confirmed by at least one source that is about this
   building (its own site, its operator's page for it, a local realtor's page for it, or a Google
   listing with the same name and address).
2. **It is housing.** Not an office or retail centre that shares the name, not an
   institution's dining or services building that a dorm cluster is named after.
3. **It is a building, not a business.** An apartment locator, a referral service, a
   property manager or an owners' association is not an entry, even when its name ends in
   "Apartments".
4. **It is one building, counted once.** Not the former name of another entry (section 3).
5. **It exists now.** A project that is announced or under construction is kept on `hold`
   and not shown until it leases.

Anything that fails 1 to 4 is dropped to a rejects file with the reason. A name with no
address, no site and no listing page after the full search ladder is dropped too. Do not
publish it as an empty page and do not keep it to reach the target. Playbook 2 section 6
defines the `publish_status` values.

Cheap tests that catch most of these early:

- Fetch the entry's website and read the title. A locator, an office centre and a lapsed
  domain are obvious in one line.
- Group entries by website. Shared sites are sister properties, duplicates or generic pages.
- Group entries by address and by outline.
- Flag entries whose only source is one realtor page or one listing row.

### 5a-2. Identity rules and the resolutions file (A&M review, 2026-11-17)

A person checked every A&M building that had no website and no listings. 27 of the 28
looked unresolvable to the pipeline. The review found real sites for 9 of them, 3
renames or aliases, and 11 rows that were never communities. Those findings are now
rules.

**Automatic rejection in `merge_candidates.py` (`entity_reject`).** Rejected rows are
written to `cand_rejected.json` with a positive reason. Nothing is dropped silently.

| Signal | Example | Decision |
|---|---|---|
| Facility word: community center, clubhouse, leasing office, student center, services, resources, department | Gardens Community Center, University Apartments Community Center - 3198, Disability Resources, Memorial Student Center | `support_facility`, rejected |
| Adjective, then only generic words, then a housing noun; or "subdivision"; or ends "in <city>" | "Top student apartment in college station", "Quiet setteled subdivision…" | `single_unit`, rejected. "Great Oak Apartments" survives because "Oak" is a name |
| Locator wording: apartment finders, locators, search | Aggieland Apartment Finders | `property_manager`, rejected |
| Legal suffix (Ltd, LP, LLC, Inc) **and** a suite address | Lexington Court Phase II Ltd, 4500 Carter Creek Pkwy Ste 101 | `owner_entity`, rejected. A suffix alone is not enough: "Stratford Arms LP" is a real complex |

**What the automatic pass cannot decide goes in `data/<campus>/resolutions.json`.**
`apply_resolutions.py` applies it after `select_roster.py`. Status codes:

- `KEEP`: a real community. Can set a canonical name, the website, a floor-plans URL, the
  manager, property and leasing-office addresses.
- `KEEP_UNIT_SOURCE`: a real community whose only source is one unit listing from a local
  broker or a manager portal.
- `ALIAS_TO`: the row is another roster building. Its names and URLs merge into that
  building.
- `REVIEW`: plausible but not verified. Never auto-merged. Not published until reviewed.
- `REJECT_PROPERTY_ROW`: not a rentable community. Needs a reason.

A `website_url` set here is **locked**. The crawler will not swap it for another URL that
"names the building", and will not fall back to discovery URLs.

**Search order when a building has no site** (each step found something on A&M):

1. **Exact address, not the name.** An address search exposes renames. Aspen Heights at
   3055 Holleman Dr S is now The Heights, confirmed by the operator's acquisition notice.
2. **Manager's property index.** A dead brand domain does not mean the building closed.
   31Thirty's own domain is dead; Original Management has a page for it.
3. **Property-specific leasing portals** (`<name>.managebuilding.com`, `<manager>.appfolio.com`
   listings). These count as first-party when the portal shows the building's name or
   address. Examples: AgTech Gardens on Buildium, Pearl on Original Management's AppFolio.
4. **Local brokers for condos.** Bell Properties, Longitude BCS, Boardwalk Homes. Keep the
   community and attach the unit listing to it. Never make a unit its own building.
5. **Directory ad headlines hide a parent complex.** The "Top student apartment" ad on
   aggiesearch says Woodlands in its text, so it becomes an alias of Woodlands.
6. **Office address and homes address differ.** Midtown's leasing office is 1612 Holleman
   #F and the townhomes are at 1600. Store both. The Penny's second row was its leasing
   office at 1025 University Dr #106.
7. **Government records** (housing vouchers, state housing agency, campus facilities
   directory) prove identity and type, not current leasing. Pearl/The Atrium are grouped
   in a voucher packet. That is not proof they are one building, so it stays `REVIEW`.

**Listing work feeds discovery back (2026-11-18).** Reading listing portals exposed more
identity facts. Record them in `resolutions.json` the same way:

- A "building" whose address is a suite and whose site is a portal listing many unrelated
  addresses is a property manager (361RENT, 979rent). Reject it.
- A roster address with `Ste` that matches the manager's office (Cedar Creek, 1000 University
  Dr E Ste 808) is not the building's address. Mark `REVIEW`.
- An Entrata portal page's title can carry the old name (The Doce's portal is still titled
  "The London"). That confirms a rename.
- Two buildings sharing one site (Sundance & Sausalito, Midtown & Fox Meadows) each have
  their own floor-plans page. Store each one's `floorplans_url`; never point both at one page.

**Never reject for a missing website.** Cayman Crossing, A&M Courtyard and Aggie Manor
exist and stay `KEEP` with no URL. A national listing site (Compass, apartments.com) is
a discovery clue, never the stored source.

**Wrong-site traps the crawler now handles** (`enrich_site.py`):

- **Redirect to a sister brand.** Redpoint's Google URL redirects to Retreat, whose pages
  link to redpoint-collegestation.com. The crawler now also follows links on the page's
  canonical and `og:url` hosts.
- **Plans on a leasing subdomain.** Eastmark's plans are on `entrata.<domain>`. Set
  `floorplans_url` in resolutions.
- **Global navigation.** Yugo's nav linked "Rooms" to the UAE pages. A path that says
  floor-plans/availability/rates now ranks above a loose text match, and the usual paths
  are probed directly.
- **Dead or parked seed.** Every other known URL is tried before marking `no_website`.

### 5b. Coverage checks

Run after the first merge:

1. **Per-source overlap.** If one source contributes many buildings no other source has,
   it is reaching a segment the others miss. Look for a second source of that kind.
2. **Miss diagnosis.** Every building known from any ground truth (old roster, a student's
   list, Reddit names) that the merge lacks gets a reason and a rule. UT's reasons:

| Miss | Reason | Rule added |
|---|---|---|
| Windtree, Treehouse | Spelling with/without space | Compare names with spaces removed |
| Dobie Twenty21 | Google type `shopping_mall` | Keep non-residential types that a student-housing text query returned |
| Delphi, Marian, Park Place | Condos named on realtor pages without an address | `resolve_addresses.py` |
| Uptown Realty's 32 condos | Realtor office not typed as agency in Places | Take realtor offices from Overture as well |
| Salado Place cluster | Over-merge on one-word subset | One-word names need a near-exact match |
| Palmetto Condominiums | No Google listing and no realtor page found | Still missed. Needs homes.com/redfin condo pages or county appraisal data |
| Gateway Apartments | University-owned family housing, 3 km out, not typed residential | Still missed. Add the university housing site as a source |
| 12 buildings 5–40 km out | Outside every named neighborhood | Out of scope by design; arrive only via Reddit or submissions |

3. **Stop** when a full extra pass (one more realtor site search, one more Reddit query
   set) adds fewer than 2% new in-scope buildings.
4. **150 floor.** If tiers A+B hold fewer than 150 verified buildings (section 5a), widen
   neighborhood radii by 25% and re-run Sources 1 and 3 before lowering the bar. A small
   campus that truly has fewer is acceptable only with the per-source counts as evidence.
   The floor is a reason to look harder. It is never a reason to keep an unverified name.

### 5c. Reference-list completeness (UT scrape misses, 2026-11-25)

A one-shot campus run is not done when the top 150 look full. It is done when every name on a reference list is either on the roster or written down with a cause. `aggregator/campus_completeness.py` compares the roster with that list and exits non-zero while names are missing. `aggregator/include_pinned.py` puts locked pins and `ADD` resolutions back into the enrich set after the rank cut.

Collect the reference list from all of these. None of them is optional:

1. Google Places grid (`discover_places.py`) and Overture footprints (`discover_overture.py`).
2. The university off-campus housing list (`discover_rcp.py`, or `discover_ocp.py` after a person saves the directory in their own browser). Names and addresses only. Never scrape rent from the directory.
3. Property-manager portfolios (`discover_pm_sites.py`), including a condo landlord's `/communities/` index. One row per community URL.
4. Aggregators (Apartments.com, Zillow, Rentable, RentCollegePads) as a lead list only. `common.is_ils` still blocks them as a rent source.
5. An existing catalog: last year's scrape, an RMR export, or `properties_config.json`. For UT that file is the synced pin list.

Causes below are the UT buildings Rebuild's top-150 roster did not already name, plus the extractor gaps that made a present building data-poor. The rule is what the next campus must do. `aggregator/miss_causes.py` assigns the cause from the backend and URL.

| Cause | What went missing | Rule |
|---|---|---|
| `condo_unit_landlord` | Uptown Realty condos (Escala, Treehouse, Pecan Square, Landmark Square, Greenwood, Wedgewood, Robbins Place, both Lantern Lane units, Littlefield, Galileo, San Pedro Flats, Tom Green, Park Place, Gables, Speedway, 3000 Guadalupe, Palmetto, Delphi, Windtree, Nueces Corner, and the ones matched by alias such as Vanderbilt, Waterford, Croix, Parapet) | Crawl the portfolio index. Lock each community URL. Do not require a Google place per condo. |
| `ranked_below_cut` | Sondery, Oak Grove, Marian, Troubadour, Presidium Tech Ridge, Promontory Point, Keystone, Preserve at Wells Branch, Oaks at Chisholm, Redpoint San Marcos, Estates and Village at East Riverside, Elan East, Haus 535, and similar low-review buildings | Top-N is not the roster. Pins and `ADD` are unioned in after the cut. |
| `entrata_bot_wall` | Quarters houses when the portal URL was stale, Point North, The Waller, Twenty Two15, Icon | Pin `/<city>/<slug>/student/` or `entrata.<site>`. Do not freeze `text_plan_list` when the status is `blocked_bot_wall`. Rescue with a price mode. |
| `rentcafe_bot_wall` | High Point, Hillside Creek, Duval Villas, Ballpark East | Pin `rentcafe_ysi` or `rentcafe_inline`. Saved `html_files` are banned on a production refresh. |
| `manager_portal_filter` | Avon, Penthouse, VEER, Leon Place, Preservation Square | Pin `address_match`, `listings_url`, and `fallback_range`. A geo guess does not replace that list. |
| `university_or_coop_table` | Dobie Twenty21, East Campus Graduate, Gateway, Laurel House | Route the university housing host to the table parser. Co-op rates are one shared URL plus `params.house`. |
| `layouts_only` | Town Lake (three FML names), Tower View, and any `no_public_pricing` pin | Keep the placeholder row and `params.reason`. Do not invent a rent. |
| `shared_feed_filter` | The Block 23, and any ACC sister the auto location filter drops | Pin every `location_filter`. Fetch the feed once per `source_id`. |
| `repli360_feed_shorter` | Marq on Burnet | Locked `repli360` stays on the DOM parser. The feed is the fallback when the DOM run is blocked, because the feed dedupes tabs and returns fewer rows. |
| `directory_lead_only` | West Campus Elloras | The directory name is a lead. Rent comes from the manager page, or an explicit unpriced pin. |
| `leaseleads_markup` | Villas on Guadalupe, 21 Pearl, Axis West Campus, Signature 1909 | Fingerprint `data-ll-floor-plan-lease-terms`. The synced `villas_wp` parser (FML_Data `a953774`) reads `[data-ll-floor-plan-card]` in the browser. Do not replace it with a partial HTTP read of the same JSON. |
| `per_room_type` | Yugo Rio, Corner, Nueces, Waterloo | Fingerprint `product-tile`. Pin `gtm_name`. Do not let `text_plan_list` win. |
| `query_string_matters` | Noble 2500 `?_lease_term=fall` | A locked URL keeps its query string. |
| `name_collision` | 1883 Cameron vs Montgomery, the four Quarters houses, the three Town Lake names | Do not alias distinct pins because they share a leasing office. |

`data/ut_austin/added_buildings.json` is the current UT set of reference names that `out/buildings.json` does not already contain. `listing_config.json` locks all 145 FML sources (`"locked": true`). Detection may add a building. It may not replace a locked backend, URL, or params.

A&M is the second reference and it is richer than a Places-only cut for concrete reasons: `campuses/texas_am.json` sets `neighbor_cities` (Bryan), a wider `pm_radius_m`, `ocp_base` (aggiesearch) and `extra_pm_sites`; `resolutions.json` locks websites and floor-plan URLs after a person checked buildings that had no site; bot-walled communities have hand-saved rescues under `data/texas_am/rescues/`; the frozen adapters include RentCafe, JSON-LD, and Gogetter, not only page text. Copy that shape for a new campus: directory plus PM portfolios plus locked URLs plus rescues, then the rank cut.

<!-- VERBAL NUANCE: -->

## 6. Run order

```
python3 discover_rcp.py <campus>          # lead list only (names/addresses/coords); or discover_ocp.py after the Chrome collection
python3 discover_places.py <campus>
python3 discover_overture.py <campus>
python3 discover_pm_sites.py <campus>
python3 resolve_addresses.py <campus>
node reddit_fetch.js <out> <subs> "<queries>" 120     # user logs in once
python3 discover_reddit.py <campus>
python3 merge_candidates.py <campus>
python3 select_roster.py <campus>         # -> roster_final.json / .csv
python3 apply_resolutions.py <campus> roster_final.json
python3 include_pinned.py <campus>        # ADD / locked pins survive the top-N cut
python3 campus_completeness.py <campus> --reference <reference.json>
```

Outputs per campus are in `data/<campus>/`. Every network response is cached, so re-runs
cost nothing.

<!-- VERBAL NUANCE: -->
