"""Shared helpers: env, cached HTTP, geo math, name normalisation, Places call log."""
import csv, hashlib, json, math, os, re, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def campus(slug):
    cfg = json.loads((ROOT / "campuses" / f"{slug}.json").read_text())
    cfg["slug"] = slug
    d = DATA / slug
    (d / "cache").mkdir(parents=True, exist_ok=True)
    cfg["dir"] = d
    return cfg


def haversine_m(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = p2 - p1, math.radians(d - b)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def offset(lat, lng, dn_m, de_m):
    return (lat + dn_m / 111320.0, lng + de_m / (111320.0 * math.cos(math.radians(lat))))


# Words that carry no identity. "house", "place", "square" DO carry identity
# (Cameron House vs Montgomery House), so they stay.
STRIP = {"apartments", "apartment", "apts", "apt", "condominiums", "condominium", "condos",
         "condo", "the", "at", "on", "of", "student", "living", "housing", "homes", "home",
         "residences", "residence", "luxury", "townhomes", "townhouses", "flats", "lofts",
         "and", "a", "by", "llc", "community", "communities", "off", "campus"}


def norm_name(s, city_words=()):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if t not in STRIP and t not in city_words]
    return " ".join(toks)


_SUF = {"street": "st", "avenue": "ave", "boulevard": "blvd", "drive": "dr", "road": "rd",
        "lane": "ln", "court": "ct", "place": "pl", "parkway": "pkwy", "highway": "hwy",
        "north": "n", "south": "s", "east": "e", "west": "w", "half": "1/2"}


_TYPES = {"st", "ave", "blvd", "dr", "rd", "ln", "ct", "pl", "pkwy", "hwy", "way", "trl", "cir", "ter", "loop", "row"}


def norm_addr(s):
    """First line of an address -> 'number street' key ('904 w 22 1/2 st')."""
    s = (s or "").lower().split(",")[0]
    s = re.sub(r"\b(apt|unit|ste|suite|#)\s*[\w-]+$", "", s)
    s = re.sub(r"[^a-z0-9/ ]+", " ", s)
    toks = [_SUF.get(t, t) for t in s.split()]
    toks = [re.sub(r"(\d+)(st|nd|rd|th)$", r"\1", t) for t in toks]
    # drop a trailing city/state/zip that was not comma-separated ("701 W 28th St Austin TX 78705")
    idx = [i for i, t in enumerate(toks) if t in _TYPES and i >= 2]
    if idx:
        toks = toks[:idx[-1] + 1]
    return " ".join(toks)


def street_number(s):
    m = re.match(r"\s*(\d+)", s or "")
    return m.group(1) if m else None


def http_get(url, cache_dir=None, timeout=30, headers=None, sleep=0.0, binary=False):
    key = hashlib.sha1(url.encode()).hexdigest()[:20]
    cp = Path(cache_dir) / key if cache_dir else None
    if cp and cp.exists():
        b = cp.read_bytes()
        return b if binary else b.decode("utf-8", "replace")
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip
            b = gzip.decompress(b)
    if cp:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_bytes(b)
    if sleep:
        time.sleep(sleep)
    return b if binary else b.decode("utf-8", "replace")


# ---- Google Places (New). Every billable call is cached and logged. -------
PRICE = {"searchNearby": 0.035, "searchText": 0.035, "details": 0.02}


def places_post(cfg, endpoint, body, fieldmask):
    load_env()
    cdir = cfg["dir"] / "cache" / "places"
    cdir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((endpoint + json.dumps(body, sort_keys=True) + fieldmask).encode()).hexdigest()[:20]
    cp = cdir / f"{key}.json"
    if cp.exists():
        return json.loads(cp.read_text())
    req = urllib.request.Request(
        f"https://places.googleapis.com/v1/places:{endpoint}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "X-Goog-Api-Key": os.environ["GOOGLE_PLACES_API_KEY"],
                 "X-Goog-FieldMask": fieldmask})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"places {endpoint} {e.code}: {e.read().decode()[:400]}")
    cp.write_text(json.dumps(out))
    log = cfg["dir"] / "places_call_log.csv"
    new = not log.exists()
    with open(log, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "endpoint", "est_usd", "n_results", "note"])
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), endpoint, PRICE.get(endpoint, 0.035),
                    len(out.get("places", [])), json.dumps(body)[:120]])
    time.sleep(0.12)
    return out


def places_spend(cfg):
    log = cfg["dir"] / "places_call_log.csv"
    if not log.exists():
        return 0.0
    return sum(float(r["est_usd"]) for r in csv.DictReader(open(log)))


def name_sim(a, b):
    """Similarity of two *normalised* names, 0-100. token_set_ratio alone is unsafe: it scores 100 whenever one
    name's tokens are a subset of the other's ('salado' vs 'salado place' vs 'casa de salado' are 3 buildings),
    so the subset score only counts when the shorter name has >= 2 tokens."""
    from rapidfuzz import fuzz
    if not a or not b:
        return 0
    ta, tb = a.split(), b.split()
    s = max(fuzz.token_sort_ratio(a, b), fuzz.ratio(a.replace(" ", ""), b.replace(" ", "")))
    if min(len(ta), len(tb)) >= 2:
        s = max(s, fuzz.token_set_ratio(a, b))
    return s
