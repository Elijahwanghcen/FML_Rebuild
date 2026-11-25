"""Enrichment step 2: amenities, 3-state, with evidence.

Two passes over the archived pages, unioned:
  A. deterministic: list-shaped strings (<li>, captions, alt text, card headings) -> alias_map.json
     (1,954 hand-vetted strings from the UT build) -> taxonomy term.            evidence_type = stated
  B. LLM read of the page prose + photo captions/alt text against the fixed taxonomy. It must return a
     verbatim quote for every term; quotes that are not actually on the page are thrown away.
     evidence_type = stated | implied_text | seen_photo(caption/alt)
Status: present | select (select units) | optional (extra fee / on request). Anything not found stays UNKNOWN -
a site never says "we have no sauna", so absence is only ever recorded from an explicit yes/no checklist.
"""
import html as H, json, re, sys, unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from common import campus
from webtext import to_text
from llm import ask_json

A = Path(__file__).resolve().parent / "assets"
TAX = json.loads((A / "taxonomy.json").read_text())
TERMS = [t for v in TAX.values() for t in v]
ALIAS = json.loads((A / "alias_map.json").read_text())
LAYER = {k: v["layer"] for k, v in json.loads((A / "scoring_weights.json").read_text())["weights"].items()}


def norm_string(s):
    s = unicodedata.normalize("NFKD", s).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def list_items(h):
    h = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", h)
    out = []
    for rx in (r"(?is)<li\b[^>]*>(.*?)</li>", r"(?is)<figcaption\b[^>]*>(.*?)</figcaption>",
               r'(?is)<span[^>]*class="[^"]*caption[^"]*"[^>]*>(.*?)</span>', r"(?is)<h[2-5]\b[^>]*>(.*?)</h[2-5]>",
               r'(?is)<div[^>]*class="[^"]*amenit[^"]*"[^>]*>(.*?)</div>', r"(?is)<p\b[^>]*>(.*?)</p>"):
        for m in re.finditer(rx, h):
            t = H.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
            t = re.sub(r"\s+", " ", t).strip()
            if 3 <= len(t) <= 90:
                out.append(t)
    out += [H.unescape(a).strip() for a in re.findall(r'(?is)<img\b[^>]*alt=["\']([^"\']{4,90})["\']', h)]
    return list(dict.fromkeys(out))


def qualifier(s):
    s = s.lower()
    if re.search(r"select (units|apartments|homes|floor)|in select|\*", s):
        return "select"
    if re.search(r"available|optional|additional (fee|cost)|for a fee|upon request|for rent\b", s):
        return "optional"
    return "present"


def extract(cfg, b_slug, extra=None):
    rd = cfg["dir"] / "raw" / b_slug
    meta = json.loads((rd / "meta.json").read_text())
    out_p = rd / "amenities.json"
    if out_p.exists():
        return json.loads(out_p.read_text())
    found, texts = {}, []
    for kind, url in meta["pages"].items():
        if kind.startswith("gallery") and len(meta["pages"]) > 2:
            pass
        h = (rd / f"{kind}.html").read_text(errors="replace")
        for it in list_items(h):
            for term in ALIAS.get(norm_string(it), []):
                if term in TERMS and term not in found:
                    found[term] = {"status": qualifier(it), "evidence": it, "evidence_type": "stated",
                                   "source_url": url, "method": "alias_map"}
        texts.append((kind, url, to_text(h, url, keep_links=False, limit=18000)))
    # No directory feature checklist: aggregators / campus directories (RentCollegePads, CoStar ...) are never an amenity source.
    order = {"amenities": 0, "amenities2": 1, "home": 2, "fpdetail": 3, "floorplans": 4, "gallery": 5}
    texts.sort(key=lambda x: order.get(x[0], 5))
    r = []
    blob = "\n\n".join(f"=== PAGE {k} ({u}) ===\n{t}" for k, u, t in texts)[:50000]
    if len(blob) > 400:
        r = ask_json(
            "You are extracting apartment-building amenities for a housing database. Use ONLY this fixed vocabulary:\n"
            + json.dumps(TAX) + "\n\n"
            "Read the page text below (it includes photo captions and image alt text as '(img: ...)').\n"
            "Return a JSON array; one object per amenity the building has:\n"
            '  term (exactly from the vocabulary), status ("present" | "select" = select units only | "optional" = extra fee/on request),\n'
            '  evidence (a SHORT VERBATIM quote copied from the text, <= 140 chars),\n'
            '  evidence_type ("stated" = listed outright | "implied_text" = implied by marketing prose, e.g. "pet spa" -> Pet Spa/Grooming, '
            '"game day on the big screen" -> Jumbo Screen, a published pet fee -> Pets Allowed | "seen_photo" = only in an image caption/alt text).\n'
            "Rules: gym equipment lists roll up to Fitness Center; furniture lists roll up to Furnished Units; ignore nearby businesses, "
            "neighbourhood attractions, navigation and footer text; never invent a term; if unsure leave it out.\n\n" + blob,
            model="sonnet", timeout=400)
        low = re.sub(r"\s+", " ", blob.lower())
        for x in r or []:
            if not isinstance(x, dict) or x.get("term") not in TERMS or not x.get("evidence"):
                continue
            q = re.sub(r"\s+", " ", x["evidence"].lower()).strip(" .\"'")
            if q[:40] not in low:          # quote must really be on the page
                continue
            url = next((u for k, u, t in texts if q[:40] in re.sub(r"\s+", " ", t.lower())), None)
            if x["term"] not in found:
                found[x["term"]] = {"status": x.get("status") if x.get("status") in ("present", "select", "optional") else "present",
                                    "evidence": x["evidence"], "evidence_type": x.get("evidence_type") or "stated",
                                    "source_url": url, "method": "llm_read"}
    res = {"slug": b_slug, "amenities": found,
           "features": {L: sorted(t for t in found if LAYER.get(t) == L) for L in ("apartment", "community", "premium")},
           "n": len(found), "pages_read": list(meta["pages"])}
    if len(blob) > 400 and r is None:
        res["llm_failed"] = True      # usage limit / timeout: do not cache a lists-only result as final
        return res
    out_p.write_text(json.dumps(res, indent=1))
    return res


def main(slug, roster_file="roster_final.json"):
    from common import norm_name, name_sim
    from enrich_site import slugify
    cfg = campus(slug)
    cw = set(cfg.get("city_words", []))
    jobs = []
    for b in json.load(open(cfg["dir"] / roster_file)):
        s = slugify(b["canonical_name"])
        mp = cfg["dir"] / "raw" / s / "meta.json"
        if not mp.exists():
            continue
        if json.loads(mp.read_text())["status"] == "ok":
            jobs.append((s, None))
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda j: extract(cfg, *j), jobs))
    print("buildings:", len(res), "median amenities:", sorted(r["n"] for r in res)[len(res) // 2] if res else 0)


if __name__ == "__main__":
    main(*sys.argv[1:3])
