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
from common import campus, norm_name, name_sim
from webtext import fetch_html, links, to_text

KINDS = {
    "amenities": re.compile(r"amenit|features|community|life(style)?\b|perks", re.I),
    "floorplans": re.compile(r"floor[-_ ]?plans?|floorplans|availability|rates|pricing|apartments/?$|units|rooms|layouts", re.I),
    "gallery": re.compile(r"gallery|photos?|tour|media", re.I),
}
PLATFORMS = [
    ("entrata", r"entrata|prospectportal|medialibrarycfo"), ("rentcafe_yardi", r"rentcafe|yardi|ysi\.|cdngeneral"),
    ("realpage", r"realpage|onesite|rpcdn|rp-fp|leasestar"), ("sightmap", r"sightmap\.com|engrain"),
    ("appfolio", r"appfolio"), ("jonah", r"jd-fp|jonahdigital|jonah systems"), ("knock", r"knockrentals|doorway"),
    ("g5", r"g5-assets|g5search|g5cdn"), ("americancampus", r"americancampus\.com"), ("yugo", r"yugo\.com"),
    ("leaseleads", r"leaseleads"), ("rentmanager", r"rentmanager|rmresident"), ("buildium", r"buildium|managebuilding"),
    ("rentvine", r"rentvine"), ("showmojo", r"showmojo"), ("resman", r"resman|myresman"), ("funnel", r"funnelleasing|nestio"),
    ("propertybase", r"propertybase"), ("duda", r"dudaone|cdn-website\.com"), ("wix", r"wixstatic|wix\.com"),
    ("squarespace", r"squarespace"), ("webflow", r"webflow"), ("wordpress", r"wp-content|wp-json"),
]


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
    cands = [u for u in [seed] + (b.get("other_urls") or []) if u]
    named = [u for u in cands if about(u) and "offcampus" not in u and "rentcollegepads" not in u]
    if named and not (seed and about(seed)):
        seed = named[0]
        meta["seed"], meta["seed_rule"] = seed, "building_named_url"
    if seed:
        seed = seed.split("?")[0]
        cdir = cfg["dir"] / "cache" / "site" / slug
        home = fetch_html(seed, cdir)
        if home and not about(seed):
            # multi-building site: follow the link whose text is this building's name
            best = max(((name_sim(nn, norm_name(t, cw)), u) for u, t in links(home, seed) if t.strip()), default=(0, None))
            if best[0] >= 88:
                seed, meta["seed"], meta["seed_rule"] = best[1], best[1], "followed_name_link"
                home = fetch_html(seed, cdir)
        if home and len(to_text(home, seed)) > 300:
            (rd / "home.html").write_text(home)
            meta["pages"]["home"] = seed
            found = {}
            lk = links(home, seed)
            for kind, rx in KINDS.items():
                c = [(u, t) for u, t in lk if rx.search(t) or rx.search(urlparse(u).path)]
                c.sort(key=lambda x: (not rx.search(x[1]), len(x[0])))
                found[kind] = [u for u, _ in c[:2]]
            for kind in ("amenities", "floorplans"):
                if not found[kind]:
                    tail = "amenities/" if kind == "amenities" else "floor-plans/"
                    found[kind] = [urljoin(seed if seed.endswith("/") else seed + "/", tail)]
                    pp = parent_path(seed)
                    if pp:
                        found[kind].append(urljoin(pp, tail))
            plat = set(fingerprint(home))
            for kind, urls in found.items():
                n = 0
                for u in urls:
                    if u.rstrip("/") == seed.rstrip("/"):
                        continue
                    h = fetch_html(u, cdir)
                    if not h or len(to_text(h, u)) < 300:
                        continue
                    if kind == "amenities" and not re.search(r"amenit|fitness|pool|parking|laundry", to_text(h, u), re.I):
                        continue
                    n += 1
                    (rd / f"{kind}{'' if n == 1 else n}.html").write_text(h)
                    meta["pages"][f"{kind}{'' if n == 1 else n}"] = u
                    plat |= set(fingerprint(h))
            # in-unit appliance lists usually live one click deeper, on a floor-plan detail page
            fpp = rd / "floorplans.html"
            if fpp.exists():
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
