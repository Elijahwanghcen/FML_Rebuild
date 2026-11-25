"""Enrichment step 1: crawl each building's official site, archive raw pages, fingerprint the leasing platform.

Page discovery order (learned the hard way on UT):
  1. nav links whose text/href says amenities / floor plans / gallery
  2. sitemap.xml
  3. sibling-path rule: Entrata-style sites hang /amenities/ ONE segment above the seed's /student/ or
     /conventional/ path, and {seed}/amenities/ silently 301s to floor plans - so also try the parent path.
Raw HTML is saved to data/<campus>/raw/<slug>/<kind>.html so everything can be re-extracted without re-crawling.
"""
import json, re, sys, unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
from common import campus, norm_name, name_sim, is_ils
from webtext import fetch_html, links, to_text

KINDS = {
    "amenities": re.compile(r"amenit|features|community|life(style)?\b|perks", re.I),
    "floorplans": re.compile(r"floor[-_ ]?plans?|floorplans|availability|rates|pricing|apartments/?$|units|rooms|layouts", re.I),
    "gallery": re.compile(r"gallery|photos?|tour|media", re.I),
}
STRONG = {"floorplans": re.compile(r"floor[-_ ]?plans?|availab|rates|pricing", re.I),
          "amenities": re.compile(r"amenit|features", re.I)}
PLATFORMS = [
    ("entrata", r"entrata|prospectportal|medialibrarycfo"), ("rentcafe_yardi", r"rentcafe|yardi|ysi\.|cdngeneral"),
    ("realpage", r"realpage|onesite|rpcdn|rp-fp|leasestar"), ("sightmap", r"sightmap\.com|engrain"),
    ("appfolio", r"appfolio"), ("jonah", r"jd-fp|jonahdigital|jonah systems"), ("knock", r"knockrentals|doorway"),
    ("g5", r"g5-assets|g5search|g5cdn"), ("americancampus", r"americancampus\.com"), ("yugo", r"yugo\.com"),
    ("repli360", r"rrac_|rracfloorplan|repli360"), ("landmark_wp", r"themes/landmark-"),
    ("leaseleads", r"leaseleads"), ("rentmanager", r"rentmanager|rmresident"), ("buildium", r"buildium|managebuilding"),
    ("rentvine", r"rentvine"), ("showmojo", r"showmojo"), ("resman", r"resman|myresman"), ("funnel", r"funnelleasing|nestio"),
    ("propertybase", r"propertybase"), ("duda", r"dudaone|cdn-website\.com"), ("wix", r"wixstatic|wix\.com"),
    ("squarespace", r"squarespace"), ("webflow", r"webflow"), ("wordpress", r"wp-content|wp-json"),
]


FP_PATHS = ["floor-plans/", "floorplans/", "availability/", "rates-floorplans/", "floor-plans.aspx", "floorplans.aspx",
            "apartments/", "rates/", "pricing/", "units/", "listings/", "rentals/", "models/"]   # models/: Razz sites (Limestone Terrace)
LA_FEED = re.compile(r"rrac_|sightmap|knockdoorway|rentcafe|window\.ysi|entrata|realpage|jd-fp|appfolio|g5marketingcloud|product-tile", re.I)
PARKED = re.compile(r"domain (is )?for sale|forsale\.godaddy|buy this domain|sedoparking|hugedomains|domain does not exist|"
                    r"this domain (name )?(has expired|may be for sale)|access denied", re.I)


SOFT404 = re.compile(r"<title>[^<]*(404|not found|page (could not|cannot|can.t) be found|no longer available)[^<]*</title>|"
                     r"the page you (are|were) looking for (has moved|may have|could not|cannot|does not)", re.I)


def alive(h, u):
    # a 404 page on a template site carries >300 chars of nav text: judge by title / wording, not length alone
    return bool(h) and len(to_text(h, u)) > 300 and not PARKED.search(to_text(h, u)[:1500]) and not SOFT404.search(h[:20000])


def slugify(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fingerprint(html):
    h = (html or "")[:600000].lower()
    return [n for n, rx in PLATFORMS if re.search(rx, h)]


def parent_path(u):
    p = urlparse(u)
    segs = [s for s in p.path.split("/") if s]
    return f"{p.scheme}://{p.netloc}/" + "/".join(segs[:-1]) + ("/" if segs[:-1] else "") if segs else None


def crawl(cfg, b):
    slug = slugify(b["canonical_name"])
    rd = cfg["dir"] / "raw" / slug
    rd.mkdir(parents=True, exist_ok=True)
    meta_p = rd / "meta.json"
    if meta_p.exists():
        return json.loads(meta_p.read_text())
    seed = b.get("website")
    meta = {"slug": slug, "seed": seed, "pages": {}, "platforms": [], "status": "no_website"}
    cw = set(cfg.get("city_words", []))
    nn = norm_name(b["canonical_name"], cw)
    toks = [t for t in nn.split() if len(t) > 2]
    def about(u):   # does this URL's path name the building?
        p = re.sub(r"[^a-z0-9]+", " ", urlparse(u).path.lower() + " " + urlparse(u).netloc.lower().replace("www.", ""))
        return bool(toks) and sum(t in p.replace(" ", "") for t in toks) >= max(1, len(toks) - 1)
    # Website resolution: Google's websiteUri for a condo is often the manager's or HOA's home page.
    # Prefer any known URL whose path names the building (PM community page, directory listing last).
    # aggregators / campus directories (RentCollegePads, CoStar, Zillow ...) are never a website seed
    cands = [u for u in [seed] + (b.get("other_urls") or []) if u and not is_ils(u, cfg)]
    if seed and is_ils(seed, cfg):
        seed = cands[0] if cands else None
        meta["seed"] = seed
    named = [u for u in cands if about(u)]
    if named and not (seed and about(seed)) and not b.get("website_locked"):
        seed = named[0]
        meta["seed"], meta["seed_rule"] = seed, "building_named_url"
    if seed and not b.get("website_locked"):
        # A locked pin may carry a lease-term query (?_lease_term=fall). Do not strip it.
        seed = seed.split("?")[0]
        cdir = cfg["dir"] / "cache" / "site" / slug
        home = fetch_html(seed, cdir)
        if not alive(home, seed) and not b.get("website_locked"):
            # the chosen URL is dead, parked or blocked: try every other known URL before giving up (a rebranded
            # building keeps its old dead domain in the roster next to the live one). Directory pages go last.
            rest = [u.split("?")[0] for u in cands if u.split("?")[0] != seed]
            for u in rest:
                h = fetch_html(u, cdir)
                if alive(h, u):
                    meta["seed_dead"], seed, home = seed, u, h
                    meta["seed"], meta["seed_rule"] = u, "fallback_live_url"
                    break
        if home and not about(seed) and not b.get("website_locked"):
            # multi-building site: follow the link whose text is this building's name
            best = max(((name_sim(nn, norm_name(t, cw)), u) for u, t in links(home, seed) if t.strip()), default=(0, None))
            if best[0] >= 88:
                seed, meta["seed"], meta["seed_rule"] = best[1], best[1], "followed_name_link"
                home = fetch_html(seed, cdir)
        if home and len(to_text(home, seed)) > 300:
            (rd / "home.html").write_text(home)
            meta["pages"]["home"] = seed
            found, strong_found = {}, {}
            lk = links(home, seed)
            for kind, rx in KINDS.items():
                c = [(u, t) for u, t in lk if rx.search(t) or rx.search(urlparse(u).path)]
                # a URL path that literally says floor-plans / amenities beats a loose text match ("Contact", "Rooms"
                # on a global nav) - loose matches sent Villas on Nueces to /contact/ and Yugo to another country
                strong = STRONG.get(kind, rx)
                # strong = the link's path OR its exact text says floor plans ("Floor Plans" -> /bryan/camber-villas/student/
                # on Entrata). Text alone counts only when it is the whole label, not a word in a sentence.
                label = re.compile(r"^\s*(floor ?plans?|rates( ?& ?floor ?plans)?|availability|amenities|features)\s*$", re.I)
                isstrong = lambda x: bool(strong.search(urlparse(x[0]).path) or label.match(x[1] or ""))
                c.sort(key=lambda x: (not isstrong(x), not rx.search(x[1]), len(x[0])))
                found[kind] = [u for u, _ in c[:2]]
                strong_found[kind] = any(isstrong(x) for x in c[:2])
            for kind in ("amenities", "floorplans"):
                tails = ["amenities/"] if kind == "amenities" else FP_PATHS
                if not found[kind] or (kind == "floorplans" and not strong_found.get(kind)):
                    # no link whose path says floor plans: probe the usual paths on the seed and on the site root
                    # (keeps any loose nav match as a last resort)
                    root = f"{urlparse(seed).scheme}://{urlparse(seed).netloc}/"
                    probes = [urljoin(seed if seed.endswith("/") else seed + "/", t) for t in tails]
                    probes += [urljoin(root, t) for t in tails]
                    pp = parent_path(seed)
                    if pp:
                        probes.append(urljoin(pp, tails[0]))
                    found[kind] = list(dict.fromkeys(probes)) + found[kind]
            sp = urlparse(seed).path.rsplit("/", 1)[0] + "/"
            if sp.count("/") >= 4 and not b.get("website_locked"):
                sp = sp.rstrip("/").rsplit("/", 1)[0] + "/"   # unverified seed: allow one level up (Entrata siblings)
            if sp.count("/") >= 3:
                # seed is one building's page on a multi-property site (midtown-foxmeadows.com/campus/midtown-townhomes/):
                # links to a sister building's pages (/campus/fox-meadows/) are not this building's floor plans
                for kind in found:
                    found[kind] = [u for u in found[kind] if urlparse(u).path.startswith(sp)]
            if b.get("floorplans_url"):
                found["floorplans"] = [b["floorplans_url"]] + found["floorplans"]
            plat = set(fingerprint(home))
            for kind, urls in found.items():
                n = 0
                for u in urls:
                    if u.rstrip("/") == seed.rstrip("/"):
                        continue
                    if n >= 2:
                        break
                    h = fetch_html(u, cdir)
                    if not alive(h, u):          # empty, parked, blocked or a soft-404 (a 404 template still has 300+ chars of nav)
                        continue
                    if kind == "floorplans" and u == b.get("floorplans_url"):
                        hr = fetch_html(u, cdir, render="always")       # hand-verified: trust it, keep the rendered DOM
                        h = hr if hr and len(to_text(hr, u)) > len(to_text(h, u)) else h
                    elif kind == "floorplans":
                        t = to_text(h, u)
                        if h == home or not re.search(r"\bbed|\bbath|studio|sq\.? ?ft|\$\s?\d{3}", t, re.I):
                            continue        # a 200 that is the home page again, or a page with no plan words
                        if not re.search(r"\$\s?\d{3}", t) and LA_FEED.search(h):
                            # plans come from a widget: keep the rendered DOM so the text read has something to read
                            hr = fetch_html(u, cdir, render="always")
                            if hr and len(to_text(hr, u)) > len(t):
                                h = hr
                    if kind == "amenities" and not re.search(r"amenit|fitness|pool|parking|laundry", to_text(h, u), re.I):
                        continue
                    n += 1
                    (rd / f"{kind}{'' if n == 1 else n}.html").write_text(h)
                    meta["pages"][f"{kind}{'' if n == 1 else n}"] = u
                    plat |= set(fingerprint(h))
            # in-unit appliance lists usually live one click deeper, on a floor-plan detail page
            fpp = rd / "floorplans.html"
            if fpp.exists() and "floorplans" in meta["pages"]:
                fu = meta["pages"]["floorplans"]
                det = [u for u, t in links(fpp.read_text(errors="replace"), fu)
                       if re.search(r"floor[-_]?plans?/[^/?]+/?$|floorplan[s]?/.+|/plans?/.+|unit[-_]?detail|/details?/", urlparse(u).path, re.I)
                       and u.rstrip("/") != fu.rstrip("/")]
                for u in det[:1]:
                    h = fetch_html(u, cdir)
                    if h and len(to_text(h, u)) > 300:
                        (rd / "fpdetail.html").write_text(h)
                        meta["pages"]["fpdetail"] = u
            meta["platforms"] = sorted(plat)
            meta["status"] = "ok"
    # Condos / small buildings: no single official site. Read every other page that names the building
    # (realtor community pages, HOA page) and union what they say.
    n = 0
    for u in [x for x in named if x.split("?")[0].rstrip("/") != (seed or "").rstrip("/")][:3]:
        h = fetch_html(u.split("?")[0], cfg["dir"] / "cache" / "site" / slug)
        if h and len(to_text(h, u)) > 300:
            n += 1
            (rd / f"alt{n}.html").write_text(h)
            meta["pages"][f"alt{n}"] = u
            meta["platforms"] = sorted(set(meta["platforms"]) | set(fingerprint(h)))
            if meta["status"] != "ok":
                meta["status"] = "ok"
        else:
            meta["status"] = "blocked_or_empty"
    meta_p.write_text(json.dumps(meta, indent=1))
    return meta


def main(slug, roster_file="roster_final.json", only=None):
    cfg = campus(slug)
    roster = json.load(open(cfg["dir"] / roster_file))
    if only:
        roster = [b for b in roster if b["canonical_name"] in only]
    with ThreadPoolExecutor(5) as ex:
        metas = list(ex.map(lambda b: crawl(cfg, b), roster))
    from collections import Counter
    print(Counter(m["status"] for m in metas))
    print(Counter(p for m in metas for p in m["platforms"]).most_common(12))
    print("with amenities page:", sum(1 for m in metas if "amenities" in m["pages"]),
          "with floorplans page:", sum(1 for m in metas if "floorplans" in m["pages"]))


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:3]))
