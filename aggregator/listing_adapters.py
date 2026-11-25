"""Platform adapters for floor plans + rent: find the leasing platform's own data feed and read it.

Why this exists (UT audit, 2026-11-16): the first rebuild read only the floor-plans page TEXT through an LLM and
got 1,474 rows where the legacy UT scraper got 2,396. The page text misses listings because
  - the plans are not in the HTML at all: a widget loads them after the page opens (Repli360/RRAC, Knock,
    RentCafe, RealPage, SightMap, Yugo, Entrata). A plain fetch that returns >400 chars of menu text was accepted
    as "the page", so the widget never ran.
  - the plans sit in a <script> JSON block or a JSON API (ACC lightning, wp-json Entrata, jd-fp, Duda collections,
    RealPage CMS proxy). to_text() drops every <script>.
  - one plan has many rows (rate tiers, room types, each available unit). An LLM asked for "floor plans" returns
    one row per plan, and long pages are cut at 30k chars.
So: detect the feed from markers in the raw HTML, build the adapter's parameters automatically, call the legacy
extractor (reference/legacy_ut_scraper/extractors - deterministic, no LLM), and only fall back to the LLM read
when no adapter returns rows.

Adding a platform: add a rule to detect() (marker regex -> backend + params). Site-specific parsers that only fit
one manager's website go in HOST_ADAPTERS or the campus config key "listing_adapters": {"host": "backend"}.
"""
import json, os, re, subprocess, sys
from pathlib import Path
from urllib.parse import urlparse
from common import ROOT, norm_name, is_ils

LEGACY = ROOT / "reference" / "legacy_ut_scraper" / "extractors"
sys.path.insert(0, str(LEGACY))
import http_extractors as HX  # noqa: E402

DOM_JS = LEGACY / "dom_extract.js"
VERSION = 10         # bump when detection/adapters change: cached listings.json with a lower version is redone
                     # 10 (11-24): plan-image post-pass (plan_images.py), jsonld_floorplans, elementor_fp_posts

# Leasing platforms that publish a machine-readable feed. If one is fingerprinted and no adapter returned rows,
# the building is flagged in the QC report (a parser is missing or the markers changed).
FEED_MARKERS = [
    ("acc_lightning", r"/api/lightning/floorplans/\d+"),
    ("repli360", r"rrac_|rracfloorplan|repli360"),
    ("sightmap", r"sightmap\.com/(?:embed|app/api)"),
    ("knock", r"knockdoorway|doorway\.knck\.io|doorway-api\.knockrentals"),
    ("realpage_cms", r"cmssitemanager/callback\.aspx"),
    ("realpage", r"realpage|rp-fp|leasestar|onesite"),
    ("rentcafe", r"window\.ysi|rentcafe|cdngeneral"),
    ("entrata", r"entrata|prospectportal"),
    ("jonah", r"jd-fp"),
    ("appfolio", r"appfolio"),
    ("g5", r"g5marketingcloud|g5-assets|g5cdn"),
    ("yugo", r"product-tile[^>]{0,200}data-gtm-name|yugo\.com/en-us/global"),
    ("landmark", r"themes/landmark-"),
    ("fp_units_modal_v2", r"floor-plan-units-modal-v2"),
    ("jsonld_floorplan", r'"@type"\s*:\s*"floorplan"'),
    ("elementor_fp_posts", r"type-floor_plans"),
    ("leaseleads_terms", r"data-ll-floor-plan-lease-terms"),
    ("gmh_floorplans", r"wp-json/gmh-student/floorplans"),
]

# Parsers written for one manager's site layout. Host -> backend. Campus config "listing_adapters" adds to this.
HOST_ADAPTERS = {
    "uptownrealtyaustin.com": "uptown_realty", "spearheadproperties.com": "spearhead_static",
    "resolutereco.com": "resolute_static", "9hundred.com": "ninehundred_static",
    "liveatsangabrielsquareaustin.com": "sgs_static", "villasonnueces.com": "mmc_ajax",
    "villasatsangabriel.com": "vsg_static", "villason26.com": "vnue_grid_static",
    "theballparkaustin.com": "ballpark_static", "westsidegroup.com": "westside_prose",
    "24longview.com": "webflow_product7", "grandmarcaustin.com": "webflow_cms_floorplans",
    "rambleratx.com": "rambler_lvbode",
    "thesinclairut.com": "sinclair_wp", "riseatwestcampus.com": "rise_units",
}
DOM_BACKENDS = {"rentcafe_cards", "entrata_pp", "landmark", "rambler_lvbode", "sinclair_wp", "repli360", "jonah_fp", "yugo", "ion_wp",
                "rentcafe_ysi", "rise_units", "villas_wp", "gogetter_wc_floorplans", "g5_sniff", "realpage_sniff"}
UNIT_PRICED = {"buildium_search", "appfolio_listings", "duda_appfolio_feed", "uptown_realty"}
_acc_cache = {}      # list_id -> API json (shared by sister buildings on one ACC page)


def _host(u):
    return urlparse(u or "").netloc.lower().replace("www.", "")


def _https(u):
    return re.sub(r"^http://", "https://", u or "")


def _toks(s):
    return {re.sub(r"(?<=\d)(st|nd|rd|th)$", "", t) for t in re.findall(r"[a-z0-9]+", (s or "").lower())}


def _addr_match(b):
    """Strings an address-filtered portal row must contain: '2812 rio grande' style street + the building name."""
    out = [b["canonical_name"]]
    m = re.match(r"\s*(\d+)\s+((?:[NSEW]\.?\s+|West\s+|East\s+|North\s+|South\s+)?)([A-Za-z0-9]+(?:\s+[A-Za-z]+)?)", b.get("address") or "")
    if m:
        out.append(f"{m.group(1)} {m.group(3)}".strip())
        out.append(f"{m.group(1)} {m.group(2).strip()[:1]} {m.group(3)}".replace("  ", " ").strip())
    return [x for x in dict.fromkeys(out) if x]


def acc_locations(list_id):
    if list_id not in _acc_cache:
        _acc_cache[list_id] = json.loads(HX.fetch(f"https://www.americancampus.com/api/lightning/floorplans/{list_id}"))
    locs = set()
    for t in _acc_cache[list_id].get("Terms", []):
        for a in t.get("Attributes", []):
            locs.update((a.get("Filters") or {}).get("LocationFilter") or [])
    return sorted(locs)


def acc_pick_location(list_id, names):
    """A multi-building ACC community (The Block) lists every building on one feed, split by LocationFilter.
    Pick the filter whose words all appear in this building's name. None = single-building feed (take all)."""
    locs = acc_locations(list_id)
    if len(locs) < 2:
        return None, locs
    best = None
    for loc in locs:
        lt = _toks(loc.split("_", 1)[-1])
        for n in names:
            if lt and lt <= _toks(n) and (best is None or len(lt) > best[0]):
                best = (len(lt), loc)
    return (best[1] if best else "NO_MATCH"), locs


def detect(b, meta, html_by_kind, cfg):
    """Return ordered adapter candidates [{backend, url, params, why}] from markers in the crawled HTML."""
    pages = meta.get("pages", {})
    fp_url = pages.get("floorplans") or pages.get("home") or meta.get("seed") or b.get("website")
    if not fp_url:
        return []
    blob = "\n".join(html_by_kind.values())
    low = blob.lower()
    names = [b["canonical_name"]] + list(b.get("aliases") or [])
    host = _host(fp_url)
    origin = f"https://{urlparse(fp_url).netloc}"
    c = []
    add = lambda backend, url, params, why: c.append({"backend": backend, "url": url, "params": params or {}, "why": why})

    hosts = {**HOST_ADAPTERS, **(cfg.get("listing_adapters") or {})}
    page_level = {"uptown_realty", "spearhead_static", "resolute_static", "westside_prose"}
    for u in [fp_url] + [pages[k] for k in pages if k.startswith(("alt", "home"))]:
        h = _host(u)
        if h in hosts:
            # page_level parsers read the building's own page; the rest read that site's floor-plans page
            fpu = next((pages[k] for k in pages if _host(pages[k]) == h and re.search(r"floor-?plans?", pages[k], re.I)), u)
            add(hosts[h], _https(u if hosts[h] in page_level else fpu), {}, f"host {h}")
            break

    m = re.search(r"/api/lightning/floorplans/(\d+)", blob)
    if m:
        loc, locs = acc_pick_location(int(m.group(1)), names)
        if loc != "NO_MATCH":
            add("acc_lightning", fp_url, {"list_id": int(m.group(1)), **({"location_filter": loc} if loc else {})}, "ACC lightning API id in page")
    if "wp-content" in low or "wp-json" in low:
        api = f"{origin}/wp-json/theme/entrata/v1/floor-plans"
        try:
            j = json.loads(HX.fetch(api))
            if j:
                add("wp_entrata_json", fp_url, {"api_url": api}, "wp-json entrata endpoint answers")
        except Exception:
            pass
        if "gmh-student" in low:
            gmh = f"{origin}/wp-json/gmh-student/floorplans/categories"
            try:
                j = json.loads(HX.fetch(gmh))
                if j:
                    add("wp_entrata_json", fp_url, {"api_url": gmh}, "GMH floorplans categories (not the theme entrata path)")
            except Exception:
                pass
    # LeaseLeads JSON is parsed by the synced villas_wp DOM extractor (FML_Data a953774).
    # Do not also schedule leadeleads_terms here: an HTTP skim returns fewer rows and
    # would skip the DOM parser once any priced row exists.
    if "collegehouses.org" in (fp_url or ""):
        house = re.sub(r"(?i)\b(the|house|co-?op)\b", " ", b.get("canonical_name") or "")
        house = " ".join(house.split())
        add("collegehouses_rates", "https://collegehouses.org/rates/", {"house": house.split()[0] if house else b.get("canonical_name")},
            "college houses shared rates page; params.house picks the block")
    if re.search(r"housing\.utexas\.edu", fp_url or ""):
        if "nueces-rates" in fp_url or "2400-nueces" in fp_url:
            add("ut_housing_nueces", fp_url, {}, "dedicated Nueces rate table")
        elif "dobie" in fp_url:
            add("ut_housing_dobie", fp_url, {}, "dedicated Dobie articles")
        else:
            add("ut_rates_table", fp_url, {}, "UT housing Type/Rate table")
    if re.search(r"cmssitemanager/callback\.aspx", low):
        add("realpage_cms_proxy", _https(fp_url), {}, "RealPage CMS proxy callback in page")
    m = re.search(r"sightmap\.com\\?/embed\\?/([a-z0-9]+)", low)
    if m:
        try:
            e = HX.fetch(f"https://sightmap.com/embed/{m.group(1)}")
            a = re.search(r"https://sightmap\.com/app/api/v1/[a-z0-9]+/sightmaps/\d+", e.replace("\\/", "/"))
            if a:
                add("sightmap", fp_url, {"api_url": a.group(0)}, "SightMap embed -> unit API")
        except Exception:
            pass
    m = re.search(r"doorway-api\.knockrentals\.com/v1/property/(\w+)", blob) or \
        re.search(r"knockDoorway\.init\(\s*'[^']*'\s*,\s*'community'\s*,\s*'(\w+)'", blob)
    if m:
        add("knock_doorway", fp_url, {"property_id": m.group(1)}, "Knock doorway id in page")
    if "jd-fp" in low:
        add("jonah_detail_json", _https(fp_url), {}, "Jonah jd-fp markers")
    # 2026-11-25 A&M rescue of saved-HTML buildings (all plain HTTP):
    if "lv-master-template-theme" in low:
        add("lv_fp_ajax", fp_url, {}, "Landmark lv-master-template: cards from admin-ajax fp_submit_search")
    if "leaseleadsembed(" in low or "embed.leaseleads.co/" in low:
        add("leaseleads_embed", fp_url, {}, "LeaseLeads iframe: floorPlans JSON (Referer = property site)")
    if '"$inventory"' in low and '"models":[{' in low:
        add("inventory_models", fp_url, {}, "$inventory models JSON on /models")
    if "data-floorplan-price" in low and "rentcafe" in low:
        add("rentcafe_cards", fp_url, {}, "RentCafe oculus cards (data-floorplan-*), headless; plain HTTP is walled")
    if "beswifty-core" in low or "swifty_floorplan_section_details_with_ajax" in low:
        add("swifty_fp_ajax", fp_url, {}, "beSwifty: cards from admin-ajax swifty_floorplan_section_details_with_ajax")
    if "floor-plan-units-modal-v2" in low:
        add("fp_units_modal_v2", fp_url, {}, "units-modal-v2 component")
    m = re.search(r"SiteAlias:\s*'(\w+)'", blob)
    if m and "appfolio-listings" in low:
        add("duda_appfolio_feed", fp_url, {"feed_url": f"{origin}/rts/collections/public/{m.group(1)}/runtime/collection/appfolio-listings/query-data?pageSize=100",
                                           "address_match": _addr_match(b)}, "Duda AppFolio collection")
    for u in [fp_url, b.get("website") or ""]:
        if ".managebuilding.com" in u:
            add("buildium_search", _https(u), {"address_match": b.get("address_match") or []}, "Buildium portal")
            break
    if b.get("appfolio_portal"):
        add("appfolio_listings", fp_url, {"portal": b["appfolio_portal"], "address_match": b.get("address_match") or _addr_match(b)},
            "AppFolio portal from resolutions")
    for m in dict.fromkeys(re.findall(r"(?<![a-z0-9.-])((?!www\.)[a-z0-9-]+)\.appfolio\.com", low)):
        if m in ("images", "cdn", "www", "passport", "help"):
            continue
        add("appfolio_smart", fp_url, {"portal": f"https://{m}.appfolio.com", "names": names[:3],
                                        "lat": b.get("lat"), "lng": b.get("lng"), "street": _street_key(b.get("address"))},
            f"AppFolio portal {m} (property filter / 150 m / same street)")
    if "webflow" in low and "w-dyn-item" in low:
        add("webflow_cms_floorplans", fp_url, {}, "Webflow CMS list")

    m = re.search(r"https://app\.repli360\.com/admin/rrac-website-script/[A-Za-z0-9=]+", blob)
    if m:
        add("repli360_feed", fp_url, {"script_url": m.group(0)}, "Repli360 widget script -> template-render feed")
    # browser (Playwright) parsers - only where the markers say the layout is there
    dom = [("repli360", r"rrac_|rracfloorplan"), ("landmark", r"themes/landmark-"),
           ("yugo", r"product-tile"), ("villas_wp", r"floor-plan-card"),
           ("rambler_lvbode", r"class=\"[^\"]*card floorplan"), ("sinclair_wp", r"room-type-content"),
           ("ion_wp", r"fp-option-rates"), ("gogetter_wc_floorplans", r"floorplan-cards"),
           ("rise_units", r"unit-detail-modal"), ("rentcafe_ysi", r"window\.ysi|fp-container|rentcafe\.com"),
           ("g5_sniff", r"g5marketingcloud|g5-assets|g5cdn"),
           ("entrata_pp", r"entrata|prospectportal|fp-card|fp-data-wrapper|fp-grid-item|floorplan-item"),
           ("realpage_sniff", r"realpage|rp-fp|leasestar")]
    if "floorplanslist" in low or "show-inclusive-fee-button" in low or 'id="fp-container-' in low or \
            ("resource.rentcafe.com" in low and 'class="card-title' in low):
        rd = cfg["dir"] / "raw" / meta.get("slug", "")
        add("rentcafe_inline", fp_url, {"html_files": [repo_rel(rd / f"{k}.html") for k in ("floorplans", "floorplans2", "fingerprint", "home")]},
            "RentCafe page data (ysi JSON / fee buttons / fp-container cards)")
    if re.search(r'"@type"\s*:\s*"floorplan"', low):
        rd1 = cfg["dir"] / "raw" / meta.get("slug", "")
        add("jsonld_floorplans", fp_url, {"html_files": [repo_rel(rd1 / f"{k}.html") for k in ("floorplans", "floorplans2", "home")]},
            "schema.org FloorPlan JSON-LD (name, size, beds, baths, layoutImage)")
    if "type-floor_plans" in low:
        rd2 = cfg["dir"] / "raw" / meta.get("slug", "")
        add("elementor_fp_posts", fp_url, {"html_files": [repo_rel(rd2 / f"{k}.html") for k in ("floorplans", "floorplans2", "home")]},
            "WordPress Elementor 'floor_plans' post cards")
    if re.search(r'"@type"\s*:\s*"offer"', low):
        rd0 = cfg["dir"] / "raw" / meta.get("slug", "")
        add("jsonld_offers", fp_url, {"html_files": [repo_rel(rd0 / f"{k}.html") for k in ("floorplans", "floorplans2", "fpdetail", "home")]},
            "schema.org JSON-LD Offers in page")
    if re.search(r"(reslife|housing)\.[a-z]+\.edu/", fp_url or ""):
        # university rate page shared by every hall: pick this building's section by name
        nm = [re.sub(r"(?i)\b(apartments?|the|hall|of|at)\b", "", n).strip() for n in names]
        add("university_rates", fp_url, {"section_names": [x for x in nm if len(x) > 3],
                                         "html_files": [repo_rel(cfg["dir"] / "raw" / meta.get("slug", "") / "floorplans.html")]},
            "university housing rate table, section by building name")
    # Entrata ProspectPortal: the plans live on /<city>/<property-slug>/(student|conventional)/, not on the marketing
    # "Floor Plans" page. The legacy UT scraper always pointed entrata_pp there (1883atx.com/austin/1883-at-cameron/student/).
    # Only portal links whose slug shares a word with the building name count (sites carry template links to other
    # properties: Scandia's page linked an Indianapolis portal).
    # FML_scraper (Noble 2500): the marketing page embeds the Entrata portal in an <iframe>; read the iframe's page
    for m in re.finditer(r"""<iframe[^>]+src=["']([^"']*(?:prospectportal\.com|/Apartments/module/|entrata\.)[^"']*)["']""", blob, re.I):
        u = m.group(1).split("#")[0]
        if "application" not in u.lower() and "login" not in u.lower():
            add("entrata_pp", _https(u), {}, "Entrata portal in an iframe on the marketing page")
            break
    portals = entrata_portals(blob, fp_url, names, [cfg.get("city", "")] + [c if isinstance(c, str) else c.get("name", "")
                                                                          for c in cfg.get("neighbor_cities", [])])
    if portals:
        add("entrata_pp", portals[0], {"extra_urls": portals[1:3]} if len(portals) > 1 else {}, "Entrata portal path /<city>/<slug>/student|conventional/")
    for backend, rx in dom:
        if re.search(rx, low) and not any(x["backend"] == backend for x in c):
            if backend == "realpage_sniff" and any(x["backend"] == "realpage_cms_proxy" for x in c):
                continue
            prm = {}
            if backend == "yugo":
                # tiles carry the residence's short name ("Apex"), which is the page title before the "|"
                t = re.search(r"<title>\s*([^|<]+?)\s*\|", html_by_kind.get("floorplans") or html_by_kind.get("home") or "")
                prm = {"gtm_name": t.group(1)} if t else {}
            add(backend, fp_url, prm, f"marker /{rx[:28]}/")
    return c


def buildium_search(url, params):
    """Buildium / ManageBuilding public ApartmentSearch page: the page embeds every listing as a list of
    {"Key","Value"} pairs. One manager portal usually lists many buildings: keep rows whose address/building name
    contains one of params["address_match"] (street names or numbers). No match list = keep all (portal is the
    building's own)."""
    import html as _h
    origin = re.match(r"(https://[^/]+)", url).group(1)
    page = HX.fetch(f"{origin}/Resident/PublicPages/ApartmentSearch.aspx")
    i = page.find('"Listings":[[')
    if i < 0:
        return []
    depth, j = 0, i + len('"Listings":')
    for k in range(j, len(page)):
        depth += page[k] == "["; depth -= page[k] == "]"
        if depth == 0:
            break
    rows, match = [], [m.lower() for m in params.get("address_match") or []]
    for lst in json.loads(page[j:k + 1]):
        d = {x["Key"]: _h.unescape(str(x.get("Value") or "")) for x in lst}
        where = " ".join([d.get("buildingname", ""), d.get("propertyname", ""), d.get("mapLink", "").replace("+", " ")]).lower()
        if match and not any(m in where for m in match):
            continue
        beds = re.match(r"(\d+)", d.get("bedtypedesc", "")) or (re.search(r"studio", d.get("bedtypedesc", ""), re.I) and "0")
        baths = re.match(r"([\d.]+)", d.get("bathtypedesc", ""))
        rows.append(HX._row(unit_or_floorplan_label=f"{d.get('buildingname') or d.get('propertyname')} - {d.get('unittype', '')}".strip(" -"),
                            beds=(beds.group(1) if hasattr(beds, "group") else beds) or "", baths=baths.group(1) if baths else "",
                            sqft=d.get("squarefootage") or "", base_rent=HX._num(d.get("listingrent")) or "", price_basis="base",
                            availability=("available " + d["availabilitydate"]) if d.get("availabilitydate") else "",
                            price_status="listed" if HX._num(d.get("listingrent")) else "not_publicly_listed"))
    return rows


HX.EXTRACTORS["buildium_search"] = buildium_search


PORTAL = re.compile(r"""href=["']([^"'#?]*/[a-z0-9-]+/[a-z0-9-]+/(?:student|conventional)/?)["']""", re.I)
NAME_STOP = {"the", "at", "on", "of", "and", "apartments", "apartment", "apts", "student", "living", "college", "station",
             "austin", "bryan", "condos", "townhomes", "new", "tx"}


def entrata_portals(blob, base, names, cities=()):
    from urllib.parse import urljoin
    want = {t for n in names for t in _toks(n)} - NAME_STOP
    out = []
    for m in PORTAL.finditer(blob):
        u = urljoin(base, m.group(1))
        if not u.endswith("/"):
            u += "/"
        slug = urlparse(u).path.strip("/").split("/")[-2]
        city_segs = " ".join(urlparse(u).path.strip("/").split("/")[:-2]).replace("-", " ").lower()
        if cities and not any(c.lower() in city_segs for c in cities):
            continue                # portal for the same brand in another city (Scandia -> /indianapolis/)
        if want & (_toks(slug.replace("-", " ")) - NAME_STOP) and u not in out:
            out.append(u)
    # the property's own domain first, then *.prospectportal.com / entrata.<domain>
    out.sort(key=lambda u: ("prospectportal" in u or "//entrata." in u, len(u)))
    return out


PROFILE = os.path.expanduser("~/.fml_dom_profile")
HEADED_OK = os.environ.get("FML_ALLOW_HEADED", "1") == "1"   # set 0 on a machine with no display


# Rebuild-owned DOM scripts, kept out of the synced FML_Data dom_extract.js
REBUILD_DOM_JS = {"rentcafe_cards": Path(__file__).resolve().parent / "dom_rentcafe_cards.js"}


def _dom(cand, env_extra):
    npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    script = REBUILD_DOM_JS.get(cand["backend"], DOM_JS)
    out = subprocess.run(["node", str(script), cand["backend"], cand["url"], json.dumps(cand["params"])],
                         capture_output=True, text=True, timeout=480,
                         env={**os.environ, "NODE_PATH": npm_root, **env_extra}).stdout
    j = json.loads(out.strip().splitlines()[-1])
    return j.get("rows", []), j.get("status", "ok")


def repo_rel(path):
    """Path as stored in listing_config.json: relative to the repo root, so a config works on any checkout."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _abs_params(params):
    """Resolve repo-relative params.file / params.html_files against ROOT (configs store them relative)."""
    params = dict(params or {})
    fix = lambda f: f if os.path.isabs(f) else str(ROOT / f)
    if isinstance(params.get("file"), str):
        params["file"] = fix(params["file"])
    if params.get("html_files"):
        params["html_files"] = [fix(f) for f in params["html_files"]]
    return params


def _run(cand):
    """Run one adapter. Browser adapters that hit a Cloudflare wall are retried the way the legacy scraper got
    through: (1) headless, (2) headless with a persistent profile (clearance cookie survives between runs),
    (3) a visible browser with that profile. Interactive CAPTCHAs are never solved; those stay blocked and are
    flagged for a hand-saved rescue file (data/<campus>/rescues/<objectID>.json)."""
    backend = cand["backend"]
    cand = dict(cand, params=_abs_params(cand.get("params")))
    try:
        if backend in DOM_BACKENDS:
            rows, status = [], "not_run"
            ladder = [{}, {"DOM_PROFILE": PROFILE}] + ([{"DOM_PROFILE": PROFILE, "DOM_HEADED": "1", "DOM_CHALLENGE_WAIT_S": os.environ.get("FML_SOLVE_WAIT_S", "300")}] if HEADED_OK else [])
            for i, env in enumerate(ladder):
                if "DOM_PROFILE" in env:
                    # Chrome allows one process per profile directory; the build runs 6 threads. Take turns.
                    import fcntl
                    with open(PROFILE + ".lock", "w") as lk:
                        fcntl.flock(lk, fcntl.LOCK_EX)
                        rows, status = _dom(cand, env)
                else:
                    rows, status = _dom(cand, env)
                if status != "blocked_bot_wall":
                    if i:
                        status = f"{status} (after cloudflare retry {i})"
                    break
            return rows, status
        rows = HX.EXTRACTORS[backend](cand["url"], cand["params"])
        return rows or [], "ok" if rows else "no_rows"
    except Exception as e:
        return [], f"error: {str(e)[:120]}"


def _keep_discovered_row(row):
    """Drop blank labels. Keep an explicit unlisted placeholder (`(no public pricing...)`)."""
    from listing_post import keep_row
    return keep_row(row)


def leadeleads_terms(url, params):
    """Read LeaseLeads `data-ll-floor-plan-lease-terms` JSON. The old `.floor-plan-card` DOM parser matches nothing on these pages."""
    html = ""
    for f in (params or {}).get("html_files") or []:
        try:
            html += Path(f).read_text(errors="replace")
        except OSError:
            pass
    if not html:
        html = HX.fetch(url)
    rows = []
    for m in re.finditer(r"data-ll-floor-plan-lease-terms='(\[.*?\])'", html):
        try:
            terms = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(terms, list) or not terms:
            continue
        window = html[max(0, m.start() - 2000):m.end() + 800]
        name_m = re.search(r'data-ll-floor-plan-name="([^"]+)"', window) or re.search(r"<h[1-4][^>]*>\s*([^<]{2,80}?)\s*</h[1-4]>", window)
        filters = {}
        fm = re.search(r"data-filters='(\{.*?\})'", window)
        if fm:
            try:
                filters = json.loads(fm.group(1))
            except json.JSONDecodeError:
                filters = {}
        term = next((t for t in terms if "annual" in str(t.get("name") or "").lower()), terms[0])
        base = term.get("base_rent")
        total = term.get("price_with_fees")
        if total == base:
            total = ""
        name = (name_m.group(1).strip() if name_m else "") or f"{filters.get('bedrooms', '?')} bed"
        rows.append(HX._row(
            unit_or_floorplan_label=re.sub(r"\s+", " ", name),
            beds=filters.get("bedrooms", ""),
            sqft=filters.get("size_min") or "",
            base_rent="" if base in (None, "") else base,
            total_price_with_mandatory_fees="" if total in (None, "") else total,
            price_basis="base" if base not in (None, "") else "",
            availability=filters.get("available_date") or "See site",
            price_status="listed" if base not in (None, "") else "not_publicly_listed",
        ))
    return rows


HX.EXTRACTORS["leadeleads_terms"] = leadeleads_terms


def headed_rescue(url, params):
    """Rows saved by hand from a real browser.

    Legacy shape: {"source_url", "rows": [legacy rows]}.
    Plan shape from ingest_headed_rescues.py: {"floor_plans": [...], "mode": "split_total"|...}.
    Modes: split_total, base_only, promo_current, installment, unpriced, empty.
    """
    from rescue_prices import units_from_rescue
    d = json.loads(open(params["file"]).read())
    mode = (params or {}).get("mode") or d.get("mode")
    if d.get("floor_plans") or d.get("plans") or mode in ("empty", "marketing", "unpriced"):
        rows = units_from_rescue(d, mode)
        return [HX._row(**{k: v for k, v in r.items() if k in HX._row()}) for r in rows]
    return [HX._row(**{k: v for k, v in r.items() if k in HX._row()}) for r in d.get("rows", [])]


HX.EXTRACTORS["headed_rescue"] = headed_rescue


def _js_array(h, var):
    """Bracket-match a JS array literal assigned to <var> (`ysi.floorplansList = [...]`)."""
    i = h.find(var)
    if i < 0:
        return None
    j = h.find("[", i)
    depth, k = 0, j
    for k in range(j, len(h)):
        depth += h[k] == "["; depth -= h[k] == "]"
        if depth == 0:
            break
    try:
        return json.loads(h[j:k + 1])
    except Exception:
        return None


def rentcafe_inline(url, params):
    """RentCafe / Yardi sites embed every floor plan as JSON in the page: ysi.floorplansList (Beds, Baths, MinSqFt,
    MinRent, MaxRent, AvailableCount) and ysi.unitsList. Found 2026-11-17 on Willow Oaks through the Chrome extension.
    The page is often behind Cloudflare, so a copy the crawler already saved (params.html_file) is read first;
    a live fetch is the fallback. No browser, no LLM."""
    h = None
    for f in params.get("html_files") or []:
        if os.path.exists(f):
            t = open(f, errors="replace").read()
            if "floorplansList" in t or "show-inclusive-fee-button" in t or 'id="fp-container-' in t or \
                    ("resource.rentcafe.com" in t and 'class="card-title' in t):
                h = t; break
    if h is None:
        h = HX.fetch(url)
    plans = _js_array(h, "floorplansList") or []
    if not plans:
        return rentcafe_fee_buttons(h) or rentcafe_cards(h)
    units = _js_array(h, "unitsList") or []
    names = {}
    # card markup: <div id="fp-container-867073"> ... <h2 class="property-title h4">Efficiency</h2>
    for m in re.finditer(r'id=["\']fp-container-(\d+)["\'][\s\S]{0,6000}?class=["\'][^"\']*property-title[^"\']*["\'][^>]*>\s*([^<]{1,60}?)\s*<', h, re.I):
        names.setdefault(m.group(1), m.group(2).strip())
    for u in units:                      # unitsList carries the plan name when the card markup differs
        if u.get("FloorplanId") and u.get("FloorplanName"):
            names.setdefault(str(u["FloorplanId"]), u["FloorplanName"])
    rows = []
    for f in plans:
        rmin = HX._num(f.get("MinRent")); rmax = HX._num(f.get("MaxRent"))
        n_av = f.get("AvailableCount")
        rows.append(HX._row(
            unit_or_floorplan_label=names.get(str(f.get("Id"))) or f.get("FloorplanName") or f"Floorplan {f.get('Id')}",
            beds=f.get("Beds", ""), baths=f.get("Baths", ""), sqft=f.get("MinSqFt") or "",
            base_rent=rmin if rmin and rmin >= HX.MIN_PLAUSIBLE_RENT else "", price_basis="base" if rmin else "",
            availability=" — ".join(x for x in [f"{n_av} available" if n_av is not None else "",
                                                 f"advertised range ${int(rmin)}-${int(rmax)}" if rmin and rmax and rmax > rmin else ""] if x),
            price_status="listed" if rmin and rmin >= HX.MIN_PLAUSIBLE_RENT else "not_publicly_listed"))
    return rows


HX.EXTRACTORS["rentcafe_inline"] = rentcafe_inline


def repli360_feed(url, params):
    """Repli360 / RRAC widget, read from its own server instead of a browser. The widget script
    app.repli360.com/admin/rrac-website-script/<token> carries `var site_id = 'NNNN'`; the cards come from
    POST app.repli360.com/admin/template-render. That host is not behind the property's bot protection
    (found 2026-11-17 in Chrome on Marq Uptown, whose own domain started blocking headless browsers).
    Same fields as the legacy browser parser (dom_extract.js repli360)."""
    import urllib.request, html as _h
    sid = params.get("site_id")
    if not sid:
        js = HX.fetch(params["script_url"])
        m = re.search(r"var site_id = '(\d+)'", js)
        sid = m.group(1) if m else None
    if not sid:
        return []
    body_q = f"site_id={sid}&action=&ready_script=dom_load&template_type=&source=&property_id=&zpopUp="
    req = urllib.request.Request("https://app.repli360.com/admin/template-render", data=body_q.encode(),
                                 headers={"User-Agent": HX.UA, "Referer": url,
                                          "Content-Type": "application/x-www-form-urlencoded"})
    page = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
    card_rx = re.compile(r'<div[^>]*class="[^"]*\brracFloorplan\b([^"]*)"([^>]*)>([\s\S]*?)(?=<div[^>]*class="[^"]*\brracFloorplan\b|$)')
    rows, seen = [], set()
    for m in card_rx.finditer(page):
        cls, attrs, body = m.group(1), m.group(2), m.group(3)[:20000]

        def a(k):
            mm = re.search(k + r"""\s*=\s*["']([^"']*)["']""", attrs, re.I)
            return mm.group(1) if mm else ""
        h2 = re.search(r"<h2[^>]*>([\s\S]*?)</h2>", body)
        name = _h.unescape(re.sub(r"<[^>]+>|\s+", " ", h2.group(1)).strip()) if h2 else a("data-fpName")
        detail = re.search(r'class="decp"[\s\S]*?<p[^>]*>([\s\S]*?)</p>', body)
        detail = re.sub(r"<[^>]+>|\s+", " ", detail.group(1)).strip() if detail else ""
        price = re.search(r'class="rrac-price[^"]*"[^>]*>([\s\S]*?)</', body)
        price = HX._num(re.sub(r"<[^>]+>", "", price.group(1))) if price else ""
        call = "call-for-pricing" in body and price == ""
        pmin, pmax = HX._num(a("data-min-price")), HX._num(a("data-max-price"))
        rent = "" if call else (price if price != "" else pmin)
        baths = re.search(r"([\d.]+)\s*bath", detail, re.I)
        img = re.search(r'<img[^>]+(?:data-src|src)="([^"]+)"', body)
        key = (name, rent, a("data-size"))
        if not name or key in seen:
            continue
        seen.add(key)
        try:
            dates = ", ".join(json.loads(a("data-available-date") or "[]")[:3])
        except Exception:
            dates = a("data-available-date")
        rng = f"advertised range ${int(pmin)}-${int(pmax)}" if pmin != "" and pmax != "" and pmax > pmin else ""
        rows.append(HX._row(unit_or_floorplan_label=name, beds=a("data-bed"), baths=baths.group(1) if baths else "",
                            sqft=a("data-size"), base_rent=rent, price_basis="base" if rent != "" else "",
                            availability=" — ".join(x for x in ["Available" if "available" in cls else "Unavailable",
                                                                  f"move-in: {dates}" if dates else "", rng] if x),
                            layout_image_url=img.group(1) if img else "",
                            price_status="listed" if rent != "" else "not_publicly_listed"))
    return rows


HX.EXTRACTORS["repli360_feed"] = repli360_feed


# ---------------------------------------------------------------- ports from FML_scraper (2026-11-17)

def _street_key(addr):
    """'3628 S Hampton Ct. - 116, Bryan' -> (3628, 'hampton')"""
    m = re.match(r"\s*(\d+)\s+(?:[NSEW]\.?\s+|north\s+|south\s+|east\s+|west\s+)?([A-Za-z0-9]+)", addr or "", re.I)
    return (int(m.group(1)), m.group(2).lower()) if m else None


def appfolio_smart(url, params):
    """AppFolio public listings portal, matched to ONE building without hand config.

    FML_scraper matched with hand-typed address strings per building (Preservation Square: '901 w 22nd' + '904 w 21st')
    and, for some, the portal's own property filter (?filters[property_list]=Lone Star Lofts). A complex spans several
    street numbers (Richmond Ridge: roster 3620 S Hampton Ct, units at 3628/3629), so one address string misses.
    Order: (1) property filter by the building's names; (2) markers within params.radius_m (150) of the building's
    coordinates; (3) same street name and house number within +-80. Markers carry lat/lng, rent_range, unit_specs."""
    from common import haversine_m
    portal = params["portal"].rstrip("/")

    def markers(u):
        h = HX.fetch(u)
        mk = re.search(r"markers:\s*(\[[^\n]*\])", h)
        return json.loads(mk.group(1)) if mk else []
    allm = markers(portal + "/listings")
    picked, how = [], ""
    for n in params.get("names") or []:
        from urllib.parse import quote
        sub = markers(f"{portal}/listings?filters%5Bproperty_list%5D={quote(n)}")
        if sub and len(sub) < len(allm):
            picked, how = sub, f"property filter '{n}'"
            break
    if not picked and params.get("lat") is not None:
        picked = [m for m in allm if m.get("latitude") and
                  haversine_m(params["lat"], params["lng"], m["latitude"], m["longitude"]) <= params.get("radius_m", 150)]
        how = "within %d m of the building" % params.get("radius_m", 150)
    if not picked and params.get("street"):
        num, st = params["street"]
        picked = [m for m in allm if (k := _street_key(m.get("address"))) and k[1] == st and abs(k[0] - num) <= 80]
        how = f"same street, number within 80 of {num}"
    rows = []
    for m in picked:
        specs = m.get("unit_specs", "")
        bm = re.search(r"(\d+)\s*bd", specs); thm = re.search(r"(\d+(?:\.\d+)?)\s*ba", specs); sm = re.search(r"([\d,]+)\s*Sq", specs)
        rent = HX._num(m.get("rent_range"))
        rows.append(HX._row(unit_or_floorplan_label=f"{m.get('address', '').split(',')[0]} — {specs}",
                            beds=bm.group(1) if bm else ("0" if "Studio" in specs else ""), baths=thm.group(1) if thm else "",
                            sqft=sm.group(1).replace(",", "") if sm else "", base_rent=rent, price_basis="base" if rent else "",
                            availability=f"listed vacancy (matched by {how})",
                            price_status="listed" if rent else "not_publicly_listed"))
    return rows


HX.EXTRACTORS["appfolio_smart"] = appfolio_smart


def rentcafe_cards(h):
    """Newer RentCafe template (2026): no ysi.floorplansList and no fee buttons. Each plan is a server-rendered card
    <div id="fp-container-<id>"> with <h2 class="card-title">A1</h2>, 'N Bed', 'N Bath', 'NNN Sq. Ft.',
    'Starting at $725.00' (or 'Call for details'), and a plan image on resource.rentcafe.com.
    Found 2026-11-17 on Dwell at 1600 and 100 Park through Chrome; the same cards are in any saved copy of the page."""
    import html as _h
    rows = []
    parts = re.split(r'(?=<div[^>]+id="fp-container-\d+")', h)
    if len(parts) < 2:
        # 'featured floor plans' variant (Sundance & Sausalito): no fp-container wrapper; each plan starts at its
        # <h2 class="card-title"> and its beds/baths/sqft sit in separate <li> items
        parts = re.split(r'(?=<h2[^>]*class="[^"]*card-title)', h)
    for p in parts[1:]:
        p = p[:15000]
        t = _h.unescape(re.sub(r"<[^>]+>", " ", p)).replace("\xa0", " ")
        t = re.sub(r"\s+", " ", t)
        # the card ends at its own tour / waitlist buttons; a 'Call for details' card has no price of its own
        t = re.split(r"Schedule a Tour|Apply to Waitlist|Get Notified", t, flags=re.I)[0]
        if re.search(r"call for details|inquire for details", t, re.I) and not re.search(r"\$\s?\d", t.split("Call for details")[0]):
            t = re.sub(r"\$\s?[\d,.]+", "", t)
        nm = re.search(r'<h2[^>]*class="[^"]*card-title[^"]*"[^>]*>([\s\S]*?)</h2>', p)
        name = _h.unescape(re.sub(r"<[^>]+>|\s+", " ", nm.group(1))).strip() if nm else ""
        beds = re.search(r"(\d+|Studio)\s*Bed", t, re.I)
        baths = re.search(r"([\d.]+)\s*Bath", t, re.I)
        sqft = re.search(r"([\d,]{3,6})\s*Sq\.?\s*Ft", t, re.I)
        price = re.search(r"(?:Starting at|From)?\s*\$\s?([\d,]{3,6})(?:\.\d\d)?", t)
        img = re.search(r'<img[^>]+src="(https://resource\.rentcafe\.com/[^"]+)"', p)
        rent = HX._num(price.group(1)) if price else ""
        if rent != "" and rent < HX.MIN_PLAUSIBLE_RENT:
            rent = ""
        b = beds.group(1) if beds else ("0" if re.search(r"\bstudio\b", name + " " + t[:200], re.I) else "")
        rows.append(HX._row(unit_or_floorplan_label=name or "floor plan", beds="0" if b.lower() == "studio" else b,
                            baths=baths.group(1) if baths else "", sqft=sqft.group(1).replace(",", "") if sqft else "",
                            base_rent=rent, price_basis="base" if rent != "" else "",
                            availability="starting price on the card" if rent != "" else "card shows no price (call for details)",
                            layout_image_url=img.group(1) if img else "",
                            price_status="listed" if rent != "" else "not_publicly_listed"))
    return rows


def rentcafe_fee_buttons(h):
    """FML_scraper rentcafe_ysi fallback: sites without ysi.floorplansList put base / mandatory fee / total on each
    card's fee-breakdown button (a.show-inclusive-fee-button data-fp_base_charge / _inclusive_charge / _total_charge).
    Static HTML attributes, so no browser is needed once the page is in hand."""
    rows = []
    for m in re.finditer(r"<a[^>]*show-inclusive-fee-button[^>]*>", h, re.I):
        tag = m.group(0)
        g = lambda k: (re.search(k + r"""=["']([^"']*)["']""", tag) or [None, ""])[1]
        aria = g("aria-label")
        name = (re.search(r"for floor plan\s+(.+?),", aria, re.I) or re.search(r"floor plan\s+(\S+)", aria, re.I) or [None, ""])[1]
        onclick = g("onclick")
        beds = (re.search(r"'floorplan_size':'(\d+)", onclick) or [None, ""])[1]
        sqft = (re.search(r"'square_footage':'([\d,]+)'", onclick) or [None, ""])[1].replace(",", "")
        base, total = HX._num(g("data-fp_base_charge")), HX._num(g("data-fp_total_charge"))
        rows.append(HX._row(unit_or_floorplan_label=name or "floor plan", beds=beds, sqft=sqft, base_rent=base,
                            total_price_with_mandatory_fees=total if total != base else "",
                            price_basis="base" if base != "" else "",
                            availability=f"mandatory fees ${g('data-fp_inclusive_charge')}" if g("data-fp_inclusive_charge") else "",
                            price_status="listed" if base != "" else "not_publicly_listed"))
    return rows


def advertised_range(url, params):
    """FML_scraper fallback_range, automated: a page that prices nothing per plan but states a property-wide range
    ('Rates starting at $1,085', '$899 - $1,250') becomes ONE row labelled as a range. Only used when every other
    extractor returned no priced rows, and only for text on the building's own pages."""
    t = ""
    for f in params.get("html_files") or []:
        if os.path.exists(f):
            from webtext import to_text
            t += "\n" + to_text(open(f, errors="replace").read(), limit=200000)
    m = re.search(r"(?:starting at|starting from|rates? (?:as low as|from|starting at)|from only|as low as)\s*\$\s?([\d,]{3,6})(?:\*|\.00)?"
                  r"(?:\s*(?:-|–|to)\s*\$\s?([\d,]{3,6}))?", t, re.I)
    if not m:
        return []
    lo = HX._num(m.group(1)); hi = HX._num(m.group(2)) if m.group(2) else ""
    if not lo or lo < HX.MIN_PLAUSIBLE_RENT:
        return []
    return [HX._row(unit_or_floorplan_label="property-wide advertised range", base_rent=lo, price_basis="base",
                    availability=f"page states '{m.group(0).strip()}'" + (f" (up to ${int(hi)})" if hi else ""),
                    price_status="listed")]


HX.EXTRACTORS["advertised_range"] = advertised_range


def university_rates(url, params):
    """University housing rate page (TAMU reslife.tamu.edu/rates/, UT housing.utexas.edu rate tables): one page lists
    every hall/apartment, each under a heading '<Name> ... Rates' followed by one or more tables.
    FML_scraper's ut_rates_table used a hand-set row filter per building; here the section is found by the building's
    own name in a heading. Each table's header says the period ('Monthly Rate' vs 'Fall or Spring Semester') and the
    text above it says whether it is per person/bedroom or per whole apartment - both are kept on the row
    (rate_period, and 'per person'/'by apartment' in the label) and nothing is converted."""
    import html as _h
    h = None
    for f in params.get("html_files") or []:
        if os.path.exists(f):
            h = open(f, errors="replace").read(); break
    h = h or HX.fetch(url)
    txt = lambda x: _h.unescape(re.sub(r"<[^>]+>|\s+", " ", x)).strip()
    want = [w.lower() for w in params.get("section_names") or []]
    heads = list(re.finditer(r"<h[1-6][^>]*>([\s\S]*?)</h[1-6]>", h, re.I))
    start = end = None
    for i, m in enumerate(heads):
        t = txt(m.group(1)).lower()
        if start is None and "rate" in t and any(w in t for w in want):
            start = m.end()
            nxt = [x for x in heads[i + 1:] if "rate" in txt(x.group(1)).lower()]
            end = nxt[0].start() if nxt else len(h)
    if start is None:
        return []
    sec = h[start:end]
    rows = []
    for tm in re.finditer(r"<table[\s\S]*?</table>", sec, re.I):
        before = txt(sec[max(0, tm.start() - 400):tm.start()]).lower()
        basis = "per person" if re.search(r"per person|per bedroom|per bed", before) else ("whole apartment" if "total apartment" in before or "by apt" in before else "")
        trs = re.findall(r"<tr[\s\S]*?</tr>", tm.group(0), re.I)
        if not trs:
            continue
        head = [txt(c) for c in re.findall(r"<t[hd][^>]*>([\s\S]*?)</t[hd]>", trs[0], re.I)]
        for tr in trs[1:]:
            cells = [txt(c) for c in re.findall(r"<t[hd][^>]*>([\s\S]*?)</t[hd]>", tr, re.I)]
            if len(cells) < 2:
                continue
            for j, c in enumerate(cells[1:], 1):
                amt = HX._num(c) if "$" in c else ""
                if amt == "":
                    continue
                col = head[j] if j < len(head) else ""
                period = "month" if re.search(r"month", col, re.I) else ("semester" if re.search(r"semester", col, re.I) else "")
                tier = re.sub(r"(?i)monthly rate|rate|fall or spring semester\*?", "", col).strip()
                bb = re.search(r"(one|two|three|four|five|\d)\s*br?\b", cells[0], re.I)
                words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
                beds = (words.get(bb.group(1).lower()) or bb.group(1)) if bb else ""
                ba = re.search(r"(one|two|three|four|\d)\s*bath", cells[0], re.I)
                rows.append(HX._row(unit_or_floorplan_label=" ".join(x for x in [cells[0], tier and f"({tier})", basis and f"[{basis}]",
                                                                                  period and f"[per {period}]"] if x),
                                    beds=beds, baths=(words.get(ba.group(1).lower()) or ba.group(1)) if ba else "",
                                    base_rent=amt if period == "month" else "",
                                    price_basis="base" if period == "month" else "",
                                    availability=f"university rate: ${int(amt)} per {period or 'period'}" + (f", {basis}" if basis else ""),
                                    price_status="listed" if period == "month" else "not_publicly_listed"))
    return rows


HX.EXTRACTORS["university_rates"] = university_rates


def jsonld_offers(url, params):
    """schema.org structured data: many leasing sites publish each floor plan as a JSON-LD Offer
    (itemOffered.numberOfBedrooms / numberOfBathroomsTotal / accommodationFloorPlan.floorSize + image, price,
    availabilityStarts). Found 2026-11-17 on the apts247 vendor sites (The Ivy, The Grand 1501, Regency Gardens) and
    on ResMan, AppFolio-marketing and other A&M sites - 12 buildings across both campuses. Vendor-neutral: it is the
    data search engines read, so it is usually present even when the visible cards are drawn by a widget."""
    out, seen = [], set()
    pages = []
    for f in params.get("html_files") or []:
        if os.path.exists(f):
            pages.append(open(f, errors="replace").read())
    if not pages:
        pages = [HX.fetch(url)]

    def walk(x, acc):
        if isinstance(x, dict):
            if x.get("@type") == "Offer" and isinstance(x.get("itemOffered"), dict):
                acc.append(x)
            for v in x.values():
                walk(v, acc)
        elif isinstance(x, list):
            for v in x:
                walk(v, acc)
    for h in pages:
        for m in re.finditer(r"<script[^>]*application/ld\+json[^>]*>([\s\S]*?)</script>", h, re.I):
            try:
                d = json.loads(m.group(1))
            except Exception:
                continue
            offers = []
            walk(d, offers)
            for o in offers:
                it = o["itemOffered"]
                fp = it.get("accommodationFloorPlan") or {}
                name = it.get("name") or fp.get("name") or ""
                size = (fp.get("floorSize") or it.get("floorSize") or {})
                size = size.get("value") if isinstance(size, dict) else size
                price = HX._num(o.get("price") if o.get("price") is not None else (o.get("priceSpecification") or {}).get("price"))
                key = (name, price, size)
                if not name or key in seen:
                    continue
                seen.add(key)
                img = fp.get("image") or it.get("image") or ""
                img = img[0] if isinstance(img, list) and img else (img.get("url") if isinstance(img, dict) else img)
                ok = price != "" and price >= HX.MIN_PLAUSIBLE_RENT
                out.append(HX._row(
                    unit_or_floorplan_label=name, beds=it.get("numberOfBedrooms", ""),
                    baths=it.get("numberOfBathroomsTotal", it.get("numberOfFullBathrooms", "")),
                    sqft=int(size) if isinstance(size, (int, float)) else (size or ""),
                    base_rent=price if ok else "", price_basis="base" if ok else "",
                    availability=" — ".join(x for x in [(o.get("availability") or "").rsplit("/", 1)[-1],
                                                         f"available {o['availabilityStarts']}" if o.get("availabilityStarts") else "",
                                                         o.get("description") or ""] if x),
                    layout_image_url=img or "", price_status="listed" if ok else "not_publicly_listed"))
    return out


HX.EXTRACTORS["jsonld_offers"] = jsonld_offers


def _saved_or_live(url, params):
    out = [open(f, errors="replace").read() for f in params.get("html_files") or [] if os.path.exists(f)]
    return out or [HX.fetch(url)]


def jsonld_floorplans(url, params):
    """schema.org FloorPlan blocks (Rank Math 'FloorPlan' schema). Found 2026-11-24 on Brazos Oaks, whose cards are
    drawn by script but whose page head lists every plan: isPlanForApartment 'A2', floorSize 710, numberOfBedrooms,
    numberOfBathroomsTotal, layoutImage. No prices in this block (they come from another adapter or stay unpriced)."""
    out, seen = [], set()

    def walk(x, acc):
        if isinstance(x, dict):
            t = x.get("@type"); t = t if isinstance(t, list) else [t]
            if "FloorPlan" in t:
                acc.append(x)
            for v in x.values():
                walk(v, acc)
        elif isinstance(x, list):
            for v in x:
                walk(v, acc)
    for h in _saved_or_live(url, params):
        for m in re.finditer(r"<script[^>]*application/ld\+json[^>]*>([\s\S]*?)</script>", h, re.I):
            try:
                d = json.loads(m.group(1))
            except Exception:
                continue
            acc = []
            walk(d, acc)
            for f in acc:
                name = f.get("name") or f.get("isPlanForApartment") or ""
                name = name.get("name", "") if isinstance(name, dict) else name
                if not name or name in seen:
                    continue
                seen.add(name)
                size = f.get("floorSize"); size = size.get("value") if isinstance(size, dict) else size
                img = f.get("layoutImage") or f.get("image") or ""
                img = img[0] if isinstance(img, list) and img else (img.get("url") or img.get("contentUrl") or "" if isinstance(img, dict) else img)
                out.append(HX._row(unit_or_floorplan_label=name, beds=f.get("numberOfBedrooms", ""),
                                   baths=f.get("numberOfBathroomsTotal", f.get("numberOfFullBathrooms", "")),
                                   sqft=HX._num(size) if size else "", layout_image_url=img,
                                   availability="plan listed in the page's FloorPlan schema (no price there)",
                                   price_status="not_publicly_listed"))
    return out


HX.EXTRACTORS["jsonld_floorplans"] = jsonld_floorplans


def elementor_fp_posts(url, params):
    """WordPress + Elementor 'Posts' widget over a floor_plans post type: <article class="... type-floor_plans">
    with a thumbnail <img>, <h3 class="elementor-post__title"> and an excerpt '1 bed | 1 bath | 408sqft'.
    One manager's College Station template (liveat<name>collegestation.com: Parkway Circle, Arbor Square, College Main,
    The Gables, Redstone, Scandia, Villa West, Walden Pond - 8 buildings). Prices are not on these cards."""
    import plan_images as PI
    import lxml.html
    out, seen = [], set()
    for h in _saved_or_live(url, params):
        root = lxml.html.fromstring(h)
        for art in root.xpath("//article[contains(concat(' ', normalize-space(@class), ' '), ' type-floor_plans ')]"):
            t = art.xpath(".//*[contains(@class,'elementor-post__title')]")
            name = PI._text(t[0]).strip() if t else ""
            ex = art.xpath(".//*[contains(@class,'elementor-post__excerpt')]")
            ex = PI._text(ex[0]) if ex else ""
            if not name or name in seen:
                continue
            seen.add(name)
            m = PLAN_LINE.search(ex)
            ims = PI._imgs(art, url)
            out.append(HX._row(unit_or_floorplan_label=name,
                               beds=("0" if m and m.group("beds").lower() in ("studio", "efficiency") else (m.group("beds") if m else "")),
                               baths=m.group("baths") if m else "", sqft=(m.group("sqft") or "").replace(",", "") if m else "",
                               layout_image_url=ims[0][0] if ims else "",
                               availability="page lists the plan with no price", price_status="not_publicly_listed"))
        if out:
            break
    return out


HX.EXTRACTORS["elementor_fp_posts"] = elementor_fp_posts


PAGE_ORDER = ("floorplans", "floorplans2", "fpdetail", "fingerprint", "home")


def attach_images(b, slug, rows, html_by_kind, meta, cfg, fetch=True):
    """Post-pass after any adapter: give rows without a layout image the plan image their page shows
    (plan_images.py). Hand-checked overrides: data/<campus>/plan_image_overrides.json {slug: {plan name: url}}.
    Returns (added, still_missing)."""
    import plan_images as PI
    pages_meta = meta.get("pages") or {}
    kinds = [k for k in PAGE_ORDER if k in html_by_kind] + [k for k in html_by_kind if k not in PAGE_ORDER and k.startswith("alt")]
    pages = [(html_by_kind[k], pages_meta.get(k) or pages_meta.get("floorplans") or b.get("website") or "") for k in kinds]
    ov_p = cfg["dir"] / "plan_image_overrides.json"
    ov = (json.loads(ov_p.read_text()).get(slug) or {}) if ov_p.exists() else {}
    ov = ov.get("plans", ov) if isinstance(ov, dict) and "plans" in ov else ov
    added = PI.attach_layout_images(rows, pages, fetch=HX.fetch if fetch else None, overrides=ov, verify=fetch)
    return added, sum(1 for r in rows if not r.get("layout_image_url"))


def weak_images(rows):
    return sum(1 for r in rows if "check by eye" in (r.get("layout_image_how") or ""))


PLAN_LINE = re.compile(
    r"(?P<beds>studio|efficiency|\d)\s*(?:bed(?:room)?s?|br|bd)\b[^\n$]{0,12}?(?P<baths>\d(?:\.\d)?)\s*(?:bath(?:room)?s?|bth|ba)\b"
    r"(?:[^\n$]{0,16}?(?P<sqft>[\d,]{3,5})\s*(?:sq\.?\s*ft|sqft|square feet|sf)\b)?", re.I)
PRICE = re.compile(r"\$\s?([\d,]{3,6})(?:\.\d\d)?")


def text_plan_list(url, params):
    """Deterministic replacement for the LLM page read on simple sites. Many small sites (WordPress templates such as
    the RealPage-managed 'liveat<name>collegestation.com' group, Wix, Webflow) print each plan as
        <plan name>
        1 bed | 1 bath | 480 sqft
        [Starting at $X]
    Reads the saved floor-plans page text: the plan line gives beds/baths/sqft, the nearest non-empty line above is
    the name, a $ amount within the next 3 lines (or on the same line) is the price. No price -> unpriced row
    (these sites often publish none: 'contact us about availability'). Nothing is guessed."""
    pages = (open(f, errors="replace").read() for f in params.get("html_files") or [] if os.path.exists(f))
    return _text_plan_rows(pages)


def _text_plan_rows(pages):
    """Plan lines from page HTML; the first page that yields rows wins (shared by text_plan_list and text_plan_live)."""
    from webtext import to_text
    out, seen = [], set()
    for html in pages:
        if not html:
            continue
        lines = [l.strip() for l in to_text(html, keep_links=False, limit=300000).split("\n")]
        lines = [l for l in lines if l]
        for i, l in enumerate(lines):
            m = PLAN_LINE.search(l)
            if not m:
                continue
            name = ""
            before = l[:m.start()].strip(" |·-–:")
            if len(before) >= 2:
                name = before
            else:
                for j in range(i - 1, max(-1, i - 3), -1):
                    if not PLAN_LINE.search(lines[j]) and not PRICE.search(lines[j]) and 1 < len(lines[j]) < 60:
                        name = lines[j]; break
            if JUNK_NAME.search(name or ""):
                name = ""
            beds = "0" if m.group("beds").lower() in ("studio", "efficiency") else m.group("beds")
            pm = PRICE.search(l[m.end():]) or next((PRICE.search(x) for x in lines[i + 1:i + 4]
                                                    if PRICE.search(x) and not PLAN_LINE.search(x)), None)
            price = HX._num(pm.group(1)) if pm else ""
            if price != "" and price < HX.MIN_PLAUSIBLE_RENT:
                price = ""
            key = (name, beds, m.group("baths"), m.group("sqft"), price)
            if key in seen:
                continue
            seen.add(key)
            out.append(HX._row(unit_or_floorplan_label=name or f"{beds} bed / {m.group('baths')} bath",
                               beds=beds, baths=m.group("baths"), sqft=(m.group("sqft") or "").replace(",", ""),
                               base_rent=price, price_basis="base" if price != "" else "",
                               availability="price as printed on the floor-plans page" if price != "" else "page lists the plan with no price",
                               price_status="listed" if price != "" else "not_publicly_listed"))
        if out:
            break
    if len(out) > 60:            # a search/results page listing many buildings, not this building's plans
        return []
    return out


JUNK_NAME = re.compile(r"^\(img|^img\b|floor ?plan|view |coming soon|available|call for|button|^home$|-->|^\W*$|summary|"
                       r"show unavailable|pricing|ready for|^bed ?/ ?bath$|^\*", re.I)
HX.EXTRACTORS["text_plan_list"] = text_plan_list


def text_plan_live(url, params):
    """text_plan_list on the LIVE page: fetch params.urls (or url) with the pipeline's HTTP client and read printed plan
    lines. Production-safe replacement for text_plan_list, which reads saved HTML and is refused in refresh runs.
    Added 2026-11-25: 19 A&M sites gave the same rows live as from their saved copies."""
    pages = (HX.fetch(u) for u in (params.get("urls") or [url]) if u)
    return _text_plan_rows(pages)


HX.EXTRACTORS["text_plan_live"] = text_plan_live


def lv_fp_ajax(url, params):
    """Landmark 'lv-master-template' WordPress sites (The Heights at College Station, 2026-11-25): the floor-plans page
    is an empty shell; floorplan.js POSTs action=fp_submit_search to /wp-admin/admin-ajax.php (no nonce) and gets the
    cards back as HTML. Each .floorplan-listing__card has the name (h3), 'N BR | N BA', 'N SF', 'Starting at $X'
    and the plan image. Plain HTTP, no browser."""
    import urllib.request, urllib.parse
    from lxml import html as LH
    u = urllib.parse.urlparse(url)
    endpoint = f"{u.scheme}://{u.netloc}/wp-admin/admin-ajax.php"
    body = urllib.parse.urlencode({"action": "fp_submit_search", "sort": "", "order": ""}).encode()
    req = urllib.request.Request(endpoint, data=body, headers={
        "User-Agent": HX.UA, "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Referer": url})
    with urllib.request.urlopen(req, timeout=30) as r:
        h = r.read().decode("utf-8", errors="replace")
    if "floorplan-listing__card" not in h:
        return []
    doc = LH.fromstring(h)
    out = []
    for card in doc.xpath('//div[contains(@class,"floorplan-listing__card")]'):
        name = " ".join(" ".join(card.xpath('.//h3[contains(@class,"floorplan-listing__name")]//text()')).split())
        det = " ".join(" ".join(card.xpath('.//div[contains(@class,"floorplan-listing__details")]//text()')).split())
        if not name:
            continue
        bb = re.search(r"(\d+|studio)\s*BR\s*\|?\s*([\d.]+)\s*BA", det, re.I)
        sf = re.search(r"([\d,]+)\s*SF", det)
        pm = re.search(r"\$\s?([\d,]+)", det)
        price = HX._num(pm.group(1)) if pm else ""
        sold = card.get("data-sold") == "1" or re.search(r"sold out", det, re.I)
        img = (card.xpath('.//div[contains(@class,"floorplan-listing__image")]//img/@src') or [""])[0]
        beds = (bb.group(1) if bb else "")
        out.append(HX._row(unit_or_floorplan_label=name, beds="0" if beds.lower() == "studio" else beds,
                           baths=bb.group(2) if bb else "", sqft=sf.group(1).replace(",", "") if sf else "",
                           base_rent=price, price_basis="base" if price != "" else "",
                           availability="sold out" if sold else ("starting at" if price != "" else ""),
                           layout_image_url=img,
                           price_status="listed" if price != "" else "not_publicly_listed"))
    return out


HX.EXTRACTORS["lv_fp_ajax"] = lv_fp_ajax


def leaseleads_embed(url, params):
    """LeaseLeads iframe (embed.leaseleads.co/<property-uuid>/floor-plans), e.g. The Landing College Station 2026-11-25.
    The iframe answers 403 without the property site as Referer and 200 with it. Its HTML carries the whole plan list
    as HTML-escaped JSON ("floorPlans":[{name, bedrooms, bathrooms, price_min, price_max, size, status, images}]).
    params.embed_url, or the iframe src found on the page at url. Plain HTTP, no browser."""
    import html as H, urllib.request
    emb = params.get("embed_url")
    if not emb:
        page = HX.fetch(url)
        m = re.search(r"embed\.leaseleads\.co/([0-9a-f-]{36})/floor-plans", page) or \
            re.search(r"LeaseLeadsEmbed\(\s*['\"]([0-9a-f-]{36})['\"]", page)
        if not m:
            return []
        emb = f"https://embed.leaseleads.co/{m.group(1)}/floor-plans"
    req = urllib.request.Request(emb, headers={"User-Agent": HX.UA, "Referer": url, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30) as r:
        h = H.unescape(r.read().decode("utf-8", errors="replace"))
    i = h.find('"floorPlans":[')
    if i < 0:
        return []
    plans, _ = json.JSONDecoder().raw_decode(h[i + len('"floorPlans":'):])
    out = []
    for f in plans:
        lo, hi = f.get("price_min"), f.get("price_max")
        lo_f = f.get("price_min_with_fees")
        sq = re.search(r"[\d,]+", str(f.get("size") or f.get("size_min") or ""))
        img = next((x.get("url") for x in f.get("images") or [] if isinstance(x, dict) and x.get("url")), "")
        out.append(HX._row(unit_or_floorplan_label=(f.get("name") or "").strip(),
                           beds=str(f.get("bedrooms") if f.get("bedrooms") is not None else ""),
                           baths=str(f.get("bathrooms") if f.get("bathrooms") is not None else ""),
                           sqft=sq.group(0).replace(",", "") if sq else "",
                           base_rent=lo if lo else "", total_price_with_mandatory_fees=lo_f if lo_f else "",
                           price_basis="total" if lo_f else ("base" if lo else ""),
                           availability=" — ".join(x for x in [f.get("status") or "",
                                                               f"up to ${hi}" if hi and hi != lo else ""] if x),
                           layout_image_url=img,
                           price_status="listed" if lo or lo_f else "not_publicly_listed"))
    return out


HX.EXTRACTORS["leaseleads_embed"] = leaseleads_embed


def inventory_models(url, params):
    """Sites whose /models page embeds an "$inventory" store (Limestone Terrace, Razz; ResMan leasing behind it).
    The page HTML holds "models":[{id, label, beds, baths, sqft{min,max}, rent{min,max}, images[uploadcare]}]; the
    visible cards are drawn from it by JS, so text parsing finds nothing. Plain HTTP, no browser. 2026-11-25."""
    h = HX.fetch(url)
    i = h.find('"models":[{')
    if i < 0:
        return []
    models, _ = json.JSONDecoder().raw_decode(h[i + len('"models":'):])
    out = []
    for m in models:
        if not isinstance(m, dict) or m.get("disabled") is True:
            continue
        rent, sq = m.get("rent") or {}, m.get("sqft") or {}
        lo, hi = rent.get("min"), rent.get("max")
        img = next((f"https://ucarecdn.com/{x['uuid']}/" for x in m.get("images") or []
                    if isinstance(x, dict) and x.get("uuid")), "")
        label = " ".join(x for x in [str(m.get("id") or ""), f"({m['label']})" if m.get("label") else ""] if x)
        out.append(HX._row(unit_or_floorplan_label=label, beds=str(m.get("beds", "")), baths=str(m.get("baths", "")),
                           sqft=str(sq.get("min") or ""), base_rent=lo if lo else "",
                           price_basis="base" if lo else "",
                           availability=f"up to ${hi}" if hi and hi != lo else "",
                           concessions_raw=m.get("special") or "",
                           layout_image_url=img,
                           price_status="listed" if lo else "not_publicly_listed"))
    return out


HX.EXTRACTORS["inventory_models"] = inventory_models


def swifty_fp_ajax(url, params):
    """beSwifty WordPress sites (West University Gardens, 2026-11-25; plugin path wp-content/plugins/beswifty-core):
    the floor-plans page loads its cards by POSTing action=swifty_floorplan_section_details_with_ajax,
    pageType=floorplans to /wp-admin/admin-ajax.php (no nonce). Each card is div.single-floorplan with
    listing-sqft / listing-price attributes, an 'N-bed' class and an h3.flp-title. 'Call for Pricing' -> unpriced.
    Plain HTTP, no browser."""
    import urllib.request, urllib.parse
    from lxml import html as LH
    u = urllib.parse.urlparse(url)
    body = urllib.parse.urlencode({"action": "swifty_floorplan_section_details_with_ajax",
                                   "pageType": "floorplans", "nocache": "1"}).encode()
    req = urllib.request.Request(f"{u.scheme}://{u.netloc}/wp-admin/admin-ajax.php", data=body, headers={
        "User-Agent": HX.UA, "X-Requested-With": "XMLHttpRequest", "Referer": url,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        h = r.read().decode("utf-8", errors="replace")
    if "single-floorplan" not in h:
        return []
    out, seen = [], set()
    for card in LH.fromstring(h).xpath('//div[contains(concat(" ", normalize-space(@class), " "), " single-floorplan ")]'):
        name = " ".join(" ".join(card.xpath('.//h3[contains(@class,"flp-title")]//text()')).split())
        if not name or (card.get("data_id"), name) in seen:
            continue
        seen.add((card.get("data_id"), name))
        cls = card.get("class") or ""
        bm = re.search(r"\b(\d+)-bed\b", cls)
        beds = bm.group(1) if bm else ("0" if re.search(r"studio", name, re.I) else "")
        ba = re.search(r"([\d.]+)\s*bath", name, re.I)
        price = HX._num((card.get("listing-price") or "").strip()) if (card.get("listing-price") or "").strip() else ""
        if price != "" and price < HX.MIN_PLAUSIBLE_RENT:
            price = ""
        sqft = re.sub(r"[^\d]", "", card.get("listing-sqft") or "")
        avail = " ".join(" ".join(card.xpath('.//*[contains(@class,"flp-availability")]//text()')).split())
        img = (card.xpath('.//img/@src') or [""])[0]
        out.append(HX._row(unit_or_floorplan_label=name, beds=beds, baths=ba.group(1) if ba else "", sqft=sqft,
                           base_rent=price, price_basis="base" if price != "" else "",
                           availability=avail, layout_image_url=img,
                           price_status="listed" if price != "" else "not_publicly_listed"))
    return out


HX.EXTRACTORS["swifty_fp_ajax"] = swifty_fp_ajax


CG_SYNERGY = "https://cgsynergyapi-prod.wonderfulisland-00679a9d.centralus.azurecontainerapps.io/api/community/"


def cg_synergy(url, params):
    """'CG Synergy' community API, used by one manager's student sites (Rev Northgate = revstudentliving.com,
    The Tradition = live12north.com). Found 2026-11-17 in Chrome: the floor-plans page calls
    GET <CG_SYNERGY>/<site domain> and draws its cards from floorPlans[] (name, bedroomCount, bathroomCount,
    squareFeet, marketRent, unitsAvailable, unitTypeNextLeaseDate, specials). Not behind Cloudflare, no key."""
    dom = params.get("domain") or urlparse(url).netloc.replace("www.", "")
    d = json.loads(HX.fetch(CG_SYNERGY + dom))
    rows = []
    for f in d.get("floorPlans") or []:
        if f.get("isDisabled"):
            continue
        rent = HX._num(f.get("marketRent"))
        ok = rent != "" and rent >= HX.MIN_PLAUSIBLE_RENT
        sp = "; ".join(str(s.get("description") or s.get("name") or s) for s in (f.get("specials") or []))
        # files[] = [{"fileType": "Floorplan", "source": <url>, ...}]. Until 11-24 this read "url"/"fileUrl" (keys the
        # API never sends), so every CG Synergy plan (12 North, Rev Northgate: 33 plans) came back without an image.
        files = [x for x in (f.get("files") or []) if isinstance(x, dict) and x.get("isActive", True)]
        files.sort(key=lambda x: (str(x.get("fileType", "")).lower() != "floorplan"))
        img = next((x.get("source") or x.get("url") or x.get("fileUrl") for x in files), "") or ""
        rows.append(HX._row(unit_or_floorplan_label=f.get("name", ""), beds=f.get("bedroomCount", ""),
                            baths=f.get("bathroomCount", ""), sqft=f.get("squareFeet") or "",
                            base_rent=rent if ok else "", price_basis="base" if ok else "",
                            concessions_raw=sp, availability=" — ".join(x for x in [
                                f"{f['unitsAvailable']} of {f.get('unitCount')} available" if f.get("unitsAvailable") is not None else "",
                                f"next lease {f['unitTypeNextLeaseDate']}" if f.get("unitTypeNextLeaseDate") else ""] if x),
                            layout_image_url=img, price_status="listed" if ok else "not_publicly_listed"))
    return rows


HX.EXTRACTORS["cg_synergy"] = cg_synergy


# Network fingerprint fallback (legacy scripts/fingerprint.js): XHR URL pattern -> adapter
NET_RULES = [
    (r"sightmap\.com/app/api/v1/[a-z0-9]+/sightmaps/\d+", "sightmap", lambda m, u: {"api_url": m.group(0)}),
    (r"doorway-api\.knockrentals\.com/v1/property/(\w+)", "knock_doorway", lambda m, u: {"property_id": m.group(1)}),
    (r"/api/lightning/floorplans/(\d+)", "acc_lightning", lambda m, u: {"list_id": int(m.group(1))}),
    (r"https?://[^/]+/wp-json/theme/entrata/v1/floor-plans", "wp_entrata_json", lambda m, u: {"api_url": m.group(0)}),
    (r"https?://[^/]+/wp-json/gmh-student/floorplans/categories", "wp_entrata_json", lambda m, u: {"api_url": m.group(0)}),
    (r"cmssitemanager/callback\.aspx", "realpage_cms_proxy", lambda m, u: {}),
    (r"inventory\.g5marketingcloud\.com/graphql", "g5_sniff", lambda m, u: {}),
    (r"cgsynergyapi[^/]*/api/community/([^/?#]+)", "cg_synergy", lambda m, u: {"domain": m.group(1)}),
    (r"realpage\.com/.*(floorplan|unit)", "realpage_sniff", lambda m, u: {}),
]


def net_fingerprint(url, out_dir):
    """Open the floor-plans page in a browser, record its JSON/XHR traffic (cached in raw/<slug>/fingerprint.json)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fp = out_dir / "fingerprint.json"
    if not fp.exists():
        npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        try:
            subprocess.run(["node", str(Path(__file__).parent / "fingerprint.js"), url, "fingerprint", str(out_dir)],
                           capture_output=True, text=True, timeout=120, env={**os.environ, "NODE_PATH": npm_root, "DOM_PROFILE": PROFILE})
        except subprocess.TimeoutExpired:
            return None
    return json.loads(fp.read_text()) if fp.exists() else None


def net_candidates(fp, page_url):
    out, seen = [], set()
    for n in (fp or {}).get("network", []):
        for rx, backend, prm in NET_RULES:
            m = re.search(rx, n["url"], re.I)
            if m and backend not in seen:
                seen.add(backend)
                out.append({"backend": backend, "url": page_url, "params": prm(m, n["url"]),
                            "why": f"network call {n['url'][:80]}"})
    return out


def _n(v):
    try:
        f = float(str(v).replace(",", "").replace("$", ""))
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def convert(r, cand, basis_fn, btype):
    """Legacy scraper row -> rebuild units row."""
    label = r.get("unit_or_floorplan_label") or ""
    avail = r.get("availability") or None
    pmin = _n(r.get("base_rent"))
    if pmin is None:
        # Total-only rows (Entrata "Total Monthly", no base) still count as priced.
        pmin = _n(r.get("total_price_with_mandatory_fees"))
    if pmin is not None and pmin < HX.MIN_PLAUSIBLE_RENT:
        pmin = None
    rng = re.search(r"advertised range \$([\d.]+)-\$([\d.]+)", avail or "")
    total = _n(r.get("total_price_with_mandatory_fees"))
    return {"name": label, "beds": _n(r.get("beds")), "baths": _n(r.get("baths")), "sqft": _n(r.get("sqft")) or (r.get("sqft") or None),
            "price_min": pmin, "price_max": _n(rng.group(2)) if rng else pmin,
            "price_label": (f"${pmin}" + (f" (${total} with mandatory fees)" if total and total != pmin else "")) if pmin else None,
            # whole-unit rental portals (AppFolio, Buildium) price the unit, whatever the building type says
            "rent_basis": basis_fn(label + " " + (avail or ""), btype, "unit" if cand["backend"] in UNIT_PRICED else None),
            "availability": avail, "concession": r.get("concessions_raw") or None,
            # legacy schema kept whole (FML_scraper CLAUDE_BUILD.md): base vs total-with-fees, parsed concessions, images
            "base_rent": pmin, "total_price_with_mandatory_fees": total, "price_basis": r.get("price_basis") or None,
            "concessions_type": r.get("concessions_type") or None, "concessions_value": _n(r.get("concessions_value")),
            "price_image_url": r.get("price_image_url") or None, "concessions_image_url": r.get("concessions_image_url") or None,
            "layout_image_url": r.get("layout_image_url") or None, "source_url": cand["url"],
            "source_type": "first_party_site", "adapter": cand["backend"]}


def extract(b, meta, html_by_kind, cfg, basis_fn, log=None):
    """Try every detected adapter. Returns (rows, chosen_backend, tried[]). Keeps the adapter with the most priced
    rows (ties: most rows). Browser parsers stop at the first one that returns rows (each costs ~30 s)."""
    cands = detect(b, meta, html_by_kind, cfg)
    tried, best, got_dom = [], None, False
    rd = cfg["dir"] / "raw" / meta.get("slug", "")
    resc = cfg["dir"] / "rescues" / f"{meta.get('slug', '')}.json"

    def run_list(cands):
        nonlocal best, got_dom
        for cand in cands:
            if is_ils(cand.get("url"), cfg):          # aggregators / campus directories are never a rent source
                tried.append({"backend": cand["backend"], "why": cand["why"], "status": "skipped_ils", "rows": 0, "priced": 0})
                continue
            is_dom = cand["backend"] in DOM_BACKENDS
            if is_dom and (got_dom or (best and best[0][0] > 0)):
                continue
            raw, status = _run(cand)
            raw = [r for r in raw if _keep_discovered_row(r)]
            rows = [convert(r, cand, basis_fn, b["building_type"]) for r in raw]
            tried.append({"backend": cand["backend"], "why": cand["why"], "status": status, "rows": len(rows),
                          "priced": sum(1 for r in rows if r["price_min"])})
            if rows:
                got_dom = got_dom or is_dom
                score = (sum(1 for r in rows if r["price_min"]), len(rows))
                if best is None or score > best[0]:
                    best = (score, rows, cand["backend"], cand)

    run_list(cands)
    fpu = meta.get("pages", {}).get("floorplans") or meta.get("pages", {}).get("home")
    if not best and fpu and meta.get("slug"):
        # no marker matched: watch the page's network traffic for a known feed (legacy fingerprint.js)
        run_list(net_candidates(net_fingerprint(fpu, rd), fpu))
    if meta.get("slug") and (not best or best[0][0] == 0):
        # last deterministic step: printed plan lines on the saved pages (replaces most LLM page reads)
        before = best
        files = [repo_rel(rd / f"{k}.html") for k in ("floorplans", "floorplans2", "fpdetail", "home")]
        run_list([{"backend": "text_plan_list", "url": fpu or "", "params": {"html_files": files}, "why": "plan lines in page text"}])
        if before and best and best[3]["backend"] == "text_plan_list" and best[0][0] <= before[0][0]:
            best = before
    if resc.exists():               # local file, free: let it compete on priced rows with whatever the live run got
        run_list([{"backend": "headed_rescue", "url": json.loads(resc.read_text()).get("source_url") or fpu or "",
                   "params": {"file": repo_rel(resc)}, "why": "hand-saved rescue file"}])
    if log:
        log(b["canonical_name"], tried)
    return (best[1], best[2], tried, best[3]) if best else ([], None, tried, None)


def sister_feed(b, basis_fn):
    """Second pass for buildings with no site of their own in the roster (seed = a directory page): a multi-building
    ACC feed found through a sister building may carry this building as one of its LocationFilters."""
    names = [b["canonical_name"]] + list(b.get("aliases") or [])
    for list_id in list(_acc_cache):
        # the building's name must carry the community's own name too ("The Block" + "Leon"). Matching on the
        # location word alone gave Texan Tower Condos another community's "Texan" plans.
        title = _toks(_acc_cache[list_id].get("Title")) - {"the", "at", "on", "of"}
        names_ok = [n for n in names if title and title <= _toks(n)]
        if not names_ok:
            continue
        loc, locs = acc_pick_location(list_id, names_ok)
        if loc and loc != "NO_MATCH":
            cand = {"backend": "acc_lightning", "url": f"https://www.americancampus.com/api/lightning/floorplans/{list_id}",
                    "params": {"list_id": list_id, "location_filter": loc}, "why": f"sister feed {loc}"}
            raw, status = _run(cand)
            rows = [convert(r, cand, basis_fn, b["building_type"]) for r in raw]
            if rows:
                return rows, {"cand": {k: cand[k] for k in ("backend", "url", "params")}, "backend": "acc_lightning", "why": cand["why"], "status": status, "rows": len(rows),
                              "priced": sum(1 for r in rows if r["price_min"])}
    return [], None


def feed_platforms(html_by_kind):
    low = "\n".join(html_by_kind.values()).lower()
    return [n for n, rx in FEED_MARKERS if re.search(rx, low)]


def coverage_flags(rows, adapter, html_by_kind, text_blob, tried=None):
    """Cheap undercount checks, written to listings.json and surfaced in the QC report."""
    flags = []
    fp = [p for p in feed_platforms(html_by_kind) if p != "appfolio" or "appfolio.com" in "\n".join(html_by_kind.values()).lower()]
    if fp and not adapter:
        flags.append("feed_platform_but_no_adapter_rows:" + ",".join(fp))
    if tried is not None and any(t.get("status") == "blocked_bot_wall" for t in tried) and adapter in (None, "llm_page_read"):
        # Cloudflare stops headless Chromium. Legacy fix: open the URL in a real (headed) browser and save the
        # floor-plan JSON, then ingest it (FML_scraper ingest_headed_rescues.py). Listed in the QC report.
        flags.append("blocked_bot_wall_needs_headed_browser:" + ",".join(t["backend"] for t in tried if t.get("status") == "blocked_bot_wall"))
    prices = {m for m in re.findall(r"\$\s?(\d{1,2},?\d{3}|\d{3})\b", text_blob or "")}
    if len(prices) > 2 * len(rows) + 4:
        flags.append(f"page_shows_{len(prices)}_distinct_prices_vs_{len(rows)}_rows")
    if adapter and rows and not any(r["price_min"] for r in rows) and prices:
        flags.append("adapter_rows_unpriced_but_page_shows_prices")
    return flags
