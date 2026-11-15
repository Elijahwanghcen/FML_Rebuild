"""PM / realtor pages often list a condo by name only. Open the building's own page on that site and take the
first street address on it that exists in the NAD address index (so a footer office address in another part of
town, or a phone number, cannot match by accident unless it is a real address near campus - office addresses are
excluded by counting: an address appearing on >3 different building pages of one site is the office)."""
import json, re, sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from common import campus, norm_addr
from webtext import fetch_html, to_text
import geo

ADDR = re.compile(r"\b(\d{2,5}(?: 1/2)? (?:[NSEW]\.? )?(?:[A-Z0-9][A-Za-z0-9.'-]*\s){1,4}?(?:St(?:reet)?|Ave(?:nue)?|Blvd|Boulevard|Dr(?:ive)?|"
                  r"R(?:oa)?d|Ln|Lane|Ct|Court|Pl(?:ace)?|Pkwy|Parkway|Way|Trl|Trail|Cir(?:cle)?|Speedway|Guadalupe|Nueces|Rio Grande|"
                  r"San Gabriel|San Antonio|Pearl|Leon|Salado|Duval|Lamar|Whitis|Red River)\b\.?)")


def main(slug):
    cfg = campus(slug)
    p = cfg["dir"] / "cand_pm_raw.json"
    rows = json.load(open(p))
    todo = [r for r in rows if not r.get("address") and r.get("url") and urlparse(r["url"]).path.strip("/")
            and not geo.geocode(cfg, r["name"])]
    by_url = defaultdict(list)
    for r in todo:
        by_url[r["url"]].append(r)
    urls = [u for u, v in by_url.items() if len(v) == 1][:400]     # a URL shared by many names is a list page

    def one(u):
        dom = urlparse(u).netloc.replace("www.", "")
        h = fetch_html(u, cfg["dir"] / "cache" / "pm" / dom, render="never")
        if not h:
            return u, []
        t = to_text(h, u, keep_links=False, limit=40000)
        return u, [a for a in dict.fromkeys(m.group(1) for m in ADDR.finditer(t)) if geo.geocode(cfg, a)]

    with ThreadPoolExecutor(8) as ex:
        res = dict(ex.map(one, urls))
    office = Counter()
    for u, al in res.items():
        for a in set(norm_addr(x) for x in al):
            office[(urlparse(u).netloc, a)] += 1
    n = 0
    for u, al in res.items():
        al = [a for a in al if office[(urlparse(u).netloc, norm_addr(a))] <= 3]
        if al:
            by_url[u][0]["address"], by_url[u][0]["address_from"] = al[0], "building_page"
            n += 1
    p.write_text(json.dumps(rows, indent=1))
    print(f"name-only candidates={len(todo)} pages fetched={len(urls)} addresses recovered={n}")


if __name__ == "__main__":
    main(sys.argv[1])
