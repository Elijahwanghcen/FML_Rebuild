# Audit of the campus listing aggregator

Audited 2026-11-15/16 against commit `7ae111d` (branch `main`) and the data in `data/`.
Nothing in `aggregator/`, `campuses/`, `data/` or `~/FML_scraper` was changed. No new Google
Places calls were made and no LLM step was re-run (one 20-token `claude -p` call was made to
measure per-call overhead). Throwaway scripts are in
`/private/tmp/claude-501/-Users-elijahwangchen/affefc6b-6870-493c-aa68-afbd01bfd2d3/scratchpad/audit/`.

Every estimate below states its sample size. "Inferred" marks a conclusion I did not check directly.

## 1. Verdict

The discovery half works: on the script's own rule it finds 128 of the 143 old UT buildings, and
at A&M it finds 52 of the 62 buildings students name most on Reddit. The headline numbers in
`RESULTS.md` mostly reproduce. What does not hold up is the step from "candidates found" to
"finished roster and data". The ranking formula leaves 33 old-roster UT buildings out of the
top 150 and puts six A&M complexes with 299 to 575 Google ratings in the discard tier, while
the A&M 173 includes a student union, two campus offices, three leasing companies and eight
duplicate entries. I would stand behind about 152 of the 173. Coordinates are no more accurate
than the raw Google pin at UT, and at A&M an address-matching bug puts one top-5 building 477 m
away. Amenity extraction is accurate where it ran (about 95% of sampled rows correct) but a
status bug skipped it for buildings whose pages were saved, and 56 of 173 A&M buildings have
none. Prices are never invented, but per-bed rent is labeled per-unit on at least 20 buildings
and at least 45 of the 104 "not publicly listed" A&M buildings are scraper misses. The repo is
not ready for a third campus without the fixes in section 5, and one item needs action today:
**the force-pushed commit with raw Google Places data is still publicly downloadable from
GitHub.**

### Scorecard

| Area | Grade | Measured number | Confidence |
|---|---|---|---|
| Discovery recall | B | UT 128/143 (90%) by the script's rule, 120 distinct entries; only 95 to 98 of the 143 are in the shipped top 150. A&M 52/62 Reddit-named buildings (84%) | High for UT, medium for A&M |
| Discovery precision | B− | UT: 19 of 25 sampled extras are real student buildings (76%). A&M: 28 of 30 sampled are real and distinct (93%); full pass finds 19 of 173 that must go | Medium |
| Coordinates | C+ | UT median 22 m from hand pins (n=92), same as the Google pin. A&M: 15 of 18 viewed are on the property, worst 477 m; 50 flagged and never reviewed | Medium |
| Amenities | B (UT), C (A&M) | Recall 77% of old terms (91 buildings). Precision about 95% (433 rows, 20 buildings). No data for 9/150 UT and 56/173 A&M | High for recall, medium for precision |
| Rents | C | 436 of 436 sampled price values are on the saved page. Priced: 109/150 UT, 69/173 A&M. `rent_basis` contradicted by the price ladder on 9 UT and 11 A&M buildings | High |
| Aliases | C | 5 of 6 claimed former names correct. Two of the three most-named A&M buildings on Reddit lost their student name. About 9 of 33 A&M alias sets contain another building's name | Medium |
| Cost efficiency | C | Places $32.21 total, 56 to 67% of calls returned nothing new. LLM: 1,868 calls, about 88% of input tokens are fixed CLI overhead (inferred from one measured call) | Medium |
| Reusability | C | Second campus ran, with 5 human steps, no README or requirements file, and UT-specific strings in code and assets | High |
| Organization | C− | Small readable scripts and good caching; no tests, object IDs collide, failures hidden, public history still serves removed data | High |

## 2. Findings, ranked by impact

### F1. The removed Google data is still public (repo hygiene, step 22)

- **Checked:** every object in the local git database (89 blobs, reachable and unreachable) for
  the `.env` key and any `AIza…` string; `.gitignore`; the GitHub API and raw file host for the
  pre-amend commit.
- **Found:** the API key is not in any git object, tracked file, log or cache file (8,683 files
  under `data/` and `aggregator/` scanned). `.env` was never committed. No emails, phone
  numbers or local paths in tracked files. But commit `7c030ec` (the one amended to `7ae111d`
  and force-pushed) is still served by GitHub:
  `gh api repos/Elijahwanghcen/RateMyRent_NewCampus/commits/7c030ec9…` returns it, and
  `raw.githubusercontent.com/…/7c030ec9…/data/ut_austin/cand_places.json` returns HTTP 200,
  607,511 bytes. That commit holds 28 data files the current one does not (15 UT, 13 A&M): raw
  Places results for both campuses, the full UT campus-directory scrape (`cand_rcp.json`), the
  A&M directory rows, realtor-site extractions, every roster stage and Reddit mention notes.
- **Also:** the current tracked files still carry Google content that Playbook 1 says must not
  be stored. `out/buildings.json` has Google-formatted addresses on 62 of 150 UT and 108 of 173
  A&M buildings, Google website links with `gmb`/`gbp` tracking on 46 and 31, and two raw Google
  pins (Asher College Station, Charleston Mills Townhomes). `data/ut_austin/roster_final.csv`
  has 509 rows, 455 with a place ID and 365 with a Google address.
- **Fix:** ask GitHub Support to purge the dangling commit, or delete and recreate the repo
  (the only branch is `main`, 0 forks). Then decide whether the tracked outputs may keep Google
  addresses and websites; if not, replace addresses with the address-index form and strip the
  website field to the registered domain before the next push.

### F2. The ranking decides the roster and it is wrong in both directions (steps 3, 6, 8)

- **Checked:** `select_roster.py` against the UT ground truth and the full A&M ranked list.
- **Found, UT:** the top 150 hold 95 old-roster names, which collapse onto 87 entries, so 63
  entries (not 53) are outside the old roster. 33 old-roster buildings rank below 150. Large
  purpose-built student buildings are among them: Dobie Twenty21 (rank 169), Twenty Two 15
  (180), Troubadour (196), The Waller (200), Icon at Austin (357). Three Riverside complexes
  with 183 to 527 ratings are in tier C.
- **Found, A&M:** tier C (discarded) holds The Heights at College Station (575 ratings), City
  Heights (411), Flats on 12 (333), The Halston (319), The Dominik (299) and Vibe on Harvey (52).
  Tier A/B (kept) holds Memorial Student Center, Disability Resources, Texas A&M Transportation
  Services, Aggieland Apartment Finders, University Rents and 361RENT.
- **Causes, with lines:**
  1. `select_roster.py:65` gives +3 for being in the campus directory and `:67` gives +1 per
     extra source family. These measure how many of the pipeline's own sources list a building,
     not whether students live there. Purpose-built student housing gets +1 (`:71`), and only
     when the word "student" is in the name or type.
  2. `select_roster.py:54` estimates units from one building outline. For garden-style
     complexes that is the clubhouse or one block: 42 of the 173 A&M buildings with 100+ ratings
     have an estimate under 30 units (Reveille Ranch 5, University Trails 2).
  3. `select_roster.py:74-75` subtracts 3 when that one outline is under 220 m². This is what
     sinks The Halston, Flats on 12 and Hillside Creek. It hit 10 A&M and 13 UT buildings that
     have 20+ ratings.
  4. `select_roster.py:58-60` counts a Reddit name as a match when its words are a subset of the
     building's words, after `common.py:42-45` has stripped "campus", "student", "community",
     "lofts", "flats" and the city words. "Campus Village" becomes "village" and credits 12
     threads to Galleria Village, Academic Village and Canyon Village. "Aggie Station" becomes
     "aggie" (the city word "station" is stripped) and credits 13 threads to Aggie Villas and
     Aggie Manor. Reddit counts are inflated this way for 49 of the UT top 150 and 36 of the
     A&M 173.
  5. Tier cut-offs (`:81`) are not calibrated. Score ≥ 2 keeps 509 buildings at UT and 173 at
     A&M. The UT set is "top 150" and the A&M set is "everything in A or B", so the two campuses
     were selected by different rules.
- **Was it tuned to UT?** The weights are generic, but nothing shows they work anywhere. They
  fail on UT's own ground truth (33 of 128 found buildings cut).
- **Fix:** score on evidence of student tenancy that does not depend on source count: Google
  rating count, exact-name Reddit threads, a per-bed price or individual-lease signal from the
  site, operator known for student housing, distance. Drop the footprint penalty and the unit
  estimate until they use every outline on the parcel. Match Reddit names exactly or by an
  explicit nickname rule. Add hard excludes before scoring (see F3).

### F3. The A&M 173 is padded; about 152 are defensible (steps 6, 8)

- **Checked:** all 173 rows by hand, plus a seeded random sample of 30.
- **Sample of 30:** 28 real distinct buildings, 1 duplicate (Domain Northgate, rank 81), 1 junk
  (Disability Resources). Precision 93% (rough 95% interval 78 to 99%). Student relevance is
  uncertain for 4 of the 28 (Brazos Oaks, Asher, Brazos Point, Academic Village).
- **Full pass, 19 entries to remove:**
  - Not housing, 6: Memorial Student Center (123), Disability Resources (147), Texas A&M
    Transportation Services (148), Aggieland Apartment Finders (125), University Rents (75),
    361RENT (152).
  - Duplicates, 8: Domain Northgate (81), The Ridge (136), Gardens Community Center (71),
    University Apartments Community Center (121), one of the two Charleston Mills (139/167),
    one of the two The Penny (56/149), one of the two EVER (41/72), "Top student apartment in
    college station" (120, a listing at the Woodlands' address).
  - A listing title for a townhome in a subdivision, 1: "Quiet setteled subdivision in Sumitt
    Crossing" (69).
  - University-owned on-campus housing, 3: The Gardens Apartments (46), White Creek (78), The
    Commons residence hall (103).
  - Not open, 1: EVER College Station is under construction at 401 Stasney St, completion
    July 2027 per the state licensing record.
- Two more are probably single units (Southern Pointe Woodbird, Azura Student Living) and about
  10 are small complexes with no website and under 5 ratings that I could not confirm.
- **Count I would stand behind:** 152 real, distinct, off-campus properties; about 140 with
  solid evidence. The 150 floor is met by two buildings, and only because six stronger
  complexes sit wrongly in tier C. With F2 fixed the floor is met comfortably.
- **Independent recall check (step 5), 80 names:** 62 from Reddit (3+ threads) and 18 from
  American Campus's College Station page (all 5 present), an Asset Living search and my own
  knowledge. In the 173 by name: 64. Present
  under a new name with the student name lost: 2 (The London, 2818 Place). In tier C: 6. Found
  but outside the named areas and dropped: 1 (The Bend at Crescent Pointe). In a source but
  filtered: 1 (21 Gramercy Park). Absent: 6. Some of my own names were chosen after
  seeing tier C, so the fair figure is the Reddit list: **52 of 62 (84%), 54 of 62 (87%)
  counting the two rebrands.** The Reddit list is not fully independent because thread counts
  feed the ranking.
- **The seven names in the brief:** The London: not in the roster by name; it is The Doce
  Student Living at 601 Luther St W (same address, and OpenStreetMap still labels the complex
  "The London"). Z Islander: yes, rank 84. The Lofts at Wolf Pen Creek: yes, rank 65. The
  Stack: yes, rank 40. Campus Village: yes, rank 95. Callaway Villas: yes, rank 58. U Centre:
  yes, rank 45.
- **Fix:** exclude `.edu` websites and names matching office/center/services/finders/rents;
  reject directory rows whose name is a sentence; dedupe on address after normalizing; treat
  the university's own housing as a separate class.

### F4. Merge and alias rules attach names to the wrong building (steps 1, 4, 12)

- **Checked:** every UT match with name similarity under 100 or distance over 60 m (45 rows),
  a seeded look at the rest, all pairs within 60 m in both final sets, and the claimed A&M
  former names against the web.
- **The eval rule is loose.** `eval_coverage.py:27` accepts 150 m with 60% name similarity.
  Two "found" UT buildings are false: Laurel House Co-op matched Helios Co-op (different
  organization, 80 m away), and 3000 Guadalupe St matched Guadalupe 31 (a different address).
  A match on an alias also counts when the alias was merged in by mistake: Texan & Vintage is
  "found" as an alias of Crest at Pearl, 350 m away.
- **Two "misses" are ground-truth errors.** Duval Villas' hand pin is 3.7 km from 4305 Duval St;
  the system has the building (rank 211). Park Place Condominiums has two different pins in
  `~/FML_scraper` (3.6 km apart); the system attached the name to a neighbor of the catalog
  address. Net effect: 128 stays about right by name, but only **120 distinct entries** carry
  the 128 names, because 8 roster buildings share an entry with another roster building
  (Croix + Delphi, The Block on 25th East + West, The Block on Pearl North + South, 1883
  Cameron + Montgomery, Halstead + Nueces, Town Lake ×3). The module docstring of
  `merge_candidates.py` says Cameron and Montgomery must never merge; the output has one entry
  named "1883 Cameron & Montgomery House".
- **Cause of the bad merges:** `common.py:42-45` strips "flats", "lofts", "homes", "campus" and
  `common.py:157-158` scores a token subset as 100, so "San Pedro Flats" equals "San Pedro Oaks"
  and `merge_candidates.py:161` merges on name alone at up to 200 m.
- **Within 60 m:** UT 42 pairs, 2 with identical stored coordinates (Buena Vista Condo and
  Buena Vista Condominium are one building split in two; House of Commons and Littlefield House
  are two buildings given one point). A&M 8 pairs, 6 identical (the duplicates in F3, plus
  Honcho and The Jay, which I did not resolve).
- **Split buildings:** UT 3 (Buena Vista; "Nueces" rank 6 and The Quarters Nueces House;
  "Grayson" and The Quarters Grayson House). A&M 8 extra entries (F3).
- **Names that are not building names:** UT "Shane Michael Brooks" (a person; the building is
  Rio Heights), "EASTGATE CONDO, perfect for House Staff at Dell/St. David's…", "College Houses
  Cooperatives" (an office; alias Opsis Co-op), "Nueces", "Metropolis" for 415 Colorado. A&M:
  the two listing titles, "Pearl Apartments Buildings A-P", "517 Southwest Parkway",
  "Lexington Court Phase II Ltd". The canonical name comes from the directory first
  (`merge_candidates.py:171-183`), so directory listing titles win.
- **Claimed A&M former names:**

  | Claim | Result | Evidence |
  |---|---|---|
  | Ion = Aspire College Station | Correct | Same address 711 University Dr; local blog and forum posts date the rename to 2024-25 |
  | The Aria = Gateway at College Station | Correct | Same address; review site says "The Aria (old Gateway Apartments)" |
  | The Doce = The District on Luther | Correct but incomplete | 2010 press release puts The District at 601 Luther St W. The name in between, The London, is missing |
  | EVER = Casa Del Sol | Wrong | EVER is a new building under construction on the Casa Del Sol site, not a rename |
  | Fifteen12 = College Edge | Correct | Same address 1512 Hollowhill Dr; earlier name Autumn Woods is missing |
  | The Grand 1501 = Plantation Oaks | Correct | Property record at 1501 Harvey Rd |

- **Other wrong aliases at A&M:** The Grand 1501 ← "The Ivy" (a separate complex, rank 11);
  Arbors at Wolf Pen Creek ← "Kiest Hall - Dorm 2" and "Wolf Creek Condos"; The Atrium ←
  Campus View, Pearl Apartments, The Marc; Hidden Bridge ← River Oaks Townhomes (also its own
  entry); Richmond Ridge ← Holleman by the Park (also its own entry); Yugo Apex ← "A&M
  Apartment"; The Tradition is listed under its pre-2016 name with the current name, 12 North,
  as the alias. By my count 9 of the 33 A&M alias sets contain another building's name.
- **Missed rebrands that cost the most:** The London (17 threads, third most-named) and 2818
  Place / 2818 Apartments (11 threads) were merged with Parkway Place into Sterling College
  Station. `discover_reddit.py:73` asked Google for both, got the right building back, and
  discarded it because the name similarity was under 60. Of 21 rejected A&M lookups, 17 were
  short names of buildings already in the roster and 3 were rebrands.
- **Fix:** keep a returned place whose name differs as a "possible former name" and confirm it
  with one check of the address; never merge on name alone beyond 60 m; do not strip words that
  distinguish buildings; require an address or outline match before adding an alias; split a
  merged entry when its records carry two different street numbers.

### F5. Coordinates: not better than the Google pin, and one real bug (step 9)

- **UT, numbers:** 122 roster buildings matched with name similarity ≥ 88. Stored point vs hand
  pin: median 24 m, 69 within 25 m, 11 over 100 m. Google pin vs hand pin: median 22 m, 68
  within 25 m, 10 over 100 m. Stored is closer in 43 pairs, Google in 43, tie in 33. On the 32
  hand pins with five or more decimals the Google pin is closer (median 20 m vs 32 m). Top-150
  subset (n=92): median 22 m, 55 within 25 m, 7 over 100 m, which matches `RESULTS.md`.
- **The hand pins are not a clean standard.** I viewed the six largest disagreements on
  satellite and street maps. In four the system is right and the hand pin is wrong (Marq Uptown
  588 m, East Campus Graduate Apartments 284 m, Tom Green Condominiums 147 m, Aura Thirty2
  99 m). Ballpark North's hand pin is on the leasing office. One is a system error: The Block on
  Pearl North is stored at Pearl South's address, 399 m off, because the two were merged.
- **A&M, 18 buildings viewed** (all 10 `pin_unverified`, 5 more that are flagged, 3 unflagged): 15 are on the
  property's residential buildings, 2 are 80 to 120 m off at an entrance or pond (Charleston
  Mills Luxury Townhomes, Asher), 1 is 477 m off (Ion College Station). Median error to the
  nearest residential building is about 0 m; worst is 477 m. The 10 unverified pins are
  directory or Google points, none grossly wrong.
- **The bug:** `common.py:72-74` cuts an address after the last street-type word, which drops a
  trailing direction. "711 University Dr" and "711 University Dr E" become the same key, and
  `geo.py:38-44` returns the mean of every point with that key. Ion is stored in Century Square,
  2 km from Northgate. The same collision affects "601 Luther St" vs "St W" and "1800 Holleman
  Dr" vs "Dr W/E". There is also no city or ZIP filter.
- **A&M's address layer is per unit.** 100 of 173 addresses match more than one point (up to
  628 points per address, spread up to 750 m within one complex). The stored point is the
  outline nearest the mean of those points. That is a fair complex-level point, and in the three
  garden complexes where both marks were in view (The Doce, Callaway Villas, U Centre) it sat
  among the residential buildings while the Google pin sat on the leasing office. But it is not
  "the building", and 43 of 173 stored points sit on an outline under 400 m².
- **Review flags:** 50 A&M buildings are flagged and none were reviewed. Of the 11 UT
  disagreements over 100 m, 5 were not flagged.
- **Is "address point + outline center" better than the Google pin?** For accuracy, no (n=119
  pairs at UT). Its advantage is that the result can be stored and published. For multi-building
  complexes it gives a better complex centroid than the leasing-office pin.
- **Fix:** keep trailing directions in the address key; filter by ZIP; when one address has many
  points, store the centroid of the points and say so (`coord_method = unit_points_centroid`)
  instead of snapping to one small outline; flag when two buildings get the same point.

### F6. Amenities: accurate when extracted, with gaps caused by bugs (step 10)

- **Recall, UT:** 91 comparable buildings in the top 150. Old terms recovered: 76.9% overall,
  86.7% median per building (claim: 74% and 83% on 93). Most missed: microwave, dishwasher,
  ceiling fans, disposal. The repo has no script that produces the full-run number;
  `eval_amenities.py` only reads the 22-building `roster_test.json`.
- **Precision, 10 buildings per campus, 433 rows read against quotes and URLs:** UT 15 wrong of
  220 (93%), A&M about 6 wrong of 213 (97%). Types of error:
  - Nearby business recorded as an amenity, 3 rows, all on Monticello Studios: BBQ/Grill from
    "Hyde Park Bar & Grill", Fitness Center from "Hyde Park Gym", Yoga Studio from "Core Power
    Yoga". These come from `aggregator/assets/alias_map.json`, which maps those exact strings.
    The file was copied from the UT build and applies with no context check.
  - Another building's page, at least 5 buildings: Melroy and Monticello cite Envoy's page;
    Signature 1909 cites The Block's directory listing; Regents West at 24th cites the 26th
    listing; Hyde Park Apartments cites Hyde Park Court's. Cause: the directory row is matched
    on name similarity ≥ 90 with the subset rule (`enrich_amenities.py:132`). 155 UT rows on 23
    buildings and 81 A&M rows on 9 buildings share an exact source URL with another building;
    some of that is legitimate (one site for several houses).
  - Term stretched beyond the quote, the rest: "Covered Parking" → Parking Garage (12 of 58 UT
    and 9 of 28 A&M garage rows), "On-site Maintenance" → 24/7 Maintenance (17 of 65 and 18 of
    49), "Cable ready" → Internet Included, "Sun Deck" → Rooftop Sun Deck.
- **Three states:** no row is ever recorded as absent. Statuses are present, select, optional;
  everything else is omitted and the building gets `amenity_data: unknown` when it has none.
  So unknown is never stored as absent. Equally, absent is never stored at all; the yes/no
  checklist path in Playbook 2 does not exist in code.
- **Evidence:** all 4,913 rows have a quote and a source URL. Implied text: 211 UT, 214 A&M.
  Photo captions: 87 and 84.
- **Buildings with zero amenities:** UT 9, A&M 56. A&M breakdown: 12 have no URL at all; 18
  have a URL that failed to fetch but are labeled `no_website` (9 of them were given the
  blocked campus-directory link as their website); 23 were crawled but the "website" is a
  realtor home or search page or a campus office; 3 are labeled `blocked_or_empty` although
  their pages were saved.
- **Bug:** `enrich_site.py:138-139` sets status to `blocked_or_empty` when a secondary page
  fails, overwriting `ok`. `enrich_amenities.py:133` then skips the building. Aggie Station
  (13 Reddit threads), Yugo Austin Nueces (324 KB amenities page saved), University Quarters,
  Midtown Townhomes and Fox Meadows lost their amenities this way.
- **Bug:** `enrich_site.py:57` defaults status to `no_website` and never changes it when the
  fetch fails, so "30 no website" in `RESULTS.md` is really 12.
- **Fix:** the two status bugs; match directory rows on address, not name; delete business and
  neighborhood strings from the alias map and re-vet the stretched ones; add an eval script for
  the full run.

### F7. Rents: faithful extraction, wrong basis, low coverage (step 11)

- **Fidelity, 10 first-party buildings per campus:** every one of 436 price values is on the
  saved floor-plan page. Four live checks on 2026-11-15 (Lark Northgate, Saddlewood Club, The
  Stack, Pease Parkside) match the stored plans, beds, baths, sqft and prices exactly. A fifth
  (Villas on 26th) returned HTTP 403.
- **`rent_basis`:** `enrich_listings.py:27` falls back to building type when the page does not
  say. Building type is wrong for much student housing (F8), so per-bed prices are labeled
  per-unit. A price ladder that falls as bedrooms rise is the per-bed signature; it contradicts
  the label on 9 UT buildings (Moontower, Axis West Campus, Villas on Guadalupe, 21 Pearl…) and
  11 A&M buildings (Domain Northgate, The Aria, The Zone, University Trails, Holleman Crossing,
  The Stack, Otto, Lofts at Wolf Pen Creek, Warehouse & Factory, Sterling, Fifteen12). The test
  only fires when a building lists both ≤ 1-bed and ≥ 3-bed prices, so this is a floor. In the
  20-building sample, 3 are wrong (Villas on 26th, Rambler, The Stack).
- **Other errors:** a struck-through old price is stored as `price_max` (The Jay: "$1,069
  $999*" became 999 to 1,069). Two UT rows have price 0. Beds are strings in all 709 UT
  directory rows and numbers elsewhere. Partial capture on large pages (Rambler: 94 dollar
  amounts on the page not captured).
- **"Not publicly listed", A&M 104:**

  | Count | State of the saved pages | Reading |
  |---|---|---|
  | 30 | No page crawled | 12 have no URL, 18 failed to fetch. Not evidence of anything |
  | 12 | Floor-plan page saved and it contains dollar amounts | Extraction miss, upper bound (The Landing's amounts are promo credits; I checked live and it lists no rents) |
  | 24 | Dollar amounts only on other saved pages | Mostly misses: the price page was not found or is a widget |
  | 9 | Floor-plan page saved, no dollars, site runs on a pricing platform | Miss: prices load by script |
  | 9 | Site crawled, no floor-plan page found | Unknown |
  | 20 | Floor-plan page saved, no dollars, no platform | Plausibly unlisted |

  At most 29 are plausibly unlisted. At least 45 are scraper or crawl misses (inferred from the
  saved pages, not checked live one by one). The A&M directory rows carry no prices, so the
  fallback that priced 74 UT buildings did nothing at A&M.
- **Fix:** decide basis from the price ladder and from "installment / per person" text before
  falling back to type; wire the platform adapters for the platforms that dominate (Entrata 47
  A&M sites, SightMap 18, RealPage 15); record `price_status = not_crawled` separately from
  `not_publicly_listed`.

### F8. Building type and condo labels come from Google's type field (step 7)

- **Checked:** the 37 A&M and 34 UT condo labels against names and Google types.
- **Found:** `merge_candidates.py:41-52` labels a building a condo if the word appears in any
  name or any type from any source. Google tags many apartment complexes
  `condominium_complex`. At A&M 16 of 37 are condo or townhome communities by name; 21 are
  apartment complexes (Domain Northgate, The Zone, The Enclave, Woodlands, The Grand 1501, The
  Landing, Sundance, Saddlewood…). At UT 19 of 34 have no condo word in any name; at least 9 of
  those are apartments or student housing (four Yugo buildings, Hilltop, Tradition on Rio,
  Sentral, Blackstone, Waterloo Flats). "Hall" in an alias makes a dorm (Arbors at Wolf Pen Creek).
- **Missing condos:** the realtor crawl found 28 named condo and townhome communities that
  never got a location and were dropped (Academy Condominiums, Old Oaks, Peachtree, River Ridge
  Townhomes, Woodsman, Chimney Hill, Spring Creek, Canyon Creek, University Place, Deacon…).
  14 more condo entries sit in tier C.
- **Was the realtor crawl effective at A&M?** 229 sites picked, 47 failed to fetch, 51 returned
  anything, 179 candidates, 57 never located. In the final 173, 51 buildings have a realtor
  record but only 2 exist because of it (Hidden Bridge, 517 Southwest Parkway). It cost about
  493 LLM calls, 384 of which returned nothing. `resolve_addresses.py` recovered 10 addresses
  (67 at UT). So: poor yield as run, and most of what it did find was thrown away at the
  locate step.
- **Fix:** take type from the building's own site and name, not Google's type list; give
  name-only condos a location by searching the name with the city (one free address or map
  lookup each) instead of dropping them.

### F9. Website field (step 13)

Counts from a rule-based pass, then corrected by hand.

| | UT (150) | A&M (173) |
|---|---|---|
| The building's own site or its page on an operator or realtor site | about 124 (82%) | about 126 (73%) |
| Campus-directory listing used as the website | 17 | 11 |
| Manager, realtor or HOA home or search page | 9 | 19 |
| Spam domain (`stayus.cfd`, `motelus.cyou`) | 0 | 2 |
| None | 0 | 12 |
| Campus office page on a non-housing entry | 0 | 3 |

Tracking query strings are kept on 57 UT and 39 A&M URLs; Playbook 2 says to strip them
(`build_json.py:31` writes the unstripped seed). Two A&M sites are old-name domains
(pointonredmond.com for The Lory, retreatcollegestation.com for Redpoint).

### F10. Places spend (step 14)

Replayed the whole call tree from cache; no network.

| | UT | A&M |
|---|---|---|
| Calls in log | 547 (364 nearby, 160 text, 23 Reddit lookups) | 373 (138 nearby, 198 text, 37 Reddit lookups) |
| Estimated cost | $19.15 | $13.06 |
| Cost per final building | $0.128 | $0.075 |
| Discovery calls that returned no new place | 350 of 524 (67%), $12.25 | 187 of 336 (56%), $6.55 |
| Final buildings first found by the core grid | 125 of 142 | 116 of 149 |
| Added by the per-neighborhood grids | 5 (235 calls) | 9 (81 calls) |
| Added by text search | 12 (160 calls) | 24 (198 calls) |

- Neighborhoods inside the core square were swept twice. At UT, "apartments", "condominiums",
  "condos for rent" and "private dormitory" added 0 final buildings in 86 calls.
- **Same roster, fewer calls (simulated):** UT: core grid + grids only for the four
  neighborhoods that reach outside the core + three text queries (student apartments,
  condominiums, housing co-op) = 321 calls, $11.24, all 142 final place IDs kept. A&M: core +
  outside-core grids + all text = 321 calls, $11.24, 149 of 149; with four text queries, 218
  calls, $7.63, 147 of 149. Stopping the grid at 200 m cells changes nothing at either campus.
- The brief said to stop and ask at $25. The budget check is per campus
  (`discover_places.py:19`, and `discover_reddit.py:63` uses 30), so the $32.21 total never
  triggered it.
- I did not check the per-call prices against a Google invoice.

### F11. LLM usage and the usage-limit stops (step 15)

- **Method:** rebuilt every prompt offline from cached pages and looked up its hash in
  `data/_llm_cache/`. 1,779 of 1,868 cache entries (95%) matched.

  | Step | Model | Cached calls | Returned `[]` | Input tokens (content) |
  |---|---|---|---|---|
  | Realtor-site pages | haiku | 1,093 | 731 (67%) | about 3.13 M |
  | Amenities | sonnet | 246 | 31 | about 1.93 M |
  | Listings | haiku | 206 | 79 | about 1.03 M |
  | Reddit threads | haiku | 237 | 104 (44%) | about 0.65 M |
  | Not matched (older prompt versions, the 95k-window test) | | 89 | | |

- **Per building:** amenities median 5,400 (UT) to 6,900 (A&M) input tokens and about 600
  output; listings about 3,700 to 4,000 input and about 640 output. Tokens are characters ÷ 4.
- **Why the limit was hit:** each call is a separate `claude -p` process (`llm.py:17`). I ran
  one with a 20-token prompt: it reported 18,597 cache-creation and 9,002 cache-read input
  tokens. That is about 27,600 tokens of fixed context per call (n=1, measured today). Times
  1,868 calls that is about 51 M tokens, against about 6.7 M of real prompt content. Roughly 88%
  of the input volume was overhead (inferred by multiplication). Cache file times show five
  separate bursts over 25 hours, consistent with four interruptions.
- **Design changes:** call the API directly, or run the CLI with a minimal system prompt and
  no tools; batch several pages per call; skip pages with no address or building-like text
  before calling (two thirds of realtor-page calls returned nothing); keep an explicit job
  queue with done / failed / limit states so a stop is resumable and visible.
- **What could be deterministic or cheaper:** realtor index pages on AppFolio and similar
  portals have a fixed structure; Reddit name extraction can be a name-list match once
  candidates exist; amenities already get 1,914 of 2,745 UT rows from the alias map, so the
  LLM pass could run only on pages with prose and on haiku with the quote check as the guard;
  listings should use platform adapters first.
- **Hidden failures:** `llm.py:19-26` returns `None` on timeout or unparseable output with no
  log. Amenities and listings handle that. `discover_pm_sites.py:94` and
  `discover_reddit.py:27` treat `None` as "nothing found" and record the site as `ok`. Today
  all but one prompt has a cached answer, so the final data is complete, but a limit hit
  during those steps would be invisible. `llm.py:22` also accepts any bracketed text as the
  answer; four cached answers are objects, not arrays, and one realtor result in the form
  `{"buildings": [...]}` was silently discarded.

### F12. What each source contributed (step 16)

| Source | Final buildings carrying it (UT / A&M) | Exist only because of it | Cost |
|---|---|---|---|
| Google Places | 142 / 149 | 17 / 58 | $32.21, no human step |
| Campus directory | 87 / 54 | 4 / 8 (2 of the 8 are junk titles) | UT: one free request. A&M: a person runs a script in Chrome |
| Realtor sites | 79 / 51 | 0 / 2 | About 1,093 LLM calls; largest LLM consumer |
| Overture places | 41 / 31 | 0 / 5 (2 are duplicates) | Free; needed anyway for outlines and addresses |
| Reddit | 13 / 15 located; names on 123 / 133 | 0 / 3 | Person logs in; 237 LLM calls; 60 Places calls |

- At A&M, 113 of the 168 in-range directory rows are street-address listings for houses or
  single units. The directory really contributes 55 building rows, with no prices or features.
- Realtor sites matter at UT for condo names and addresses, and almost not at all at A&M as
  run. Next campus: run them only on the few local firms that list communities, after a cheap
  filter, not on every domain a map source returns (229 picked, 51 useful).
- Reddit adds almost no buildings. Its value is the ranking signal and nicknames, and both are
  currently damaged by the matching rules (F2, F4). Keep it only if the login step is removed.
- Overture place records are weak for discovery but the building layer has names that were
  never used (F13).

### F13. The three in-range UT misses (step 2)

- **Palmetto Condominiums:** findable. The Overture building layer the pipeline already
  downloads has an outline named "Palmetto Apartment Complex" at the hand pin. Named
  residential outlines are never used as candidates. The realtor crawl fetched only 5 pages of
  uptownrealtyaustin.com and Palmetto is on none of them.
- **Gateway Apartments:** findable. Overture places has "Gateway Apartments" about 20 m from the hand
  pin, category `historic_site`; `discover_overture.py:56` drops it for the category. Reddit
  also names it once.
- **Park Place Condominiums:** the stated reason is partly right. It is on a realtor page with
  no address. The hand pin in `property_coords.csv` is wrong (F4).
- **The far misses:** Oak Grove, Presidium Tech Ridge and Keystone were found on realtor sites,
  two with a full address, and then dropped because the address index only covers the named
  neighborhoods (`merge_candidates.py:118-127`). The stated reason "not discoverable by area
  search" is true for Places but these three were in hand.

### F14. Run it cold (steps 17, 19)

A new agent could not run a third campus from the docs and `run_campus.sh` alone.

- **Not documented or not scripted:**
  1. `run_campus.sh` starts at the realtor crawl. Places, Overture, the directory step and the
     Reddit fetch must be run by hand first, in an order only Playbook 1 section 6 gives.
  2. The in-browser JavaScript for CoStar directories exists only as a prose description in the
     `discover_ocp.py` docstring. No file to paste.
  3. The Reddit query list is in Playbook 1 prose, not in config; `subreddits` in the config
     lists two per campus and only the first was read.
  4. `run_campus.sh` defaults to the top 170. UT was cut at 150 by hand. A&M kept all 173.
  5. Config keys `pm_radius_m` and `campus_radius_m`, and optional inputs `cand_manual.json`
     and `coord_overrides.json`, are read by code and absent from the config description.
  6. `set -u` without `set -e`: a failed step does not stop the run.
- **Dependencies, none declared:** Python 3 with `rapidfuzz` and the `overturemaps` CLI; Node
  with a global Playwright and the Chrome channel; a logged-in `claude` CLI; zsh; `.env` with
  `GOOGLE_PLACES_API_KEY`.
- **UT or Austin assumptions:** street names in the address pattern
  (`resolve_addresses.py:13-15`: Speedway, Guadalupe, Nueces, Rio Grande, San Gabriel, Pearl,
  Leon, Salado, Duval, Lamar, Whitis, Red River); the alias map's Austin business names; the
  "S.M.A.R.T Housing" vocabulary term (an Austin program; 38 UT buildings, 0 at A&M); address
  points assumed one per address (true in Austin, false in Brazos County).
- **Human steps today:** write the campus config (center, radii, neighborhoods); search for
  extra realtor sites; log in to Reddit and run the fetch; collect the CoStar directory through
  Chrome with a local receiver; review flagged coordinates (50 at A&M, not done); save blocked
  pages by hand; choose the cut; check the flagged merges; restart after each usage limit.
- **Removable:** neighborhoods (cluster the first Places pass; Playbook 1 describes this, no
  code does it); extra realtor sites (derive from the map sources only); Reddit login (use the
  official API with an app token, or drop Reddit); usage-limit restarts (F11); most coordinate
  review (F5). The CoStar directory step cannot be scripted and is worth keeping only where it
  carries prices.
- **A README should contain:** what the system produces; prerequisites and install commands;
  the `.env` format; how to write a campus config with every key; the full run order with the
  human steps marked; where outputs land; how to resume; cost expectations; how to run the two
  eval scripts. A `requirements.txt` needs `rapidfuzz` and `overturemaps`; a `package.json`
  needs `playwright`.

### F15. Code review (steps 18, 20)

Structure is sound: one script per stage, shared helpers, raw pages archived, every network
response cached. The problems are concentrated in name matching, silent failure and cache keys.

Bugs and rough spots with file and line (those not already cited above):

| Where | Problem |
|---|---|
| `merge_candidates.py:36-38`, used at `:92` | `fn_is_unit()` always returns True, so every directory row whose name starts with a digit is dropped. Lost: 12 North, 21 Gramercy Park (A&M); 26 West, 21 Pearl, 21 Rio, 24 Longview, 1883 (UT). 28 of 143 UT rows and 113 of 168 A&M rows hit the rule; 7 and 2 of those are building names, the rest are addresses |
| `enrich_site.py:33-35`, `:50`; `build_json.py:27` | The storage folder and `objectID` are the slug of the name. Two buildings with one name share pages, amenities and prices. A&M has 4 colliding pairs, so 173 rows carry 169 distinct IDs |
| `enrich_site.py:54-55` | `meta.json` short-circuits re-crawls even when the first crawl failed, and does not notice a changed website |
| `enrich_amenities.py:59-61`, `enrich_listings.py:61-62` | Results cached by slug only. Changing the text window (95k to 50k) or the prompt does not invalidate them. The claimed "smaller window on the final pass" cannot be told apart from older results on disk |
| `discover_pm_sites.py:18-22` | The deny pattern matches substrings anywhere: "law", "title", "commercial", "hotel". It rejects `liveatvillawestbryan.com` (vil-LAW-est) and `outlawrealty.com`; 43 UT and 7 A&M domains are denied by the loose words |
| `discover_pm_sites.py:60-64` | 47 A&M and 30 UT sites recorded `fetch_failed` with no retry |
| `discover_reddit.py:66` | Appends "apartments" to every name ("2818 Apartments apartments") |
| `resolve_addresses.py:27` | Silent cap of 400 pages |
| `webtext.py:16-18`, `:24-26` | All fetch and render errors swallowed; a bot-wall page that returns 200 is cached forever (`common.py:83-88`, no expiry) |
| `enrich_amenities.py:47-53` | Any "available" makes a row optional ("Roommate Matching Available") |
| `enrich_amenities.py:64-65`, `enrich_listings.py:86` | Dead code (`pass` branch; a filter ending in `and False`) |
| `build_json.py:36`, `:40` | `verifiedAt` and `scraped_at` are the build date for every row, not the fetch date |
| `discover_overture.py:4` | Docstring names `coords_footprint.py`, which does not exist |
| `discover_places.py:17-19`, `select_roster.py:65-75`, `merge_candidates.py:18-33` | Queries, budget, score weights and all filters are inline constants |
| whole repo | No tests. The name-matching rules have changed several times by the docs' own account and nothing guards them |

**Wasted or repeated work:** 67% and 56% of Places calls (F10); about 51 M tokens of CLI
overhead (F11); 89 LLM answers from superseded prompts; Overture downloaded per neighborhood
with overlapping boxes (data dirs are 699 MB and 639 MB); enrichment ran four times at UT
(`enrich_run.log` to `enrich_run4.log`); amenities for buildings later cut from the roster.

### F16. Data layout and output shape (step 21)

- `data/<campus>/` mixes candidates, three roster stages, ad-hoc logs and outputs in one flat
  folder. `roster_final.json` means 509 buildings at UT and 173 at A&M; the outputs are built
  from `roster_enrich.json`. No run manifest records which inputs and code produced an output.
- **Provenance:** amenity rows and unit rows have a source URL (100%). Building fields do not:
  name, address, coordinates, aliases, type and website have no per-field source, only a
  building-level list of source families and up to 8 URLs. No value has a real date. Playbook 2
  says "every value carries where it came from"; that is true for two of three files.
- **App shape:** `build_json.py` says the outputs mirror the catalogs the app reads. Against
  the field lists in `RESTRUCTURE_CHANGELOG.md` they do not:

  | App reads | Output has |
  |---|---|
  | `buildingImage`, `provider`, `sourceUrl`, `priceBasis` | `photos[]`, `management_company`, `website_url`; no building-level price basis |
  | `property_type` = `condominium` | `condo` |
  | `area` as a slug (`west_campus`) | display name (`West Campus`) |
  | `unit_label`, `layout_display`, `sqft_display`, `price_display`, `rate_period`, `base_rent` | `name`, `beds`+`baths`, `sqft`, `price_label`, `rent_basis`, `price_min` |
  | `features_flat`, `amenities_highlights`, `amenities_summary`, `tiers` | `features` by layer only |

  A mapping step is needed before the app can read these.

### F17. Docs against the code and data (step 23)

Claims not supported:

| Document | Claim | Reality |
|---|---|---|
| RESULTS | Overture alone finds 37/143 (26%) | 28/143 (20%) with the candidate file on disk |
| RESULTS | Top 150 contain 97 old-roster buildings; "the other 53" are new | 95 to 98 names on 87 entries; 63 entries are not in the old roster |
| RESULTS | 12 misses are 4.8 to 42 km out | 11; Duval Villas was found and its hand pin is wrong |
| RESULTS | 105 of 143 hand pins rounded to 4 decimals | 99 |
| RESULTS | A&M: 30 buildings have no website | 12; 18 are fetch failures |
| RESULTS | EVER = Casa Del Sol | Not a rename |
| RESULTS | Amenity recall 74%, 93 comparable | 77% on 91; no script in the repo produces it |
| RESULTS | "Steps now refuse to save a result when the AI read fails" | True for amenities and listings only |
| Playbook 1 | Merged set 905, 816 ranked, 96 in top 150 | 830, 732, 95 to 98 (stale numbers) |
| Playbook 1 | Store only `place_id` long-term | Tracked outputs hold Google addresses, websites and two raw pins |
| Playbook 1 | Never merge Cameron House and Montgomery House | They are one entry |
| Playbook 1 | Stop when a pass adds under 2%; widen radii if under 150 | Neither exists in code; the code takes the top N instead |
| Playbook 1 | Do not trust subset matching for one-word names | Stripping makes names one word and the subset rule still merges two-word names |
| Playbook 2 | Every value carries where it came from | Building fields do not |
| Playbook 2 | Strip tracking query strings | Kept in the output |
| Playbook 2 | Headed browser for sites that still block; queue blocked sites for the user | `render.js` accepts `--headed` but nothing passes it; no queue |
| Playbook 2 | Absent recorded from a yes/no checklist | No code path records absent |
| Playbook 2 | Unit estimate decides how hard to look | Not used in enrichment |
| Playbook 2 | Keep base rent and fee-inclusive rent separate; strikethrough is the old price | No such fields; a struck price was stored as the maximum |
| Playbook 2 | Never ship `pin_unverified` | 10 shipped (RESULTS admits this) |
| `build_json.py` | Shapes mirror what the app reads | They do not (F16) |

Important behavior the docs omit: the final set is "score ≥ 2" at A&M and "top 150" at UT; the
directory rule drops any name starting with a digit; a campus directory URL is used as the
building's website when nothing else exists; building type comes from Google's type list;
`rent_basis` falls back to that type; the address index covers only the named areas, so
candidates with an address outside them are dropped; object IDs are name slugs and can collide;
the alias map is UT-derived.

### F18. Against the original brief (step 24)

| Requirement | Status | Note |
|---|---|---|
| Phase A: reverse-engineer the UT build with CONFIRMED / INFERRED and file:line or commit | Partly | Playbook 2 has 9 CONFIRMED and 1 INFERRED tag, citing files but no line numbers or commits. Playbook 1 has none |
| Phase B: blind UT discovery, per-source coverage, miss diagnosis | Mostly | Done and reproducible. "Smallest source combination reaching 95%" and "buildings only one source found" are not reported. Recall is 90%, under the 95% the brief names |
| `ut_blind_roster.csv`, `ut_coverage_diff.csv`, `tamu_roster.csv` | Not done under those names | `roster_final.csv` per campus is the nearest; there is no coverage-diff file |
| `places_call_log.csv`; never write the key | Done | Key is nowhere in the repo or data |
| Stop and ask above $25 | Partly | Enforced per campus; total was $32.21 |
| Phase C: about 20 buildings, agreement per field, plain-geocoding error | Partly | Amenities done on 22. Coordinates compared, but no per-field agreement table for aliases or listings and no plain-geocoder baseline |
| Phase D: A&M pilot, about 10 buildings enriched, list what broke | Done and exceeded | All 173 enriched; "what broke" table exists |
| 150+ buildings, firm floor | Partly | 173 claimed, about 152 defensible |
| Scope: no Greek houses, no single houses, 30-minute cap | Mostly | Sorority houses fall to tier C by score, not by rule. 1 to 3 single units and 3 on-campus properties are in the A&M set |
| Exact building pin, `coord_method`, never ship unverified | Partly | Method recorded; 10 unverified shipped; 50 flagged unreviewed; complex-level, not building-level |
| Automated check of pin against the building on a map view | Not done | Outline lookup only; no imagery check |
| Aliases, former names, slang, sub-buildings | Partly | Some rebrands caught by address; nicknames not stored as aliases; wrong merges |
| Amenities: implied, small, three-state, evidence type and URL | Mostly | Implied and evidence done. Absent state not implemented |
| Vision review of photos and tours | Not done | Captions and alt text only (stated in the docs) |
| Unit count as a prior for how hard to look | Not done | |
| Per-platform rent adapters | Not done | Copied to `reference/`, not wired |
| OCR for image-only prices | Not done | |
| Rent basis, concessions | Partly | Basis unreliable; concession text captured on 87 UT and 43 A&M rows |
| Schema: unit_count, management_company, photos, per-field `source_urls` | Partly | Unit count is an outline estimate; manager only from the directory; photos only at UT; provenance per building |
| Two playbooks with a known-gaps list and VERBAL NUANCE slots | Done | In `docs/`, not the repo root |
| Stop condition in the discovery playbook | Written, not implemented | |
| Checkpoints after Phase A and B | Not verifiable | No record in the repo |

## 3. Corrected headline numbers

| `RESULTS.md` says | Corrected |
|---|---|
| UT found 128/143 (90%) | 128 by the script's rule (reproduced). 2 are false matches and 2 "misses" are ground-truth pin errors, so about 128 by name; **120 distinct entries** |
| Places only 123/143 | 122 |
| Overture only 37/143 (26%) | 28 (20%) |
| Top 150 contain 97 of the old roster; 53 others | 95 to 98 names on 87 entries; 63 others |
| 12 misses are 4.8 to 42 km out | 11 |
| 105 hand pins rounded to 4 decimals | 99 |
| UT coordinates: 97 matched, median 22 m, 58 within 25 m, 9 over 100 m | 92 matched at similarity ≥ 88: median 22 m, 55 within 25 m, 7 over 100 m. Google pin on the same set: median 22 m |
| UT amenities 74% overall, 83% median, 93 buildings | 76.9%, 86.7%, 91 buildings |
| A&M 173 in tiers A and B | 173 rows, 169 distinct IDs, about 152 defensible |
| A&M 37 condos | 16 condo or townhome communities; 21 mislabeled apartments |
| A&M sites: 140 read, 30 no website, 3 blocked | 140 read; 12 no URL; 18 fetch failures; 3 mislabeled blocked with pages on disk |
| A&M 104 not publicly listed | At most 29 plausibly unlisted; at least 45 misses; 30 never crawled |
| AggieSearch: 132 + 38 named places in range | 168 in range, of which 113 are street-address listings; 55 building rows |

Reproduced without change: both Places costs and call counts; realtor-site counts (243 / 116 /
776 / 67 and 229 / 51 / 179); Reddit counts (120 threads, 187 and 207 names, 88 and 107 in two
or more threads); merged and tier counts (830, 733 in area, 235 A, 274 B; 310, 293, 173); UT and
A&M output counts by type, amenities, prices, unit rows and aliases; coordinate method counts.

## 4. Fix list

**Today**

1. Get commit `7c030ec` purged from GitHub (F1).

**Before running a third campus**

2. Replace the ranking (F2): remove the footprint penalty and single-outline unit estimate,
   stop scoring on source count, match Reddit names exactly, add hard excludes.
3. Fix name normalization and merging (F4): stop stripping distinguishing words, drop the
   subset score, require address or outline agreement to merge or alias.
4. Fix the address key (F5): keep trailing directions, filter by ZIP, handle many points per
   address.
5. Fix `fn_is_unit()` so it tests for a street-type word, not a leading digit (F15).
6. Make object IDs unique (slug plus place ID or address hash) (F15).
7. Fix the two crawl-status bugs (F6) and separate "not crawled" from "no website" and from
   "not publicly listed".
8. Replace per-call `claude -p` with direct API calls or a minimal-context invocation, add a
   job queue with visible failure states, and pre-filter realtor pages (F11).
9. Remove the Austin street names from `resolve_addresses.py`; split the alias map into a
   general file and a per-campus file; drop business names from it.
10. Cut the Places plan to one grid over the core, grids only for areas outside it, and three
    or four text queries; make the budget global (F10).
11. Write the README, `requirements.txt`, `package.json`; make `run_campus.sh` run every
    scripted stage with `set -e`; put Reddit queries and the cut size in the campus config;
    save the CoStar browser snippet as a file (F14).
12. Add tests for name similarity, address normalization, merging and scoring, using the UT
    cases the playbook already lists.

**Added 2026-11-16 after the website and photo check (see `RESULTS.md`), also before a third campus**

12a. Enforce the verify-before-counting rules and `publish_status` (Playbook 1 section 5a,
     Playbook 2 section 6) in `select_roster.py` and `build_json.py`, with a rejects file.
12b. Wire the website ladder into `enrich_site.py`: call `resolve_website.py`, set
     `website_class` and `website_status`, re-fetch every stored URL, report shared URLs.
     Add `neighbor_cities` to both campus configs.
12c. Turn `reference/photo_pass/` into a scripted stage that reads the roster, with a vision
     model call for the visual check and the three photo counts in the QC report.

**Before publishing the A&M data**

13. Remove the 19 entries in F3 and add the six tier-C complexes and the located condos.
14. Add the missing names: The London on The Doce; 2818 Place, 2818 Apartments and Parkway
    Place on Sterling; The Retreat on Redpoint; swap The Tradition and 12 North. Remove the
    wrong aliases in F4 and the EVER / Casa Del Sol link.
15. Correct Ion's coordinate and review the 50 flagged and 10 unverified points, or relabel
    them as complex-level.
16. Re-derive `rent_basis` from price ladders and page text; fix the 11 known A&M buildings.
17. Re-run amenities for the buildings skipped by the status bug; replace realtor-home and
    directory links in `website_url`; drop the two spam URLs; strip tracking parameters.
18. Fix building types (21 false condos, false dorms).
19. Re-check the amenity rows that cite another building's page (9 A&M buildings, 23 UT).
20. Decide what Google-sourced content may be published (F1).

**Later**

21. Wire platform adapters for Entrata, SightMap, RealPage and RentCafe.
22. Use named Overture building outlines and residential-named places as candidates (F13).
23. Per-field provenance and real fetch dates; an output mapping to the app's field names.
24. Photo review, the absent state, base versus fee-inclusive rent, the stop condition.
25. A run manifest and a tidier `data/<campus>/` layout (inputs, stages, logs, out).
26. Fix the wrong pins found in `~/FML_scraper/rentright_buildings/places/property_coords.csv`
    (Duval Villas, Park Place, Marq Uptown, East Campus Graduate Apartments, Tom Green).

## 5. What I could not verify

- **Live rents for 10 buildings per campus.** I checked 20 buildings against the saved pages
  and only 4 live; the saved pages are one to two days old. One live fetch was blocked.
- **Which "not listed" A&M buildings truly publish no price.** The split in F7 comes from the
  saved pages; I checked one live (The Landing).
- **Student relevance.** Judged from names, sources, ratings and my own knowledge of both
  markets, not from tenant data. Borderline calls are marked.
- **A&M names from Reddit that are absent** (Sterling Northgate, Cedar Ridge, Campus Crossing,
  Laurel Ridge, Park Hudson Place). Some may be former names of buildings in the roster. Not
  resolved.
- **Honcho and The Jay** share one stored coordinate and adjacent addresses. Same building or
  not: not resolved. **The Ivy = Briarwood** and other aliases outside the six claimed: not
  checked.
- **Operator portfolios** for Yugo, Landmark, Scion and Asset Living. Only American Campus's
  page gave a usable list (5 of 5 present). A search for the others returned nothing reliable.
- **Coordinates beyond the 24 buildings viewed.** A&M has no hand pins. The UT hand pins proved
  unreliable above 100 m, so the UT median is a noise floor, not a precise error.
- **Google's actual billing** and whether free tiers applied. Costs are the log's estimates.
- **Token overhead per LLM call during the build.** Measured once, today, on this machine; the
  total is a multiplication.
- **Whether usage-limit failures lost realtor or Reddit results at the time.** All prompts have
  cached answers now, so the final data is complete, but the code would not have shown a loss.
- **Run time and the exact number of interruptions.** Inferred from file times.
- **Checkpoints and the "no peeking" rule in the brief.** Nothing in the repo records them.
- **GitHub's caches after a purge.** I confirmed the commit is reachable now; I did not test
  forks, search indexes or third-party mirrors.
