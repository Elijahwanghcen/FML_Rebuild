"""Source 3: local realtor / property-manager / multi-building operator sites.

This is how condos surface: they rarely have their own Google listing or website, but a
local PM's "communities" / "properties" page lists them by name + address.
Rule for picking sites (campus-agnostic):
  a) any Places/Overture candidate typed real_estate_agency / property_management near campus
  b) any website domain shared by >=2 residential candidates (portfolio operators)
Then: homepage + up to 6 portfolio-looking pages -> LLM extracts {name, address, type, url}.
"""
import json, re, sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from common import campus
from webtext import fetch_html, to_text, links
from llm import ask_json

DENY = re.compile(r"facebook|instagram|vrbo|airbnb|bluepillow|kasa\.com|booking|zillow|apartments\.com|yelp|"
                  r"trec\.texas|wa\.me|linktr|google|safelease|marriott|hilton|hyatt|sonder|vacasa|blueground|"
                  r"\.edu$|\.gov$|lincolnfinancial|hotel|kw\.com|kellerwilliams|compass\.com|remax|coldwell|sothebys|exprealty|"
                  r"century21|redfin|realtor\.com|bhhs|jpar|homes\.com|linkedin|twitter|youtube|yellowpages|mapquest|"
                  r"loopnet|cbre|jll\.|colliers|commercial|mortgage|title|insurance|law|architect|construction", re.I)
KEY = re.compile(r"communit|propert|portfolio|listing|apartment|condo|rental|availab|for[-_ ]?rent|lease|"
                 r"student|locations|our[-_ ]homes|buildings|houses|vacanc|search", re.I)


def dom(u):
    try:
        return urlparse(u if "://" in u else "http://" + u).netloc.lower().replace("www.", "")
    except Exception:
        return None


def pick_sites(cfg):
    P = json.load(open(cfg["dir"] / "cand_places.json"))
    O = json.load(open(cfg["dir"] / "cand_overture.json"))
    ag = cfg["dir"] / "pm_overture_agents.json"
    if ag.exists():
        O = O + [a for a in json.load(open(ag)) if a["dist_m"] <= cfg.get("pm_radius_m", 1500)]
    lim = cfg["core_radius_m"] * 1.8
    sites, dc = {}, Counter()
    for x in P + O:
        w = x.get("website")
        if not w:
            continue
        d = dom(w)
        dc[d] += 1
        typ = x.get("primary_type") or x.get("category") or ""
        if x["dist_m"] <= lim and (typ in ("real_estate_agency", "property_management", "apartment_agent")
                                    or re.search(r"realty|propert|management|leasing|locator", x["name"] or "", re.I)):
            sites.setdefault(d, f"https://{d}/")
    for d, n in dc.items():
        if n >= 2:
            sites.setdefault(d, f"https://{d}/")
    for d in cfg.get("extra_pm_sites", []):
        sites.setdefault(dom(d), d if "://" in d else f"https://{d}/")
    return {d: u for d, u in sites.items() if d and not DENY.search(d)}


def crawl_site(cfg, d, home):
    cdir = cfg["dir"] / "cache" / "pm" / d
    h = fetch_html(home, cdir)
    if not h:
        return d, [], "fetch_failed"
    pages = [(home, h)]
    seen = {home.rstrip("/")}
    cand = []
    for u, t in links(h, home):
        if u.rstrip("/") in seen or re.search(r"\.(pdf|jpg|png|zip)$", u, re.I):
            continue
        score = len(KEY.findall(u + " " + t))
        if score:
            cand.append((score, len(u), u))
            seen.add(u.rstrip("/"))
    for _, _, u in sorted(cand, key=lambda x: (-x[0], x[1]))[:4]:
        hh = fetch_html(u, cdir)
        if hh:
            pages.append((u, hh))
    found = []
    for u, hh in pages:
        txt = to_text(hh, u, limit=45000)
        if len(txt) < 300:
            continue
        res = ask_json(
            f"This is text from a page on {d}, a real-estate / property-management / apartment site near "
            f"{cfg['name']} in {cfg['city']}, {cfg['state']}.\nList every distinct multi-unit residential BUILDING or "
            f"COMMUNITY (apartment complex, condominium building, co-op, private dorm, student housing) located in the "
            f"{cfg['city']} area that the page names. Skip single-family houses, duplexes, commercial space, blog posts, "
            f"neighbourhood names and buildings in other cities. Use the building's own name (e.g. 'Croix Condominiums'), "
            f"not a unit title. If a listing is 'ADDRESS Unit 203' with no building name, use the street address as name.\n"
            f"Return a JSON array of objects: name, address (street address if shown else null), "
            f"type (apartment|condo|co_op|dorm|student_housing|unknown), url (the building's own page link if shown else null).\n"
            f"Return [] if none.\n\nPAGE URL: {u}\n\n{txt}")
        for r in res or []:
            if isinstance(r, dict) and r.get("name"):
                r["page"] = u
                found.append(r)
    return d, found, "ok"


def main(slug):
    cfg = campus(slug)
    sites = pick_sites(cfg)
    print("sites:", len(sites))
    out, status = [], {}
    with ThreadPoolExecutor(6) as ex:
        for d, found, st in ex.map(lambda kv: crawl_site(cfg, *kv), sites.items()):
            status[d] = (st, len(found))
            uniq = {}
            for r in found:
                uniq.setdefault((r["name"].lower(), (r.get("address") or "").lower()), r)
            for r in uniq.values():
                out.append({"name": r["name"], "address": r.get("address"), "type": r.get("type"),
                            "url": r.get("url") or r["page"], "sources": [f"pm_site:{d}"]})
    (cfg["dir"] / "cand_pm_raw.json").write_text(json.dumps(out, indent=1))
    (cfg["dir"] / "pm_site_status.json").write_text(json.dumps(status, indent=1))
    print("pm candidates:", len(out), "sites with results:", sum(1 for s in status.values() if s[1]))


if __name__ == "__main__":
    main(sys.argv[1])
