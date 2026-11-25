"""Why a building on the FML_Data roster was missing or thin in Rebuild, and the rule that closes that hole on the next campus.

Each cause has one rule. classify() picks a cause from the pinned backend and URL.
The completeness check prints the rule next to every reference building the roster lacks.
"""

RULES = {
    "ranked_below_cut": (
        "A real building can rank below the top-N cut (small condo, few reviews, no Reddit). "
        "Pinned and ADD buildings are unioned into the enrich set after the cut. "
        "campus_completeness.py reports every reference name that the cut dropped."
    ),
    "condo_unit_landlord": (
        "Individual condos live on a manager portfolio (Uptown Realty /communities/<slug>/), not as their own Google place. "
        "Crawl the portfolio index and keep one roster row per community URL. Lock that URL. "
        "Do not merge two unit pages that share a street into one building."
    ),
    "no_google_presence": (
        "Some buildings have no Places listing and no aggregator card. "
        "The reference list (university housing, an existing RMR/catalog export, a PM portfolio) is a source, not a nice-to-have. "
        "A name that appears only there is still added, with needs_review, instead of waiting for Places."
    ),
    "entrata_bot_wall": (
        "Plans are on /<city>/<slug>/(student|conventional)/ or an entrata.<site> host, and Cloudflare stops headless Chrome. "
        "Pin that portal URL. Do not freeze text_plan_list over a bot wall. "
        "A headed rescue uses a price mode (split_total, base_only, promo_current, installment, unpriced, empty). "
        "The first DOM try leaves DOM_PROFILE unset so it matches FML_Data; a profile retry is opt-in."
    ),
    "rentcafe_bot_wall": (
        "RentCafe answers 403 to a plain client and hides fees on buttons or ysi JSON. "
        "Pin rentcafe_ysi or rentcafe_inline. A saved html_files path is banned in production. "
        "Rescue mode base_only or split_total when the card shows one figure or a fee total."
    ),
    "leaseleads_markup": (
        "LeaseLeads replaced .floor-plan-card with data-ll-floor-plan-card and "
        "data-ll-floor-plan-lease-terms JSON (price, base_rent, price_with_fees). "
        "detect() adds leadeleads_terms when that attribute is in the HTML. "
        "The FML_Data villas_wp parser is owned by the scraper repo; do not treat a zero-row villas_wp run as an empty building."
    ),
    "per_room_type": (
        "Yugo and similar sites list a room type per tile (product-tile, gtm_name), not one card per plan. "
        "Pin gtm_name. Do not let text_plan_list win. Fingerprint product-tile -> yugo."
    ),
    "layouts_only": (
        "The site lists plans and no public rent (no_public_pricing, vnue grid, Rise). "
        "Keep the placeholder row, including a label that starts with '(' and price_status not_publicly_listed, "
        "and keep params.reason. Do not drop it and do not invent a rent from an aggregator."
    ),
    "university_or_coop_table": (
        "University and co-op rates are HTML tables, often one page for many houses. "
        "Route housing.utexas.edu paths to ut_housing_nueces, ut_housing_dobie or ut_rates_table, "
        "and collegehouses.org to collegehouses_rates with params.house. "
        "university_rates is only the generic fallback. One fetch per shared rates URL."
    ),
    "directory_lead_only": (
        "A campus off-campus directory (housing.offcampus.*, RentCollegePads, OCP) is a lead list. "
        "It is not a rent source. Completeness still counts every directory name. "
        "The rent row comes from the manager page, or from an explicit no_public_pricing pin when that is all the school publishes."
    ),
    "manager_portal_filter": (
        "AppFolio, Duda and Westside portals list many buildings. Pin address_match, listings_url and fallback_range. "
        "appfolio_smart may run for a new campus, but a locked pin's filter list is not replaced by a geo guess."
    ),
    "shared_feed_filter": (
        "One ACC (or similar) feed serves several buildings, split by location_filter. "
        "Pin every filter. Auto-pick must not keep only the first token that matches "
        "(Texan & Vintage is both filters, not Texan alone). Fetch the feed once per source_id."
    ),
    "repli360_feed_shorter": (
        "repli360_feed dedupes widget tabs and can return fewer rows than the DOM parser. "
        "For a locked repli360 building, run the pinned DOM parser. Use the feed only when the DOM run is blocked."
    ),
    "query_string_matters": (
        "A floor-plans URL can carry the lease term (?_lease_term=fall). "
        "A locked website keeps its query string. enrich_site strips '?' only when the URL is not locked."
    ),
    "name_collision": (
        "Distinct buildings that share a leasing office or a brand (Quarters houses, 1883 Cameron vs Montgomery, "
        "Town Lake names, Halstead vs Nueces) stay separate pins. Do not alias them together because the street matches."
    ),
}


def classify(prop):
    """Return a cause id for one FML_Data property."""
    backend = prop.get("backend") or ""
    url = (prop.get("url") or "").lower()
    host = url.split("/")[2] if "://" in url else ""
    params = prop.get("params") or {}
    name = prop.get("property_name") or ""
    if backend == "uptown_realty" or "uptownrealty" in host:
        return "condo_unit_landlord"
    if backend == "no_public_pricing" or backend in ("vnue_grid_static", "rise_units"):
        return "layouts_only"
    if backend == "villas_wp" or "floor-plan-card" in url:
        return "leaseleads_markup"
    if backend == "yugo":
        return "per_room_type"
    if backend in ("ut_housing_nueces", "ut_housing_dobie", "ut_rates_table", "collegehouses_rates"):
        return "university_or_coop_table"
    if backend == "ut_offcampus_directory" or "offcampus" in host or "rentable.co" in host:
        return "directory_lead_only"
    if backend in ("appfolio_listings", "duda_appfolio_feed", "westside_prose") or params.get("address_match") or params.get("fallback_range") or params.get("listings_url"):
        return "manager_portal_filter"
    if backend == "acc_lightning" and params.get("location_filter"):
        return "shared_feed_filter"
    if backend == "repli360":
        return "repli360_feed_shorter"
    if backend == "entrata_pp" or "entrata." in host or "/student/" in url:
        return "entrata_bot_wall"
    if backend in ("rentcafe_ysi", "rentcafe_inline"):
        return "rentcafe_bot_wall"
    if backend == "gogetter_wc_floorplans" and "?" in (prop.get("url") or ""):
        return "query_string_matters"
    if "quarters" in name.lower() or name.lower().startswith("1883") or "town lake" in name.lower():
        return "name_collision"
    return "ranked_below_cut"


def rule(cause):
    return RULES.get(cause, RULES["ranked_below_cut"])
