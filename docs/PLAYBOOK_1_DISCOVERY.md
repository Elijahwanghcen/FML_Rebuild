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
- CoStar sites (apartments.com, apartmentfinder, forrent, and CoStar-run campus directories such
  as aggiesearch.tamu.edu) block scripts. Campus directories on that platform must be read
  through the user's own Chrome.
- The student-relevance ranking is a heuristic tuned on one campus (UT). Treat the tier cut-offs
  as a starting point.
- Buildings far outside the named neighborhoods (UT had ~12 at 5–40 km, added by student rent
  submissions) are not discoverable by area search. They only arrive through Reddit mentions
  or later user submissions.

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
comparing names), `rcp_urls` / `ocp_base` (campus directory), `extra_pm_sites`.

How to choose neighborhoods:

1. Pull the campus off-campus directory first (Source 4) and bucket its listings on a 0.01°
   grid. The dense cells are the student neighborhoods. At A&M this showed Northgate,
   Holleman/Jones Butler, Wolf Pen Creek and the Barracks area in one pass.
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
| 4 | Campus off-campus directory | `discover_rcp.py`, `discover_ocp.py` | strong student signal | Names, addresses, floor plans, per-bed flag, features |
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

Then for each site: fetch the home page plus up to four links that look like portfolio pages
(communities, properties, listings, condos, availability). Hand each page's text to an LLM
and ask for `{name, address, type, url}` of multi-unit buildings in the city. Read liberally:
most of these sites have no feed.

Follow-ups that mattered:

- Many pages give a name with no address. `resolve_addresses.py` opens the building's own
  page on that site and takes the first street address that exists in the NAD index. An
  address that appears on more than three building pages of one site is the firm's office
  and is ignored. UT: 67 of 267 name-only candidates recovered.
- A listing titled "ADDRESS Unit 203" is a unit, not a building. Strip the unit and use the
  street address as the name. It will merge with the building later by address.

UT numbers: 243 sites picked, 116 returned buildings, 776 raw candidates.

<!-- VERBAL NUANCE: -->

### Source 4: Campus off-campus directory

Two platforms cover most universities:

- **Rent College Pads** (rentcollegepads.com/off-campus-housing/<school>/search and
  white-label sites like housing.offcampus.utexas.edu). The search page embeds every listing
  as `var listingData = JSON.parse(JSON.stringify({...}))`. One plain HTTP request returns
  name, address, lat/lng, category, landlord company, landlord website, floor plans with
  rents, `rent_style` (person or unit), feature lists and photos.
- **Off Campus Partners / CoStar** (e.g. aggiesearch.tamu.edu). Akamai blocks every scripted
  client including headless browsers. Read it in the user's own Chrome: each
  `/housing/page-N` response carries a `<script id="ocp-state">` whose search body is JSON
  escaped with `&q;` for quotes. `placards[]` hold name and `geography`. To get the data out
  of the tab without flooding the agent's context, put it in `window.name`, navigate the tab
  to a localhost receiver (`recv_local.py`) and send it in chunks.

Check both for every campus. A&M's Rent College Pads page has 8 listings; its CoStar
directory has 564.

Drop houses, duplexes, rooms, sublets, shared-space rows and rows titled with a bare street
address. Other campuses in the same university system appear in the same directory (A&M's
includes Fort Worth and Galveston), so cut by `max_radius_m`.

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
- zumper, rent.com, apartmentguide, uloop, collegerentals: reachable, thin or unit-level.
  Not needed once Sources 1–5 run.
- homes.com / redfin neighborhood condo pages surface condo building names in web search
  results. Useful as a manual cross-check for condos, not automated.

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

<!-- VERBAL NUANCE: -->

## 5. Completeness checks and the stop condition

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
4. **150 floor.** If tiers A+B hold fewer than 150, widen neighborhood radii by 25% and
   re-run Sources 1 and 3 before lowering the bar. A small campus that truly has fewer is
   acceptable only with the per-source counts as evidence.

<!-- VERBAL NUANCE: -->

## 6. Run order

```
python3 discover_rcp.py <campus>          # or discover_ocp.py after the Chrome collection
python3 discover_places.py <campus>
python3 discover_overture.py <campus>
python3 discover_pm_sites.py <campus>
python3 resolve_addresses.py <campus>
node reddit_fetch.js <out> <subs> "<queries>" 120     # user logs in once
python3 discover_reddit.py <campus>
python3 merge_candidates.py <campus>
python3 select_roster.py <campus>         # -> roster_final.json / .csv
```

Outputs per campus are in `data/<campus>/`. Every network response is cached, so re-runs
cost nothing.

<!-- VERBAL NUANCE: -->
