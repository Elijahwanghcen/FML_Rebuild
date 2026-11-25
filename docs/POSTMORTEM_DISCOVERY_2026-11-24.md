# Review of `college_station_apartments.md` + post-mortem: what the A&M rebuild missed (2026-11-24)

The report covers the 51 Texas A&M site buildings that have no floor plans. To check it, I fetched its 28
first-party links over plain HTTP (no browser, no LLM) and compared every row with the rebuild's record
(`roster_*.json`, `out/buildings.json`, `raw/<slug>/listings.json`). Listing-site links (Zillow, Apartments.com, HAR,
homes.com, AggieSearch, veryapt, collegestation.guide, apartmentbuildings.com) were not fetched. Under the no-ILS rule
they are leads only, never sources.

## 1. How good is the report?

**Overall: a good lead list, not a source of record.** Where it could be checked, its claims about identity, status
and duplicates were correct. It found real first-party sites that the rebuild missed. Its main weaknesses are
unverified links (it says so itself), heavy use of listing sites for condo rows, and calling floor plans "unverified"
on sites that do publish them.

### Claims confirmed by fetching the page

| Row | Report says | Page shows | Rebuild had |
|---|---|---|---|
| Sterling College Station | 2818 + Parkway Place consolidated, 1/2/4 BR | `/floorplans/`: 33 plan lines, 22 JSON-LD FloorPlans | same consolidation (resolutions.json); RMR still has the two duplicate profiles |
| The Penny | future, opens Aug 2027, Studio–5 BR | "hard hat tour", "first 10 leases for Fall 2027" | `planned` ✓ (6 plans from the LLM read, not pushed) |
| **The Reserve at College Station** | Entrata student portal, 4 BR houses | portal live: 4 bd / 4.5 ba, leases for 2026-27 and 2027-28 | **never discovered** |
| **University Heights** | official universityheightscs.com | plans 3×3 Townhome, 4×3 House, 4×4 House, 4×4 Townhome, 4×4.5 Luxury | **brickandparcel.com** (manager homepage) |
| VERVE | future, 1,193 beds | Subtext page: 21-storey, 1,193 beds, 311 Stasney St | **never discovered** |
| **Country Place** | originalmanagement.net/country-place | Studio–2 BR, 468–810 sq ft, $589–1,699, plan images | **countryplaceapts.net now redirects to a gambling spam site** |
| **Huntington** | liveathuntingtoncollegestation.com | 1, 2 and 3 BR floor plans (interactive model) | **dtiproperties.com** (manager homepage) |
| **A&M Courtyard** | bcsonlinerealestate.com/allone.php | manager listing: A&M Courtyard 1 bd / 1 ba, 550 sq ft, $775 | no website |
| **North Ramparts** | bcsonlinerealestate.com/alltwo.php | 2 bd units: 865–1,167 sq ft, $950–1,295 | manager homepage → 1 junk row ("3500 Sq Ft") |
| Madison Pointe, Cedar Creek, Eastmark, The Vintage, The Heights | plans exist | floor-plan pages live (The Vintage: plan images) | 0 rows (Madison Pointe) or LLM read only (the rest, so not pushed) |
| **Galleria Village** | commercial office/retail | title "Office and Retail Space" | listed as an `open` apartment building |
| **Treehouse** | reported closed | "permanently closed" on its own site | `open` |
| Howdy Apartments | locating service | "Texas Apartment Locating for Aggies" | rejected ✓ |
| Southern Pointe Woodbird | development, unresolved | community / subdivision site | rejected ✓ |
| The Commons | on-campus halls, exclude | RMR points to reslife Mosher Hall | `open`, reslife commons-hall |
| Forest Pines | official site | site live | found by discovery, dropped before ranking |

### Claims I could not verify

- The Halston and 21 Gramercy: both sites return a 403 bot wall to plain HTTP.
- Landmark on Longmire: sits behind a waiting-room queue.
- Aggie Villas: did not answer.
- Unit and bed counts (Azura "50 homes / 300 beds", Reserve "~119 homes"): no first-party source given.
- University Place "includes 517 Southwest Parkway": plausible, since the rebuild has University Place at 521
  Southwest Pkwy, next door. Needs a first-party check.
- Waterwood "3–4 BR": the HOA page shows no configurations.

### Weaknesses

- Its own note says links were not rechecked. 4 of 28 first-party links didn't load for a script; the condo rows
  mostly point to listing sites.
- It under-claims: University Heights, Huntington and Country Place are "diagrams unverified" or "not fully
  verified", but all three publish floor plans.
- Rows carry no address or checked-on date, so each one has to be re-identified before use.
- "Configurations" and "floor plans" are mixed: individual condo units are not floor plans, as the report itself notes.

## 2. Post-mortem: what the rebuild missed

| # | Miss | Buildings | Root cause in the pipeline |
|---|---|---|---|
| M1 | **Never discovered** | The Reserve (leasing now), VERVE (future, 1,193 beds) | No source family returned them. Places grid, Overture, the PM-site crawl, Reddit and the off-campus directory all missed them. There is no sweep of management-company or developer portfolios, and no sweep of new developments. |
| M2 | **Discovered, then dropped** | The Halston (rank 247, student score −0.5, tier C), Forest Pines (merged, never ranked), 21 Gramercy (only in the off-campus directory) | Selection cuts on student score. Nothing reconciles the final roster against what is already on the site or in the campus directory, so dropped buildings vanish without a reason. |
| M3 | **Wrong website chosen** | Huntington and University Heights (manager homepage instead of the property site); A&M Courtyard and North Ramparts (homepage instead of the manager's listing page) | The website ladder accepts a management company's homepage. No domain probe for `liveat<name><city>.com` or `<name>cs.com` patterns. No search of the manager's own site for the property's page. |
| M4 | **Hijacked domain kept** | Country Place (countryplaceapts.net → gambling spam) | The parked-domain check looks only for "for sale"/parking wording. It doesn't catch a redirect to an unrelated domain, a foreign-language page, or gambling keywords. |
| M5 | **Wrong status or entity** | Treehouse (permanently closed), Galleria Village (office/retail), The Commons (on-campus residence hall) | No check of the site's own text for "permanently closed", "office/retail space" or a university housing domain before publishing. |
| M6 | **Plans on the page, none extracted** | Madison Pointe (0 rows), A&M Courtyard and North Ramparts (manager listing pages), and LLM-only rows (Cedar Creek, Eastmark, The Vintage, The Heights, The Penny, Lakeridge, River Oaks, Waterwood) | Floor-plan page not saved or not parsed (see the plan-image post-mortem). No adapter for the bcsonlinerealestate listing pages. LLM rows are rightly held back, so these show as empty. |
| M7 | **Probable duplicate** | 517 Southwest Parkway vs University Place (521 Southwest Pkwy) | Duplicate check matches names and exact addresses, not neighbouring house numbers on the same street. |
| M8 | **Expected-empty treated like a miss** | 16 condo/HOA communities (Fox Run, Woodstock, Hidden Bridge…) | No "no central floor plans expected" class, so condos sit in the same "no plans" bucket as apartments that need fixing. |

**What the rebuild got right that the report confirms:** the Sterling consolidation, the Howdy and Southern Pointe
rejections, The Penny as planned, Azura's Boardwalk portal, and no catalog for the condo communities.

## 3. Checks to add so other campuses don't repeat this

None of these use an LLM or a browser. Proposed only; not implemented.

1. **Roster reconciliation (catches M2).** Every name from the existing site profiles, the campus directory lead list
   (AggieSearch/OCP), Reddit and places discovery must end up in `roster_final` or in `rejected_rows.json` with a
   reason. Unaccounted names go to the QC report. Buildings cut only by student score are listed separately
   ("cut by score: N"), so cutting a real apartment is a decision, not an accident.
2. **Portfolio and pipeline sweep (catches M1).** For each management company or developer seen in the roster
   (`manager`, site footers, PM-site crawl), plus a fixed list of student developers and managers (Subtext, ACC, Asset
   Living, Landmark, Yugo, Cardinal, Peak, CA Ventures…), fetch their properties or portfolio page and keep entries
   in the campus city. New ones become candidates. Also read city and university new-development pages for
   "planned/under construction" entries.
3. **Website ladder hardening (catches M3, M4).**
   - Reject a website whose final URL is on another registrable domain.
   - Reject a page whose title or language has nothing to do with housing or the building name (gambling words,
     non-English).
   - When the website is a manager's homepage listing several properties, find the property's own page on that site
     (sitemap or link whose text or path contains the name) and prefer it.
   - Extend `resolve_website.py` probes with `liveat<name><city>.com`, `<name><city>.com`, `<name>cs.com` and
     `<name>apts.com`.
4. **Status and entity gate before publish (catches M5).**
   - "permanently closed" on the site → `closed`.
   - "office", "retail", "commercial space" in title/H1 → not residential.
   - `reslife.`, `housing.` or `.edu` website → `residence_hall` (separate on-campus list).
   - "locating"/"locator" → service, not a building.
   - "hard hat tour", "opening fall 20xx", "now pre-leasing" with no units yet → `planned`.
5. **Adapters for the misses (catches M6).** A host adapter for `bcsonlinerealestate.com` listing pages, filtered by
   property name; it is deterministic, since rows carry beds, baths, sqft and price. Save floor-plan subpages per §4x
   A1–A2.
6. **Neighbour-address duplicate check (catches M7).** Same street and house numbers within ±10 → candidate
   duplicate for review.
7. **Floor-plan expectation class (catches M8).** Mark condo/HOA/individual-landlord communities as
   `individual_units`, so QC reports them separately from apartments with zero plans.

## 4. What to do with this report now (A&M)

- Add The Reserve, with its first-party Entrata portal. Add VERVE as planned.
- Fix the websites:
  - Huntington → liveathuntingtoncollegestation.com
  - University Heights → universityheightscs.com
  - Country Place → originalmanagement.net/country-place (drop the hijacked domain)
  - A&M Courtyard and North Ramparts → the manager's listing pages
- Hide Galleria Village (commercial) and Treehouse (closed). Decide whether The Commons belongs on an
  off-campus site.
- Merge Parkway Place and 2818 Apartments into Sterling. Check 517 Southwest Parkway against University Place, then
  merge if they are the same.
- Rebuild the plans for University Heights, Huntington, Country Place, Madison Pointe, A&M Courtyard and North
  Ramparts from their first-party pages.
- Not usable as sources: the report's Zillow, Apartments.com, HAR, homes.com and AggieSearch links. Use them to find
  first-party pages only.
