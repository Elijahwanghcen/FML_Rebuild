"""Find a building's own website by probing likely domains, then verifying the page is that building.

Why: a web search for "<name> <city>" often returns only listing sites, and a search summary that says
"no official site found" is not evidence. Many properties sit on an obvious domain that a plain request
loads (see docs/PLAYBOOK_2_ENRICHMENT.md section 2).

  python3 resolve_website.py "<name>" "<city>" "<state>" ["<street address>"] ["<other city>" ...]
  python3 resolve_website.py --roster <roster.json>     # rows: name, city, state, address (optional)

A hit is returned only when the page names the city (or a neighbouring city passed in) AND either the
street address or the building's name. Parked, for-sale and unrelated pages are rejected.
"""
import concurrent.futures as cf
import html
import json
import re
import subprocess
import sys

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TYPE_WORDS = r"apartment homes|apartments?|apts?|condominiums?|condos?|townhomes?|townhouses?|lofts?|villas?|student living|student housing|residences?"
PARKED = re.compile(r"domain (is )?for sale|buy this domain|parked (free|domain)|sedoparking|hugedomains|dan\.com|afternic|"
                    r"this domain (name )?(has expired|may be for sale)|godaddy\.com/domainsearch", re.I)
# Hosted resident/leasing portals: a property (or its one-building owner) gets its own subdomain.
# Only portals that answer "unknown account" for a wrong name are probed. Hosts that answer every name the same way
# (a bot challenge on any subdomain) give no signal and are left out.
PORTALS = ["{b}.managebuilding.com"]
PATTERNS = ["{b}.com", "{b}apartments.com", "{b}apts.com", "{b}apt.com", "live{b}.com", "liveat{b}.com", "{b}living.com",
            "the{b}.com", "{b}{c}.com", "{b}at{c}.com", "liveat{b}{c}.com", "{b}condos.com", "{b}condos.net", "{b}townhomes.com",
            "{b}-apartments.com", "{b}.net", "{b}apartments.net", "my{b}.com", "{b}.live"]


def slugs(name):
    n = re.sub(r"[^a-z0-9 ]", "", name.lower().replace("&", " and "))
    n = re.sub(r"\s+", " ", n).strip()
    no_the = re.sub(r"^the ", "", n)
    core = re.sub(r"\b(" + TYPE_WORDS + r")\b", "", no_the)
    core = re.sub(r"\s+", " ", core).strip()
    out = []
    for s in (core, no_the, n):
        s = s.replace(" ", "")
        if len(s) >= 4 and s not in out:
            out.append(s)
    return out, [w for w in core.split() if len(w) > 2]


def candidates(name, city):
    c = re.sub(r"[^a-z]", "", city.lower())
    bases, _ = slugs(name)
    seen, out = set(), []
    for b in bases:
        for p in PATTERNS + PORTALS:
            d = p.format(b=b, c=c)
            if d not in seen:
                seen.add(d)
                out.append(d)
    return out


def fetch(domain):
    for scheme_host in ("https://www." + domain, "https://" + domain):
        if domain.count(".") > 1 and scheme_host.startswith("https://www."):
            continue  # portal subdomains have no www
        r = subprocess.run(["curl", "-sL", "-A", UA, "--compressed", "--max-time", "12", "-w", "\n%{http_code} %{url_effective}",
                            scheme_host + "/"], capture_output=True)
        body, _, tail = r.stdout.decode("utf-8", "ignore").rpartition("\n")
        code, _, eff = tail.partition(" ")
        if code in ("200", "403") and not re.search(r"Error\.aspx|InvalidAccount|/404|hugedomains\.|dan\.com|sedo\.com|afternic\.|godaddy\.com", eff):
            return code, eff, body
    return None, None, ""


def addr_key(address):
    m = re.match(r"\s*(\d+)\s+(?:[NSEW]\.?\s+)?([A-Za-z0-9]+)", address or "")
    return (m.group(1), m.group(2).lower()) if m else None


def verify(name, cities, address, code, eff, body):
    """Return (score, reason). score >= 2 is a confirmed hit; 1 is a lead to check by hand."""
    if code == "403":
        return 1, "blocked (bot challenge): open in a real browser to confirm"
    text = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", body, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    low = re.sub(r"\s+", " ", (text + " " + " ".join(re.findall(r'content="([^"]{0,300})"', body))).lower())
    if len(low) < 200 or PARKED.search(low):
        return 0, "parked or empty"
    city_ok = any(c.lower() in low for c in cities)
    _, words = slugs(name)
    name_ok = bool(words) and all(w in low for w in words)
    ak = addr_key(address)
    addr_ok = bool(ak) and re.search(r"\b" + ak[0] + r"\b[^<]{0,25}\b" + re.escape(ak[1]), low) is not None
    housing = re.search(r"apartment|floor ?plan|leasing|bedroom|resident|townhome|condo", low) is not None
    if addr_ok and (city_ok or name_ok):
        return 3, "street address on page"
    if city_ok and name_ok and housing:
        return 2, "name + city on a housing page"
    if name_ok and housing:
        return 1, "name on a housing page, city not shown: could be a same-name property elsewhere"
    return 0, "unrelated page"


def resolve(name, city, state, address=None, other_cities=()):
    cities = [city, *other_cities]
    # The address's own city beats the campus city: a property across the city line is common.
    m = re.search(r",\s*([A-Za-z .]+),\s*[A-Z]{2}\b", address or "")
    if m and m.group(1).strip() not in cities:
        cities.insert(0, m.group(1).strip())
    hits = []
    doms = []
    for c in cities[:2]:
        for d in candidates(name, c):
            if d not in doms:
                doms.append(d)
    with cf.ThreadPoolExecutor(16) as ex:
        for d, (code, eff, body) in zip(doms, ex.map(fetch, doms)):
            if not code:
                continue
            score, why = verify(name, cities, address, code, eff, body)
            if score:
                hits.append({"url": eff, "score": score, "why": why, "probe": d})
    hits.sort(key=lambda h: -h["score"])
    seen, out = set(), []
    for h in hits:
        k = re.sub(r"^https?://(www\.)?", "", h["url"]).rstrip("/")
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--roster":
        for row in json.load(open(sys.argv[2])):
            hits = resolve(row["name"], row["city"], row.get("state", ""), row.get("address"), row.get("other_cities", ()))
            print(json.dumps({"name": row["name"], "hits": hits[:3]}), flush=True)
    elif len(sys.argv) >= 4:
        for h in resolve(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None, sys.argv[5:]):
            print(h["score"], h["url"], "|", h["why"])
    else:
        print(__doc__)
