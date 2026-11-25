# Prompt: Audit the campus listing aggregator

You are auditing a system you did not build. Be skeptical. Verify claims by running code and
reading data, not by trusting the docs. Report what is true, including where the docs are wrong.

## Background

`~/FML_rebuild` (GitHub: `Elijahwanghcen/RateMyRent_NewCampus`, public, branch `main`) is a
campus-agnostic pipeline that finds student-relevant housing around a university and collects
each building's location, aliases, amenities and advertised rent. It was built in one long
session on 2026-11-14/15 that was interrupted by usage limits several times.

It was tested by rebuilding UT Austin "blind" and comparing against the existing hand-built UT
data in `~/FML_scraper` (143 buildings, grown from student rent submissions). It was then run
on Texas A&M. The owner's goals:

- 150+ buildings per large campus (firm floor): purpose-built student housing first, then
  apartments students rent, co-ops and private dorms, then condo buildings. No Greek houses,
  no single houses, nothing over a 30-minute drive.
- Exact building coordinates (the owner used to right-click each building in Google Maps).
- Accurate amenities, including small and implied ones, with unknown kept separate from absent.
- Aliases and former names.
- A system that can be pointed at the next campus with little rework.

## Where things are

- `aggregator/`: pipeline scripts. `run_campus.sh` is the intended one-command run.
  Discovery: `discover_places.py`, `discover_overture.py`, `discover_pm_sites.py`,
  `resolve_addresses.py`, `discover_rcp.py`, `discover_ocp.py`, `reddit_fetch.js`,
  `discover_reddit.py`. Then `merge_candidates.py`, `select_roster.py`. Enrichment:
  `enrich_site.py`, `enrich_amenities.py`, `enrich_listings.py`, `build_json.py`.
  Shared: `common.py`, `geo.py`, `webtext.py`, `llm.py`. Eval: `eval_coverage.py`, `eval_amenities.py`.
- `campuses/ut_austin.json`, `campuses/texas_am.json`: campus configs.
- `docs/PLAYBOOK_1_DISCOVERY.md`, `docs/PLAYBOOK_2_ENRICHMENT.md`, `docs/RESULTS.md`: the
  written method and the claimed numbers.
- `data/<campus>/`: all intermediate and final data (most of it gitignored). Final outputs in
  `data/<campus>/out/{buildings,amenities,units}.json` and `qc_report.md`. Ranked roster in
  `roster_final.json` / `.csv`. Raw pages in `raw/<slug>/`. Caches in `cache/` and `data/_llm_cache/`.
- `reference/legacy_ut_scraper/`: the old UT per-platform rent scrapers, copied in but not wired up.
- Ground truth for UT: `~/FML_scraper/properties.csv`,
  `~/FML_scraper/rentright_buildings/places/property_coords.csv`,
  `~/FML_scraper/rentright_buildings/amenities/amenities_features.json`, `~/FML_scraper/fml_catalog.json`.
- `PROMPT.md`: the original brief the system was built against.

## Rules for the audit

- Read-only on `~/FML_scraper`. In `~/FML_rebuild`, do not change pipeline code or data; write
  only your report and any throwaway scripts (put scripts in a scratch folder).
- Everything is cached. Do not make new paid Google Places calls, and do not re-run LLM steps
  at scale (they call the local `claude` CLI and burn the usage limit). Sampling a handful is fine.
- No Reddit access and no CAPTCHA solving. Use the saved corpus in `data/<campus>/cache/`.
- The API key is in the gitignored `.env`. Never print or commit it.
- Web lookups to verify individual buildings are fine (official sites, Google Maps in a browser).

## Part 1: Did it find the buildings?

**UT (has ground truth).**
1. Re-run `eval_coverage.py` against `property_coords.csv` and confirm or correct the claimed
   128 / 143 (90%). Check the matching rule itself: is a "found" really the same building?
   Sample 20 matches and 10 near-misses by hand.
2. For each miss, confirm the stated reason. Could any in-range miss (Palmetto, Gateway
   Apartments, Park Place) have been found with a source the system already has?
3. The final UT set is the top 150 by a "student score". Only 97 of those are in the old
   roster. Judge the other 53: sample 25 and classify each as real student-relevant building,
   real but not student-relevant, duplicate, or junk. Then check which old-roster buildings
   rank below 150 and why. Is the ranking formula in `select_roster.py` doing its job, or was
   it tuned to UT?
4. Duplicates and bad merges: scan `roster_final.json` for buildings within 60 m of each
   other, for aliases that look like a different building, and for one building split in two.
   Give counts and examples.

**Texas A&M (no ground truth).**
5. Build an independent check list of at least 40 known A&M student buildings from sources
   the pipeline did not rank by (e.g. the top names in `reddit_mentions.json`, operator
   portfolio pages for American Campus, Yugo, Landmark, Scion, Asset Living, and your own
   knowledge). Measure how many are in the 173. Reddit's top names include The London,
   Z Islander, The Lofts at Wolf Pen Creek, The Stack, Campus Village, Callaway Villas,
   U Centre: check each explicitly.
6. Sample 30 of the 173 and classify as in Part 1 step 3. Report an estimated precision.
7. Condos: 37 are labeled condo. Are they really condo buildings? Are obvious A&M condo
   communities missing? Was the realtor-site crawl effective at A&M (51 of 229 sites returned
   anything)?
8. Is 173 a real pass of the 150 floor, or is it padded with weak entries? State how many
   you would stand behind.

## Part 2: Is the collected data right?

9. **Coordinates.** For 15 buildings per campus (include all 10 A&M `pin_unverified` and some
   `coord_review` ones), compare the stored lat/lng with the real building on a map. Report
   median and worst error, and whether "address point + outline center" is actually better
   than the Google pin. Check multi-building complexes and leasing-office pins.
10. **Amenities.** Re-run `eval_amenities.py`-style comparison for UT and confirm the claimed
    74% recall. Then judge precision: for 10 buildings per campus, open the evidence quotes
    and source URLs and count amenities that are wrong, misattributed (a nearby business, a
    different building on a shared site), or unsupported. Check that unknown is never
    recorded as absent. Check what happened to the buildings with zero amenities.
11. **Rents.** For 10 buildings per campus compare `units.json` with the live site: are
    prices, beds/baths and `rent_basis` (per bed vs per unit) right? How much of the
    "not publicly listed" share (104 of 173 at A&M) is truly unlisted vs a scraper miss?
12. **Aliases.** Verify the claimed former names (Ion = Aspire, The Aria = Gateway at College
    Station, The Doce = District on Luther, EVER = Casa Del Sol, Fifteen12 = College Edge,
    Grand 1501 = Plantation Oaks) and list wrong ones.
13. **Websites.** How often is `website_url` the wrong site (a manager's home page, an HOA,
    a same-named property elsewhere)?

## Part 3: Was it done efficiently?

14. **Money.** From `places_call_log.csv`: calls and estimated cost per campus, cost per
    final building, and how many calls returned nothing new. Could the same recall be reached
    with fewer calls (fewer text queries, larger quadtree cells, skipping overlapping
    neighborhood sweeps)? Use the cached responses to simulate.
15. **LLM usage.** Count calls in `data/_llm_cache/` by step if you can infer it, and estimate
    tokens per building for amenities and listings. Which steps could be deterministic or use
    a cheaper model without losing accuracy? The build hit the usage limit at least four
    times: what design change would prevent that?
16. **Source value.** For each source, how many final-roster buildings exist only because of
    it, and what did it cost in time, money and human effort? Which sources are not worth
    running at the next campus?
17. **Human steps.** List every point that needs a person (Reddit login, CoStar directory
    through Chrome, manual coordinate checks, neighborhood config). Which can be removed?
18. **Wasted work.** Look for re-crawls, steps that silently saved failed results, caches
    that do not key on what they should, and anything that had to be run more than once.

## Part 4: Is it organized well?

19. **Run it cold.** Following only `README`-level docs and `run_campus.sh`, could a new
    agent run a third campus? Note every undocumented step, hard-coded UT or Austin
    assumption, and missing dependency. (There is no README or requirements file: say what
    they should contain.)
20. **Code.** Review structure, naming, duplication, error handling, resumability, and
    whether failures are visible. Flag real bugs with file and line. Known rough spots to
    check: `fn_is_unit()` in `merge_candidates.py` always returns True; street-name list in
    `resolve_addresses.py` contains Austin street names; filters and score weights are
    inline constants; no tests.
21. **Data layout.** Is `data/<campus>/` sensibly organized? Is provenance (source and date
    per value) actually present in the outputs, as the playbooks say it should be? Do the
    output shapes match what the existing app reads (`~/FML_scraper/RESTRUCTURE_CHANGELOG.md`
    lists the fields)?
22. **Repo hygiene.** The repo is public. Check the full git history for the API key, raw
    Google Places data, scraped page content, or personal data. One commit was force-pushed
    to remove raw Google data: confirm nothing remains reachable. Check `.gitignore`.
23. **Docs vs reality.** List every claim in the two playbooks and `RESULTS.md` that the code
    or data does not support, and every important behavior of the code the docs omit.
24. **Against the brief.** Go through `PROMPT.md` and mark each requirement done, partly done
    or not done (e.g. vision review of photos, per-platform rent adapters, the 20-building
    accuracy test, stop conditions).

## Deliverable

Write `~/FML_rebuild/docs/AUDIT.md`:

1. A one-paragraph verdict, then a scorecard table: discovery recall, discovery precision,
   coordinates, amenities, rents, aliases, cost efficiency, reusability, organization. Each
   row gets a grade, the measured number behind it, and how confident you are.
2. Findings ranked by impact. Each one: what you checked, what you found, the evidence
   (file path, count, example), and the fix.
3. A corrected version of any headline number in `RESULTS.md` that you could not reproduce.
4. A prioritized fix list split into: before running a third campus, before publishing the
   A&M data, and later.
5. What you could not verify and why.

State sample sizes for every estimate. Mark anything you inferred without checking as inferred.
Do not commit or push; leave the report as a local file.
