"""HTTP extractors for backends with clean endpoints or static pages (no browser needed).

Each extractor takes (url, params) and returns a list of partial row dicts with keys:
unit_or_floorplan_label, beds, baths, sqft, base_rent, total_price_with_mandatory_fees,
price_basis, concessions_raw, concessions_type, concessions_value, availability, price_status
run.py fills in the property-level fields.

Extractors for shared sources (ACC The Block) accept the full fetched payload via a
module-level cache so the source is only hit once per run.
"""
import json
import re
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 apartment-research/1.0")

_FETCH_CACHE = {}

# specials below this are treated as data-entry noise, never as a price
MIN_PLAUSIBLE_RENT = 100


def fetch(url, timeout=30):
    if url in _FETCH_CACHE:
        return _FETCH_CACHE[url]
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    _FETCH_CACHE[url] = body
    return body


def _row(**kw):
    base = dict(unit_or_floorplan_label="", beds="", baths="", sqft="",
                base_rent="", total_price_with_mandatory_fees="", price_basis="",
                concessions_raw="", concessions_type="", concessions_value="",
                availability="", layout_image_url="", price_image_url="",
                concessions_image_url="", price_status="listed")
    base.update(kw)
    return base


def _abs(base_url, u):
    """Resolve a possibly-relative image URL against the page/site URL."""
    if not u:
        return ""
    return urllib.parse.urljoin(base_url, u)


def _num(s):
    if s is None:
        return ""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(s))
    return float(m.group().replace(",", "")) if m else ""


def parse_concession(raw):
    if not raw:
        return "", ""
    r = raw.lower()
    r = re.sub(r"\b(one|two|three|four)\b(?=\s*(?:month|week)s?\s*free)",
               lambda m: {"one": "1", "two": "2", "three": "3", "four": "4"}[m.group(1)], r)
    m = re.search(r"(\d+(?:\.\d+)?)\s*months?\s*free", r)
    if m:
        return "months_free", m.group(1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*weeks?\s*free", r)
    if m:
        return "weeks_free", m.group(1)
    m = re.search(r"\$\s*([\d,]+)\s*(?:off|discount)", r)
    if m:
        return "flat_discount", m.group(1).replace(",", "")
    m = re.search(r"save\s*\$\s*([\d,]+)", r)
    if m:
        return "flat_discount", m.group(1).replace(",", "")
    m = re.search(r"\$\s*([\d,]+)\s*(?:gift\s*card|credit)", r)
    if m:
        return "gift_card_or_credit", m.group(1).replace(",", "")
    if "waive" in r:
        return "waived_fee", ""
    if re.search(r"free|special|sale|% off|flash", r):
        return "other", ""
    return "other", ""


# ---------------------------------------------------------------- ACC lightning
def acc_lightning(url, params):
    list_id = params["list_id"]
    api = f"https://www.americancampus.com/api/lightning/floorplans/{list_id}"
    data = json.loads(fetch(api))
    default_term_id = None
    for v in data.get("TermsFilter", {}).get("Values", []):
        if v.get("Default"):
            default_term_id = v["ID"]
            break
    term = None
    for t in data.get("Terms", []):
        if t["ID"] == default_term_id or default_term_id is None:
            term = t
            break
    if term is None:
        return []
    loc_filter = params.get("location_filter")
    rows = []
    for a in term.get("Attributes", []):
        locs = (a.get("Filters") or {}).get("LocationFilter") or []
        if loc_filter and loc_filter not in locs:
            continue
        sqft = _num(a.get("SqFt"))
        avail = (a.get("Availability") or {}).get("AvText", "")
        min_p, max_p = a.get("MinPrice"), a.get("MaxPrice")
        label = a.get("Title", "")
        basis_note = a.get("PricingText", "")
        range_note = (f"advertised range ${min_p}-${max_p}"
                      if min_p is not None and max_p is not None and max_p > min_p else "")
        avail_parts = [x for x in [avail, f"term: {term['Text']}", range_note] if x]
        rows.append(_row(
            unit_or_floorplan_label=label + (f" [{basis_note}]" if basis_note else ""),
            beds=a.get("BedroomCount", ""), baths=a.get("BathroomCount", ""),
            sqft=int(sqft) if sqft != "" else "",
            base_rent=min_p if min_p is not None else "",
            price_basis="base" if min_p is not None else "",
            availability=" — ".join(avail_parts),
            layout_image_url=_abs("https://www.americancampus.com/", a.get("ImageURL") or ""),
            price_status="listed" if min_p is not None else "not_publicly_listed",
        ))
    return rows


# ---------------------------------------------------------------- 21 Rio wp-json
def wp_entrata_json(url, params):
    data = json.loads(fetch(params["api_url"]))
    rows = []
    cats = data.get("categories") if isinstance(data, dict) and "categories" in data else data
    force_unlisted = params.get("force_not_listed")
    for cat, cdata in (cats or {}).items():
        for fp in cdata.get("floorplans", []):
            name = fp.get("name", "")
            # layout image: 21rio-style `thumbnail` dict or Torre/GMH-style `image` dict
            img = ""
            for key in ("thumbnail", "image"):
                v = fp.get(key)
                if isinstance(v, dict):
                    img = v.get("url") or v.get("abs_url") or ""
                elif isinstance(v, str):
                    img = v
                if img:
                    break
            beds, baths = fp.get("beds", ""), fp.get("baths", "")
            smin, smax = fp.get("sq_ft_min"), fp.get("sq_ft_max")
            sqft = f"{smin}-{smax}" if smin and smax and smax != smin else (smin or "")
            banner = fp.get("banner") or ""
            sold_out_fp = bool(fp.get("sold_out"))
            rates = fp.get("rates") or []
            if not rates:
                rate_min = fp.get("min_rate")
                ctype, cval = parse_concession(banner)
                rows.append(_row(
                    unit_or_floorplan_label=name, beds=beds, baths=baths, sqft=sqft,
                    base_rent=rate_min if rate_min else "",
                    price_basis="base" if rate_min else "",
                    concessions_raw=banner, concessions_type=ctype if banner else "",
                    concessions_value=cval if banner else "",
                    availability="Sold Out" if sold_out_fp else f"{fp.get('units_available', '')} units available",
                    layout_image_url=img,
                    price_status="listed" if rate_min else "not_publicly_listed",
                ))
                continue
            for r in rates:
                special = r.get("special_value") or ""
                msg = r.get("message") or ""
                conc_raw = " | ".join(x for x in [banner, msg, (f"special rate {special}" if special else "")] if x)
                ctype, cval = parse_concession(conc_raw)
                effective = _num(special) if special else r.get("value")
                # junk special guard: a special_value below any plausible rent
                # (e.g. Hilltop's special_value=2 vs value=1375) is data entry
                # noise, not a price — keep it in concessions_raw only
                if special and isinstance(effective, (int, float)) and effective < MIN_PLAUSIBLE_RENT:
                    effective = r.get("value")
                sold = sold_out_fp or bool(r.get("sold_out"))
                rows.append(_row(
                    unit_or_floorplan_label=f"{name} ({r.get('label','')})" if r.get("label") else name,
                    beds=beds, baths=baths, sqft=sqft,
                    base_rent=effective if effective else "",
                    price_basis="base" if effective else "",
                    concessions_raw=conc_raw, concessions_type=ctype if conc_raw else "",
                    concessions_value=cval if conc_raw else "",
                    availability="Sold Out" if sold else "Available",
                    layout_image_url=img,
                    price_status="listed" if effective else "not_publicly_listed",
                ))
    if force_unlisted:
        # feed carries internal rates the site does not display (e.g. Torre is
        # call-for-availability) — keep plan rows, drop non-public prices
        for r in rows:
            r["base_rent"] = ""
            r["price_basis"] = ""
            r["price_status"] = "not_publicly_listed"
            r["availability"] = (r["availability"] + " — call for availability; site shows no live pricing").strip(" —")
    return rows


# ---------------------------------------------------------------- UT Housing
def ut_housing_nueces(url, params):
    html = fetch(url)
    rows = []
    # one <table> per rate year; each row: Apartment Type cell + rate cell "$1,745 (9 months)"
    for table in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S):
        year_m = re.search(r"(20\d\d-\d\d)[^<]{0,30}Rate", table)
        year = year_m.group(1) if year_m else ""
        for tr in re.findall(r"<tr>(.*?)</tr>", table, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(cells) < 2:
                continue
            def clean(c):
                return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            apt = clean(cells[0])
            apt = re.sub(r"^Apartment Type\s*", "", apt)
            rates = re.findall(r"\$([\d,]+)\s*\((\d+)\s*months?\)", clean(cells[1]))
            if not rates or not re.search(r"Bed|Studio|Efficiency", apt, re.I):
                continue
            bm = re.search(r"(\d+)\s*Bedroom", apt)
            thm = re.search(r"(\d+)\s*Bathroom", apt)
            for amount, months in rates:
                rows.append(_row(
                    unit_or_floorplan_label=f"{apt} — {year} rate, {months}-month installments".strip(" —"),
                    beds=bm.group(1) if bm else ("0" if re.search(r"studio|efficiency", apt, re.I) else ""),
                    baths=thm.group(1) if thm else "",
                    base_rent=float(amount.replace(",", "")),
                    price_basis="base",
                    availability=f"per-installment university housing rate ({year})" if year else "per-installment university housing rate",
                ))
    return rows


def ut_housing_dobie(url, params):
    html = fetch(url)
    rows = []
    # article blocks: h3 space name, occupancy, bathrooms, "<year> Rate" header, "Unit: $17,913"
    for art in re.findall(r"<article[^>]*utprop-property-space[^>]*>(.*?)</article>", html, re.S):
        def clean(x):
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()
        name_m = re.search(r"<h3[^>]*>(.*?)</h3>", art, re.S)
        name = clean(name_m.group(1)) if name_m else ""
        name = re.sub(r"\s*3D Tour.*$", "", name, flags=re.I)
        occ_m = re.search(r'field-utprop-occupancy.*?field__item[^>]*>([^<]+)<', art, re.S)
        bath_m = re.search(r'field-utprop-bathrooms.*?field__item[^>]*>([^<]+)<', art, re.S)
        year_m = re.search(r"(20\d\d-\d\d)\s*Rate", art)
        rate_m = re.search(r"(Unit|Per Person):\s*\$([\d,]+)", art)
        if not rate_m:
            continue
        basis_label = rate_m.group(1)
        beds_m = re.search(r"(One|Two|Three|Four|\d+)\s*Bedroom", name, re.I)
        words = {"one": "1", "two": "2", "three": "3", "four": "4"}
        beds = words.get(beds_m.group(1).lower(), beds_m.group(1)) if beds_m else ""
        rows.append(_row(
            unit_or_floorplan_label=f"{name} — {year_m.group(1) if year_m else ''} academic-year rate ({basis_label})"
                                    + (f", {clean(occ_m.group(1))}" if occ_m else ""),
            beds=beds,
            baths="1" if bath_m and re.search(r"one", bath_m.group(1), re.I) else "",
            base_rent=float(rate_m.group(2).replace(",", "")),
            price_basis="base",
            availability=f"university residence hall; rate is per academic year, {basis_label.lower()}",
        ))
    return rows


# ---------------------------------------------------------------- SightMap (Engrain)
def sightmap(url, params):
    """Engrain SightMap public API: floor plans + currently-available units with
    base price, total price incl. mandatory monthly expenses, and specials."""
    import gzip
    import io
    api = params["api_url"]
    req = urllib.request.Request(api, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    data = json.loads(raw)["data"]
    plans = {fp["id"]: fp for fp in data.get("floor_plans", [])}
    by_plan = {}
    for u in data.get("units", []):
        by_plan.setdefault(u.get("floor_plan_id"), []).append(u)
    rows = []
    for pid, fp in plans.items():
        units = by_plan.get(pid, [])
        fp_img = fp.get("image_url") or ""
        if not units:
            rows.append(_row(
                unit_or_floorplan_label=fp.get("name", ""),
                beds=fp.get("bedroom_count", ""), baths=fp.get("bathroom_count", ""),
                availability="no available units listed",
                layout_image_url=fp_img,
                price_status="not_publicly_listed",
            ))
            continue
        for u in units:
            specials = u.get("specials_description") or ""
            ctype, cval = parse_concession(specials)
            total = None
            tp = u.get("total_price") or []
            if tp:
                total = tp[0]
            rows.append(_row(
                unit_or_floorplan_label=f"{fp.get('name','')} — {u.get('display_unit_number','')}",
                beds=fp.get("bedroom_count", ""), baths=fp.get("bathroom_count", ""),
                sqft=u.get("area", ""),
                base_rent=u.get("price", ""),
                total_price_with_mandatory_fees=total if total is not None else "",
                price_basis="total" if total is not None else ("base" if u.get("price") else ""),
                concessions_raw=specials, concessions_type=ctype if specials else "",
                concessions_value=cval if specials else "",
                availability=u.get("display_available_on", ""),
                layout_image_url=fp_img,
                price_status="listed" if u.get("price") else "not_publicly_listed",
            ))
    return rows


# ---------------------------------------------------------------- AppFolio listings
def appfolio_listings(url, params):
    portal = params["portal"].rstrip("/")
    matches = [m.lower() for m in params.get("address_match", [])]
    html = fetch(params.get("listings_url") or (portal + "/listings"))
    rows = []
    mk = re.search(r"markers:\s*(\[[^\n]*\])", html)
    markers = json.loads(mk.group(1)) if mk else []
    for m in markers:
        addr = m.get("address", "")
        if matches and not any(x in addr.lower() for x in matches):
            continue
        specs = m.get("unit_specs", "")
        bm = re.search(r"(\d+)\s*bd", specs)
        thm = re.search(r"(\d+(?:\.\d+)?)\s*ba", specs)
        sm = re.search(r"([\d,]+)\s*Sq", specs)
        rows.append(_row(
            unit_or_floorplan_label=f"AppFolio listing — {specs}",
            beds=bm.group(1) if bm else ("0" if "Studio" in specs else ""),
            baths=thm.group(1) if thm else "",
            sqft=sm.group(1).replace(",", "") if sm else "",
            base_rent=_num(m.get("rent_range")),
            price_basis="base" if m.get("rent_range") else "",
            availability="listed vacancy",
            # default_photo_url is a listing/unit photo, not a floor-plan diagram,
            # and the marker payload carries no plan image — leave blank
            price_status="listed" if m.get("rent_range") else "not_publicly_listed",
        ))
    if not rows:
        fb = params.get("fallback_range")
        if fb:
            rows.append(_row(
                unit_or_floorplan_label=fb.get("label", "property-wide advertised range"),
                base_rent=fb.get("min", ""),
                price_basis="base" if fb.get("min") else "",
                availability=f"no unit-level listing; property page advertises ${fb.get('min')}-${fb.get('max')}/mo",
                price_status="listed" if fb.get("min") else "not_publicly_listed",
            ))
        else:
            rows.append(_row(
                unit_or_floorplan_label="(no public pricing found)",
                availability="no active AppFolio vacancy for this property",
                price_status="not_publicly_listed",
            ))
    return rows


EXTRACTORS = {
    "acc_lightning": acc_lightning,
    "wp_entrata_json": wp_entrata_json,
    "ut_housing_nueces": ut_housing_nueces,
    "ut_housing_dobie": ut_housing_dobie,
    "appfolio_listings": appfolio_listings,
    "sightmap": sightmap,
}


# ================================================================ batch 2 =====

def knock_doorway(url, params):
    """Knock CRM doorway API: layouts + available units with display price."""
    api = f"https://doorway-api.knockrentals.com/v1/property/{params['property_id']}/units"
    data = json.loads(fetch(api))["units_data"]
    layouts = {l["id"]: l for l in data.get("layouts", [])}

    def lay_img(lay):
        ims = lay.get("images") or []
        return (ims[0].get("url") or ims[0].get("thumbUrl") or "") if ims else ""
    by_layout = {}
    for u in data.get("units", []):
        if u.get("hidden") or u.get("deletedAt"):
            continue
        by_layout.setdefault(u.get("layoutId"), []).append(u)
    rows = []
    seen_layouts = set()
    for lid, units in by_layout.items():
        seen_layouts.add(lid)
        lay = layouts.get(lid, {})
        for u in units:
            price = _num(u.get("displayPrice") or u.get("price"))
            rows.append(_row(
                unit_or_floorplan_label=f"{u.get('layoutName') or lay.get('name','')} — Unit {u.get('name','')}",
                beds=u.get("bedrooms", lay.get("bedrooms", "")),
                baths=u.get("bathrooms", lay.get("bathrooms", "")),
                sqft=u.get("area", lay.get("area", "")),
                base_rent=price if price != "" else "",
                price_basis="base" if price != "" else "",
                availability=("Available " + (u.get("availableOn") or "now")) if u.get("available") else "Not available",
                layout_image_url=lay_img(lay),
                price_status="listed" if price != "" else "not_publicly_listed",
            ))
    for lid, lay in layouts.items():
        if lid in seen_layouts:
            continue
        rows.append(_row(
            unit_or_floorplan_label=lay.get("name", "") or lay.get("description", ""),
            beds=lay.get("bedrooms", ""), baths=lay.get("bathrooms", ""), sqft=lay.get("area", ""),
            availability="no available units listed",
            layout_image_url=lay_img(lay),
            price_status="not_publicly_listed",
        ))
    return rows


def duda_appfolio_feed(url, params):
    """Duda site collection mirroring an AppFolio listings feed (e.g. Rainier)."""
    data = json.loads(fetch(params["feed_url"]))
    matches = [m.lower() for m in params.get("address_match", [])]
    rows = []
    for item in data.get("values", []):
        d = item.get("data", item)
        addr = d.get("full_address", "")
        if matches and not any(m in addr.lower() for m in matches):
            continue
        if str(d.get("available")).lower() != "true":
            continue
        rent = _num(d.get("market_rent") or d.get("rent"))
        # feed photos are listing/unit photos; no floor-plan field exists — leave blank
        title = d.get("marketing_title", "") or addr
        promo_m = re.search(r"(one month free[^*]*|\d+ month[s]? free[^*]*|free rent[^*]*)", title, re.I)
        ctype, cval = parse_concession(promo_m.group(1)) if promo_m else ("", "")
        rows.append(_row(
            concessions_raw=promo_m.group(1).strip() if promo_m else "",
            concessions_type=ctype, concessions_value=cval,
            unit_or_floorplan_label=title,
            beds=_num(d.get("bedrooms")) or "",
            baths=_num(d.get("bathrooms")) or "",
            sqft=int(_num(d.get("square_feet"))) if _num(d.get("square_feet")) != "" else "",
            base_rent=rent,
            price_basis="base" if rent != "" else "",
            availability=("available " + (d.get("available_date") or "")).strip(),
            price_status="listed" if rent != "" else "not_publicly_listed",
        ))
    if not rows:
        rows.append(_row(unit_or_floorplan_label="(no active listings in feed)",
                         availability="no active AppFolio listing for this address",
                         price_status="not_publicly_listed"))
    return rows


def ut_offcampus_directory(url, params):
    """UT off-campus housing directory page; unit data embedded as JSON in page JS.
    Third-party directory, not the property's own site — config sets source_type."""
    html = fetch(url)
    i = html.find('"units":[')
    if i < 0:
        return [_row(unit_or_floorplan_label="(no unit data on directory page)",
                     price_status="not_publicly_listed",
                     availability="directory page had no embedded units array")]
    # bracket-match the units array
    start = i + len('"units":')
    depth = 0
    for j in range(start, len(html)):
        if html[j] == "[":
            depth += 1
        elif html[j] == "]":
            depth -= 1
            if depth == 0:
                break
    units = json.loads(html[start:j + 1])
    rows = []
    for u in units:
        mn, mx = _num(u.get("min_rent")), _num(u.get("max_rent"))
        rows.append(_row(
            unit_or_floorplan_label=(u.get("title") or u.get("unit_number") or "unit"),
            beds=u.get("bed", ""), baths=u.get("bath", ""),
            sqft=_num(u.get("sqft") or u.get("square_feet")) or "",
            base_rent=mn if mn != "" else "",
            price_basis="base" if mn != "" else "",
            availability=(f"advertised range ${int(mn)}-${int(mx)}"
                          if mn != "" and mx != "" and mx > mn else ""),
            price_status="listed" if mn != "" else "not_publicly_listed",
        ))
    return rows


def spearhead_static(url, params):
    """Spearhead Properties single-property page; unit rows in table with popovers."""
    html = fetch(url)
    # layout images carry the sqft in the filename (e.g. Oak-Grove-11-623-sq-ft-1.jpg)
    imgs = re.findall(r'<img[^>]+(?:data-src|src)="([^"]+wp-content/uploads/[^"]+)"', html)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", html))
    rows = []
    # rows look like: Unit name|||$1,400 / mo||1||1||623 sq ft|| <availability text>|||
    pat = re.compile(r"([\w \-\.]{3,40})\|+\$([\d,]+)\s*/\s*mo\|+(\d+)\|+([\d\.]+)\|+([\d,]+)\s*sq ?ft\|+([^|]{0,80})")
    for m in pat.finditer(text):
        label, rent, beds, baths, sqft, avail = m.groups()
        sq = sqft.replace(",", "")
        img = next((_abs(url, i) for i in imgs if f"{sq}-sq" in i), "")
        rows.append(_row(
            unit_or_floorplan_label=label.strip(),
            beds=beds, baths=baths, sqft=sq,
            base_rent=float(rent.replace(",", "")),
            price_basis="base",
            availability=avail.strip(),
            layout_image_url=img,
        ))
    return rows


def resolute_static(url, params):
    """Resolute Real Estate property page; 'Unit A1 | 1 bed / 1 bath | 500 sq. ft. | $1,300/Month' blocks."""
    html = fetch(url)
    # layout images named by plan code (e.g. A1Floorplan.png for "Unit A1")
    imgs = re.findall(r'<img[^>]+(?:data-src|src)="([^"]+wp-content/uploads/[^"]+)"', html)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", html))
    rows = []
    pat = re.compile(r"(Unit [\w\-]+)[\s|]+(\d+)\s*bed(?:room)?s?\s*/\s*([\d\.]+)\s*bath(?:room)?s?[\s|]+([\d,]+)\s*sq\.? ?ft\.?[\s|]*\$([\d,]+)/Month", re.I)
    for m in pat.finditer(text):
        label, beds, baths, sqft, rent = m.groups()
        code = label.replace("Unit", "").strip()
        img = next((_abs(url, i) for i in imgs
                    if re.search(re.escape(code) + r"[\-_]?Floorplan", i, re.I)), "")
        rows.append(_row(
            unit_or_floorplan_label=label, beds=beds, baths=baths,
            sqft=sqft.replace(",", ""),
            base_rent=float(rent.replace(",", "")),
            price_basis="base",
            availability="advertised for lease",
            layout_image_url=img,
        ))
    return rows


def ninehundred_static(url, params):
    """9HUNDRED floorplans page: 'N Bed / N Bath NAME NNN SF* Call for Pricing' — no public price."""
    html = fetch(url)
    # plan images named like 2A-2x2-L-9hundred-floorplan-*.jpeg; some exist only as
    # -WxH resized copies, so match any and strip the size suffix to get the original
    imgs = [re.sub(r"-\d+x\d+(\.\w+)$", r"\1", i)
            for i in re.findall(r'<img[^>]+(?:data-src|src)="([^"]+wp-content/uploads/[^"]+)"', html)
            if "floorplan" in i.lower()]
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    rows = []
    pat = re.compile(r"(\d+)\s*Bed\s*/\s*([\d\.]+)\s*Bath\s+([\w\- ]{1,20}?)\s+([\d,]{3,5})\s*SF\*?\s*(Call for Pricing)?", re.I)
    for m in pat.finditer(text):
        beds, baths, name, sqft, cfp = m.groups()
        key = re.sub(r"[^\w]", "", name).upper()
        img = next((_abs(url, i) for i in imgs
                    if key and re.search(r"(?:^|[\-_])" + re.escape(key) + r"(?:[\-_]|\.)",
                                         i.rsplit("/", 1)[-1], re.I)), "")
        rows.append(_row(
            unit_or_floorplan_label=name.strip(), beds=beds, baths=baths,
            sqft=sqft.replace(",", ""),
            availability="advertised; pricing on request",
            layout_image_url=img,
            price_status="not_publicly_listed",
        ))
    return rows


def sgs_static(url, params):
    """San Gabriel Square: per-plan sub-pages list beds/baths but no pricing."""
    html = fetch(url)
    links = sorted(set(re.findall(r'href="(https://www\.liveatsangabrielsquareaustin\.com/floor-plans/[a-z\-]+/)"', html)))
    rows = []
    for link in links:
        page = fetch(link)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
        tm = re.search(r"(?:Request a Tour|Residents)\s+([A-Z][\w \-]{3,40}?)\s+(\d+)\s*Bedrooms?\s+([\d\.]+)\s*Bath", text)
        if tm:
            name, beds, baths = tm.groups()
        else:
            name = link.rstrip("/").split("/")[-1].replace("-", " ").title()
            bm = re.search(r"(\d+)\s*Bedrooms?", text)
            thm = re.search(r"([\d\.]+)\s*Bath", text)
            beds = bm.group(1) if bm else ("0" if "efficiency" in link else "")
            baths = thm.group(1) if thm else ""
        sm = re.search(r"([\d,]{3,5})\s*(?:sq\.? ?ft|square feet)", text, re.I)
        prices = [p for p in re.findall(r"\$([\d,]{3,6})", text) if 500 <= float(p.replace(",", "")) <= 8000]
        # plan image filename encodes bedsxbathsxsqft (e.g. ..._0x1x440.jpg); skip logos/resized dupes
        img_cands = [i for i in re.findall(r'<img[^>]+(?:data-src|src)="([^"]+wp-content/uploads/[^"]+)"', page)
                     if not re.search(r"logo|fav|-\d+x\d+\.\w+$", i, re.I)]
        img = next((i for i in img_cands if re.search(r"_\d+x[\d\.]+x\d+", i)), "")
        rows.append(_row(
            unit_or_floorplan_label=name.strip(),
            beds=beds, baths=baths,
            sqft=sm.group(1).replace(",", "") if sm else "",
            base_rent=float(prices[0].replace(",", "")) if prices else "",
            price_basis="base" if prices else "",
            availability="see property site",
            layout_image_url=_abs(link, img),
            price_status="listed" if prices else "not_publicly_listed",
        ))
        import time as _t
        _t.sleep(2)
    return rows


EXTRACTORS.update({
    "knock_doorway": knock_doorway,
    "duda_appfolio_feed": duda_appfolio_feed,
    "ut_offcampus_directory": ut_offcampus_directory,
    "spearhead_static": spearhead_static,
    "resolute_static": resolute_static,
    "ninehundred_static": ninehundred_static,
    "sgs_static": sgs_static,
})


# ================================================================ batch 3 =====

def mmc_ajax(url, params):
    """MMC/vNue WP theme (Villas on Nueces): floorplans page lists fpRouter links
    /floorplans/<cat>/<sub>; admin-ajax returns an HTML fragment per plan with
    Double/Single occupancy pricing."""
    import time as _t
    html = fetch(url)
    pairs = []
    for cat, sub in re.findall(r'href="/floorplans/([\w_]+)/([\w\d]+)"', html):
        if (cat, sub) not in pairs:
            pairs.append((cat, sub))
    post_id_m = re.search(r"mmc_ajax_post_id=(\d+)", html)
    post_id = post_id_m.group(1) if post_id_m else params.get("post_id", "35")
    base = url.split("/floorplans")[0]
    rows = []
    for cat, sub in pairs:
        frag = fetch(f"{base}/wp-admin/admin-ajax.php?action=mmc_get_MMCFlooplansData"
                     f"&d%5Bfpcat%5D={cat}&d%5Bfpsub%5D={sub}&mmc_ajax_post_id={post_id}")
        img_m = re.search(r'<img[^>]+(?:data-src|src)="([^"]+)"', frag)
        img = _abs(base, img_m.group(1)) if img_m else ""
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", frag))
        name_m = re.search(r"\|\s*([A-Z]{1,3}\d{0,2})\s*\|Double Occupancy", text) or \
                 re.search(r"\|\s*([A-Z]{1,3}\d{0,2})\s*\|Single Occupancy", text)
        name = name_m.group(1) if name_m else sub.upper()
        bb_m = re.search(r"(\d+)\s*Bedroom[s]?\s*•\s*([\d\.]+)\s*Bath", text)
        sq_m = re.search(r"([\d,]{3,5})\s*Sq\.? ?Ft", text, re.I)
        # occupancy sections: "<NAME> |<Occupancy> |Units Available| ... |$1795|"
        found = False
        sections = re.split(r"(Double|Single) Occupancy", text)
        # re.split keeps delimiters: [pre, occ1, seg1, occ2, seg2, ...]
        occ_pairs = list(zip(sections[1::2], sections[2::2]))
        for occ, seg in occ_pairs:
            seg = seg[:400]
            price_m = re.search(r"\$([\d,]{3,6})", seg)
            avail = "Units Available" if "Units Available" in seg else ("Sold Out" if re.search(r"sold\s*out", seg, re.I) else "")
            if not price_m and not avail:
                continue
            found = True
            rows.append(_row(
                unit_or_floorplan_label=f"{name} ({occ} Occupancy)",
                beds=bb_m.group(1) if bb_m else ("0" if cat == "studio" else cat.split("_")[0]),
                baths=bb_m.group(2) if bb_m else "",
                sqft=sq_m.group(1).replace(",", "") if sq_m else "",
                base_rent=float(price_m.group(1).replace(",", "")) if price_m else "",
                price_basis="base" if price_m else "",
                availability=avail or "see site",
                layout_image_url=img,
                price_status="listed" if price_m else "not_publicly_listed",
            ))
        if not found:
            rows.append(_row(
                unit_or_floorplan_label=name,
                beds="0" if cat == "studio" else cat.split("_")[0],
                baths=bb_m.group(2) if bb_m else "",
                sqft=sq_m.group(1).replace(",", "") if sq_m else "",
                availability="no pricing in plan fragment",
                layout_image_url=img,
                price_status="not_publicly_listed",
            ))
        _t.sleep(2)
    best = {}
    for r in rows:
        k = r["unit_or_floorplan_label"]
        if k not in best or (best[k]["base_rent"] == "" and r["base_rent"] != ""):
            best[k] = r
    return list(best.values())


def vsg_static(url, params):
    """Villas at San Gabriel: server-rendered bedroom-group tab panels.

    Studio / 1 / 3 / 4 / 5 / 6 Bedroom panels are all in the HTML (no click
    required). Each ``li.fp-card.stack-2`` is one advertised floor plan with
    name, optional $, layout image, beds/baths, and sqft.
    """
    html = fetch(url)
    rows = []
    card_re = re.compile(
        r'<li class="fp-card stack-2 bg-w" id="([^"]+)">(.*?)'
        r'(?=<li class="fp-card stack-2 bg-w"|</ul>\s*<!-- END \.floor-plan-card-list)',
        re.S)
    for m in card_re.finditer(html):
        body = m.group(2)
        name_m = re.search(r"<h4>([^<]+)</h4>", body)
        name = (name_m.group(1).strip() if name_m else m.group(1)).strip()
        price_m = re.search(r'class="fp-misc-content">\s*<p>\s*\$?\s*([\d,]+)', body)
        rent = _num(price_m.group(1)) if price_m else ""
        det_m = re.search(r'<ul class="fp-details">(.*?)</ul>', body, re.S)
        details = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", det_m.group(1) if det_m else ""))
        beds, baths = "", ""
        if re.search(r"\bstudio\b", details, re.I):
            beds = "0"
        bm = re.search(r"(\d+)\s*Bedroom", details, re.I)
        if bm:
            beds = bm.group(1)
        bam = re.search(r"(\d+(?:\.\d+)?)\s*Bath", details, re.I)
        if bam:
            baths = bam.group(1)
        sq_m = re.search(r"([\d,]+)\s*Sq\.?\s*Ft", details, re.I)
        sqft = sq_m.group(1).replace(",", "") if sq_m else ""
        img = ""
        href_m = re.search(r'class="fp-card-image-link"[^>]*href="([^"]+)"', body)
        if href_m:
            img = _abs(url, href_m.group(1))
        if not img:
            src_m = re.search(r'<img[^>]+src="([^"]+)"', body)
            if src_m:
                img = _abs(url, src_m.group(1))
        smart = "SMART Housing Only" if re.search(r"SMART Housing", details, re.I) else ""
        sold_m = re.search(
            r'class="fp-card__sold-out-text"[^>]*(?:style="([^"]*)")?[^>]*>\s*([^<]+)',
            body, re.S)
        sold_hidden = bool(sold_m and sold_m.group(1) and "display: none" in sold_m.group(1))
        sold_txt = (sold_m.group(2).strip() if sold_m and not sold_hidden else "")
        avail = " — ".join(x for x in [
            sold_txt or "advertised on floor-plans page",
            smart,
            "price shown on card" if rent != "" else "no price on card",
        ] if x)
        rows.append(_row(
            unit_or_floorplan_label=name,
            beds=beds, baths=baths, sqft=sqft,
            base_rent=rent if rent != "" else "",
            price_basis="base" if rent != "" else "",
            concessions_raw=smart,
            concessions_type="other" if smart else "",
            availability=avail,
            layout_image_url=img,
            price_status="listed" if rent != "" else "not_publicly_listed",
        ))
    return rows


def no_public_pricing(url, params):
    """Explicit placeholder for properties whose site publishes no pricing data at all."""
    return [_row(
        unit_or_floorplan_label=params.get("label", "(no public pricing on site)"),
        availability=params.get("reason", "site publishes no floor-plan pricing"),
        price_status="not_publicly_listed",
    )]


EXTRACTORS.update({
    "mmc_ajax": mmc_ajax,
    "vsg_static": vsg_static,
    "no_public_pricing": no_public_pricing,
})


def vnue_grid_static(url, params):
    """vNue WP family plan grid (Villas on 26th): fpnavitem blocks with name +
    details; .floor-plan__rate is empty — no public pricing."""
    html = fetch(url)

    def srcset_best(tag):
        ss = re.search(r'srcset="([^"]+)"', tag)
        if ss:
            cands = []
            for c in ss.group(1).split(","):
                parts = c.strip().split()
                w = _num(parts[1]) if len(parts) > 1 else 0
                cands.append((w if w != "" else 0, parts[0]))
            if cands:
                return max(cands)[1]
        sm = re.search(r'(?:data-src|src)="([^"]+)"', tag)
        return sm.group(1) if sm else ""

    rows = []
    for m in re.finditer(r'fpnavitem__title">\s*<h2>([^<]+)</h2>\s*<ul class="fpnavitem__details">(.*?)</ul>', html, re.S):
        name, det = m.groups()
        # plan image: fpnavitem__img tag shortly after this block
        img_m = re.search(r'<img[^>]+fpnavitem__img[^>]*>', html[m.end():m.end() + 3000])
        img = _abs(url, srcset_best(img_m.group(0))) if img_m else ""
        items = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", li)).strip() for li in re.split(r"<li>", det) if li.strip()]
        beds = baths = sqft = ""
        for it in items:
            if re.search(r"studio", it, re.I):
                beds = "0"
            bm = re.match(r"(\d+)\s*Bed", it, re.I)
            if bm:
                beds = bm.group(1)
            thm = re.match(r"([\d\.]+)\s*Bath", it, re.I)
            if thm:
                baths = thm.group(1)
            sm = re.match(r"([\d,]{3,5})\s*Sq", it, re.I)
            if sm:
                sqft = sm.group(1).replace(",", "")
        # names in the page use HTML entities (3&#215;2 = 3x2)
        clean_name = name.strip().replace("&#215;", "x")
        rate_key = re.escape(name.strip().lower())
        rate_m = re.search(r'id="fp-' + rate_key + r'"[^>]*>\s*<h2 class="floor-plan__rate">([^<]*)<', html, re.I)
        rate_text = rate_m.group(1).strip() if rate_m else ""
        # the "rate" slot often carries availability text, not a price
        rate = _num(rate_text) if re.match(r"^\$?[\d,\.]+(\s*/|$)", rate_text) else ""
        rows.append(_row(
            unit_or_floorplan_label=clean_name,
            beds=beds, baths=baths, sqft=sqft,
            base_rent=rate,
            price_basis="base" if rate != "" else "",
            availability=rate_text if (rate_text and rate == "") else ("plan advertised" if rate != "" else "plan advertised; no rate shown on site"),
            layout_image_url=img,
            price_status="listed" if rate != "" else "not_publicly_listed",
        ))
    return rows


EXTRACTORS["vnue_grid_static"] = vnue_grid_static


def jonah_detail_json(url, params):
    """JonahSystems sites: plan slugs are static links on the floorplans page;
    each detail page embeds jd-fp-data-script-resource JSON with rent_min/max,
    beds/baths, sqft, availability_count, and the priced lease term."""
    import time as _t
    html = fetch(url)
    base = re.match(r"(https://[^/]+)", url).group(1)
    slugs = []
    for m in re.finditer(r'href="(?:' + re.escape(base) + r')?/floorplans/([a-z0-9\-]+)/"', html):
        if m.group(1) not in slugs:
            slugs.append(m.group(1))
    rows = []
    for slug in slugs:
        try:
            page = fetch(f"{base}/floorplans/{slug}/")
        except Exception:
            continue
        # plan image: detail-page <img> whose alt/title mentions "floorplan"
        img = ""
        for tag in re.findall(r"<img[^>]+>", page):
            if re.search(r'(?:alt|title)="[^"]*floor ?plan', tag, re.I):
                sm = re.search(r'(?:data-src|src)="([^"]+)"', tag)
                if sm:
                    img = _abs(base, sm.group(1))
                    break
        m = re.search(r'id="jd-fp-data-script-resource">(\{.*?\})</script>', page, re.S)
        if not m:
            rows.append(_row(unit_or_floorplan_label=slug.upper().replace("-", " "),
                             availability="plan page had no data block",
                             price_status="not_publicly_listed"))
            _t.sleep(2)
            continue
        d = json.loads(m.group(1))
        pe = d.get("price_entity") or {}
        rent_min = _num(d.get("rent_min"))
        rent_max = _num(d.get("rent_max"))
        sqft = d.get("square_feet") or ""
        if d.get("max_square_feet") and d.get("max_square_feet") != sqft:
            sqft = f"{sqft}-{d['max_square_feet']}"
        term = pe.get("termDisplay") or ""
        avail_n = d.get("availability_count")
        beds = d.get("bedrooms", "")
        if isinstance(beds, str) and re.search(r"studio|efficiency", beds, re.I):
            beds = "0"
        rows.append(_row(
            unit_or_floorplan_label=d.get("title", slug.upper()),
            beds=beds, baths=d.get("bathrooms", ""),
            sqft=sqft,
            base_rent=rent_min if rent_min != "" else "",
            price_basis="base" if rent_min != "" else "",
            availability=" — ".join(x for x in [
                f"{avail_n} available" if avail_n is not None else "",
                f"term: {term}" if term else "",
                f"advertised range ${int(rent_min)}-${int(rent_max)}" if rent_min != "" and rent_max != "" and rent_max > rent_min else "",
            ] if x),
            layout_image_url=img,
            price_status="listed" if rent_min != "" else "not_publicly_listed",
        ))
        _t.sleep(2)
    return rows


EXTRACTORS["jonah_detail_json"] = jonah_detail_json


# ================================================================ batch 4 =====

def realpage_cms_proxy(url, params):
    """RealPage CMS sites (legacy .aspx): /CmsSiteManager/callback.aspx proxies the
    RealPage WS API server-side — no auth needed. GetFloorPlans + GetUnits."""
    base = re.match(r"(https://[^/]+)", url).group(1)
    def get(act):
        body = fetch(f"{base}/CmsSiteManager/callback.aspx?act=Proxy/{act}")
        body = re.sub(r"^[\w\$\.]+\(", "", body.strip())  # strip JSONP wrapper if present
        body = re.sub(r"\)\s*;?\s*$", "", body)
        return json.loads(body)
    fps = get("GetFloorPlans")
    plans = {str(p["id"]): p for p in fps.get("floorplans", [])}

    def plan_img(p):
        # dimg URLs carry a %s size-token slot; native WxH works (tested)
        ims = sorted(p.get("floorPlanImages") or [],
                     key=lambda i: (0 if re.search(r"2D|Diagram", str(i.get("tag")), re.I) else 1,
                                    i.get("displaySequence") or 0))
        if not ims:
            return ""
        src = ims[0].get("httpsSrc") or ims[0].get("src") or ""
        if "%s" in src:
            src = src.replace("%s", f"{ims[0].get('maxWidth') or 700}x{ims[0].get('maxHeight') or 700}")
        return src
    rows = []
    covered = set()
    try:
        units = get("GetUnits").get("units", [])
    except Exception:
        units = []
    for u in units:
        if u.get("displayed") is False or u.get("active") is False:
            continue
        rent = u.get("rent")
        val = float(rent) if rent not in (None, "") else ""
        p = plans.get(str(u.get("floorplanId")), {})
        covered.add(str(u.get("floorplanId")))
        rows.append(_row(
            unit_or_floorplan_label=f"{p.get('name','Floorplan '+str(u.get('floorplanId')))} — Unit {u.get('unitNumber') or u.get('name','')}",
            beds=u.get("numberOfBeds", p.get("bedRooms", "")),
            baths=u.get("numberOfBaths", p.get("bathRooms", "")),
            sqft=u.get("squareFeet", ""),
            base_rent=val,
            price_basis="base" if val != "" else "",
            availability=" — ".join(x for x in [u.get("leaseStatus", ""),
                                                ("vacant " + str(u.get("vacantDate"))[:10]) if u.get("vacantDate") else ""] if x),
            layout_image_url=plan_img(p),
            price_status="listed" if val != "" else "not_publicly_listed",
        ))
    for pid, p in plans.items():
        if pid in covered:
            continue
        rent = p.get("rentMin") or p.get("rent")
        val = float(rent) if rent not in (None, "", 0) else ""
        rows.append(_row(
            unit_or_floorplan_label=(p.get("name", "") or "") + " [floorplan]",
            beds=p.get("bedRooms", ""), baths=p.get("bathRooms", ""),
            sqft=p.get("squareFeet", "") or p.get("minSquareFeet", ""),
            base_rent=val,
            price_basis="base" if val != "" else "",
            availability="no available units listed",
            layout_image_url=plan_img(p),
            price_status="listed" if val != "" else "not_publicly_listed",
        ))
    return rows


def ut_rates_table(url, params):
    """Generic UT Housing rates tables: 'Unit/Apartment Type | Rate' rows, optionally
    filtered (e.g. Gateway rows are prefixed GAT on the shared University Apartments page)."""
    html = fetch(url)
    filt = params.get("row_filter")  # regex a row label must match
    rows = []
    for table in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S):
        # year context: nearest heading before the table isn't captured here; look inside page order instead
        for tr in re.findall(r"<tr>(.*?)</tr>", table, re.S):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
            if len(cells) < 2:
                continue
            def clean(c):
                return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            label, ratec = clean(cells[0]), clean(cells[1])
            if re.search(r"(?i)^(unit|apartment)\s*type|^rate$", label) or not label:
                continue
            if filt and not re.search(filt, label):
                continue
            pm = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", ratec.replace("| ", "").replace(" |", ""))
            if not pm:
                continue
            bm = re.search(r"(\d+)\s*Bed", label, re.I)
            rows.append(_row(
                unit_or_floorplan_label=label + (f" — {params.get('label_note')}" if params.get("label_note") else ""),
                beds=bm.group(1) if bm else ("0" if re.search(r"(?i)studio|efficiency", label) else ""),
                baths="",
                base_rent=float(pm.group(1).replace(",", "")),
                price_basis="base",
                availability=params.get("availability_note", "university housing monthly rate"),
            ))
    # de-dup identical (label, rent) rows that appear in both current+past tables: keep first
    seen = set()
    out = []
    for r in rows:
        k = (r["unit_or_floorplan_label"], r["base_rent"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def collegehouses_rates(url, params):
    """College Houses shared rates page: per-house blocks with Private/Shared room
    base rent, mandatory utilities+meals, and Total Monthly cost."""
    html = fetch("https://collegehouses.org/rates/")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", html))
    house = params["house"]
    m = None
    for cand in re.finditer(re.escape(house) + r".{0,4000}?(?=\|[A-Z][\w ]{2,22}Co-op\||$)", text):
        if "Base Rent" in cand.group(0):
            m = cand
            break
    if not m:
        return [_row(unit_or_floorplan_label=f"({house} not found on rates page)",
                     availability="no rates block on collegehouses.org/rates",
                     price_status="not_publicly_listed")]
    block = m.group(0)
    term_m = re.search(r"(Fall \d{4}/Spring \d{4}) Rates", block)
    term = term_m.group(1) if term_m else ""
    rows = []
    for rm in re.finditer(r"(Private Room|Shared Bedroom|Single Room|Double Room)\s*Base Rent:\s*\$([\d,]+)(.{0,240}?)Total Monthly cost:\s*\$([\d,]+)", block):
        room, base, mid, total = rm.groups()
        fees = re.findall(r"([A-Za-z\+ \d]+?):\s*\$([\d,]+)", mid)
        fee_txt = "; ".join(f"{a.strip()} ${b}" for a, b in fees)
        rows.append(_row(
            unit_or_floorplan_label=f"{room}" + (f" ({term})" if term else ""),
            beds="", baths="",
            base_rent=float(base.replace(",", "")),
            total_price_with_mandatory_fees=float(total.replace(",", "")),
            price_basis="total",
            availability=("co-op per-resident rate" + (f"; mandatory: {fee_txt}" if fee_txt else "")),
        ))
    return rows


def ballpark_static(url, params):
    """Ballpark North: elementor cards 'Name | N bed | N bath | NNNsqft | Starting at $X'."""
    html = fetch(url)
    # plan diagrams named by beds/baths (e.g. 2-bed-2-bath_ltr-LA-300x300.png,
    # 1-bed-efficiency-LA-300x300.png); strip the -WxH suffix for the original
    imgs = [re.sub(r"-\d+x\d+(\.\w+)$", r"\1", i)
            for i in re.findall(r'<img[^>]+(?:data-src|src)="([^"]+wp-content/uploads/[^"]+)"', html)
            if re.search(r"\d-bed", i, re.I)]
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", html))
    rows = []
    pat = re.compile(r"([A-Z][\w, \-]{2,35}?)\s*\|[\s|]*(\d+)\s*beds?\s*\|\s*([\d\.]+)\s*baths?\s*\|\s*([\d,]{3,5})\s*sqft[\s|]*Starting at \$([\d,]{3,6})", re.I)
    for m in pat.finditer(text):
        name, beds, baths, sqft, rent = m.groups()
        bath_n = str(int(float(baths))) if _num(baths) != "" else baths
        img = next((_abs(url, i) for i in imgs
                    if f"{beds}-bed" in i.lower()
                    and (f"{bath_n}-bath" in i.lower() or "efficiency" in i.lower())), "")
        rows.append(_row(
            unit_or_floorplan_label=name.strip(),
            beds=beds, baths=baths, sqft=sqft.replace(",", ""),
            base_rent=float(rent.replace(",", "")),
            price_basis="base",
            availability="starting-at price on floor-plans page",
            layout_image_url=img,
        ))
    return rows


def westside_prose(url, params):
    """Westside Group property pages: prose rent mentions + AppFolio vacancies.
    Some prices are baked into images — those are flagged, not guessed."""
    rows = []
    html = fetch(url)
    # content images: layout = floorplan/dimension drawing; price = price baked into an image
    imgs = [i for i in re.findall(r'<img[^>]+(?:data-src|src)="([^"]+wp-content/uploads/[^"]+)"', html)
            if not re.search(r"logo|icon", i, re.I)]
    # plan diagrams only (e.g. hyde-park-court-1br-floor-plan.png,
    # envoy-1br-floor-dimension.png) — room photos also mention "2BR" etc., so
    # require a floor/plan/dimension token in the filename
    plan_imgs = [_abs(url, i) for i in imgs if re.search(r"floor|plan|dimension", i, re.I)]

    def plan_img_for(beds):
        # match by bedroom count when the filename encodes it; otherwise only
        # safe to use a page-level plan image if the page has exactly one
        if beds:
            hit = next((i for i in plan_imgs if re.search(rf"\b{beds}\s*br|{beds}-?br|{beds}-?bed", i, re.I)), "")
            if hit:
                return hit
        return plan_imgs[0] if len(plan_imgs) == 1 else ""
    layout_img = plan_img_for("")
    price_img = next((_abs(url, i) for i in imgs if re.search(r"price|rent|rate|month", i, re.I)), "")
    # structured Elementor icon-list price items, written without a dollar sign
    # since the 2026 redesign: "1195/Month (1BR/1BA)" or "1150/Month", followed by
    # descriptor items ("Full Apartment Unit", "450 Sq Ft", "1Bed/1Bath")
    lis = [re.sub(r"\s+", " ", x).strip()
           for x in re.findall(r'elementor-icon-list-text">\s*([^<]{1,80}?)\s*<', html)]
    price_li = re.compile(r"^\$?\s*([\d,]{3,6})\s*/\s*Month(?:\s*\(\s*(\d+)\s*BR\s*/\s*([\d\.]+)\s*BA\s*\))?$", re.I)
    seen_rents = set()
    i = 0
    while i < len(lis):
        m = price_li.match(lis[i])
        if not m:
            i += 1
            continue
        rent = float(m.group(1).replace(",", ""))
        beds, baths = m.group(2) or "", m.group(3) or ""
        unit_type = sqft = ""
        j = i + 1
        while j < len(lis) and j <= i + 4 and not price_li.match(lis[j]):
            sm = re.match(r"([\d,]{3,5})\s*Sq\.? ?Ft", lis[j], re.I)
            bm = re.match(r"(\d+)\s*Bed[s]?\s*/\s*([\d\.]+)\s*Bath", lis[j], re.I)
            if sm:
                sqft = sm.group(1).replace(",", "")
            elif bm:
                beds, baths = beds or bm.group(1), baths or bm.group(2)
            elif re.search(r"unit", lis[j], re.I):
                unit_type = lis[j]
            j += 1
        seen_rents.add(rent)
        rows.append(_row(
            unit_or_floorplan_label=(unit_type or "advertised unit")
                                    + (f" ({beds}BR/{baths}BA)" if beds else ""),
            beds=beds, baths=baths, sqft=sqft,
            base_rent=rent,
            price_basis="base",
            availability="price in page icon list",
            layout_image_url=plan_img_for(beds),
        ))
        i = j
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    for m in re.finditer(r"([^.]{0,140}?)\$\s*([\d,]{3,6})\s*(?:/|per\s*)month([^.]{0,60})", text):
        pre, rent, post = m.groups()
        if re.search(r"(?i)fee|deposit", pre + post):
            continue
        if float(rent.replace(",", "")) in seen_rents:
            continue  # same price already captured from the icon list
        rows.append(_row(
            unit_or_floorplan_label="advertised in page text: …" + pre.strip()[-60:],
            base_rent=float(rent.replace(",", "")),
            price_basis="base",
            availability="price stated in page prose",
            layout_image_url=layout_img,
        ))
    rows += appfolio_listings(url, params)
    note = params.get("image_price_note")
    if note:
        rows.append(_row(
            unit_or_floorplan_label="(image-only pricing)",
            availability=note,
            layout_image_url=layout_img,
            price_image_url=price_img,
            price_status="not_publicly_listed",
        ))
    return rows


EXTRACTORS.update({
    "realpage_cms_proxy": realpage_cms_proxy,
    "ut_rates_table": ut_rates_table,
    "collegehouses_rates": collegehouses_rates,
    "ballpark_static": ballpark_static,
    "westside_prose": westside_prose,
})


def uptown_realty(url, params):
    """Uptown Realty Austin (uptownrealtyaustin.com) — custom WordPress community &
    unit pages. Pricing lives in static HTML under a 'Property Specifics' / 'Unit
    Specifics' heading as a stack of <div class="ampti"> cards, each with:
      ampti-quant  -> number + <small>Bedroom</small>
      ampti-quant  -> number + <small>bath</small>
      ampti-price  -> number + <small>Per month</small>   ($ and commas possible)
      ampti-square -> number + <small>Sq. Ft.</small>     (may be blank on unit pages)
    No per-plan floor-plan diagrams are exposed (slider holds listing photos only),
    so layout_image_url stays blank. Availability, when present, comes from an
    amenities <li>Available: ...</li>.
    """
    html = fetch(url)
    am = re.search(r"Available:\s*([^<]+?)\s*</li>", html)
    avail = am.group(1).strip() if am else "advertised for lease"
    rows = []
    for block in re.findall(r'<div class="ampti">(.*?)</div>', html, re.S):
        def field(label):
            m = re.search(r'([\$\d,\.]+)\s*<small>\s*' + re.escape(label) + r"\s*</small>",
                          block, re.I)
            return m.group(1) if m else ""
        beds_s = field("Bedroom").replace(",", "")
        baths_s = field("bath").replace(",", "")
        price_s = field("Per month")
        sqft_s = field("Sq. Ft.").replace(",", "")
        if not (beds_s or baths_s or price_s):
            continue  # empty/decorative card
        rent = _num(price_s)
        bed_lbl = f"{beds_s} Bed" if beds_s else ""
        bath_lbl = f"{baths_s} Bath" if baths_s else ""
        label = " / ".join(x for x in (bed_lbl, bath_lbl) if x) or "unit"
        rows.append(_row(
            unit_or_floorplan_label=label,
            beds=beds_s, baths=baths_s, sqft=sqft_s,
            base_rent=rent if rent != "" else "",
            price_basis="base" if rent != "" else "",
            availability=avail,
            price_status="listed" if rent != "" else "not_publicly_listed",
        ))
    return rows


EXTRACTORS["uptown_realty"] = uptown_realty


def fp_units_modal_v2(url, params):
    """Craft/Servd ``<floor-plan-units-modalv2 :units="[...]">`` pages.

    The listing page embeds the full unit inventory as HTML-escaped JSON.
    Weekly job collapses to one advertised row per floorPlanId (min rent,
    beds/baths/sqft, layout image). Prefer this HTTP parse over the old
    Entrata ProspectPortal when the marketing site is the public source.
    """
    import html as html_lib
    page = fetch(url)
    tag_m = re.search(r"<floor-plan-units-modalv2\b([^>]*)>", page, re.S | re.I)
    if not tag_m:
        return []
    attrs = tag_m.group(1)
    units_m = re.search(r':units="', attrs)
    if not units_m:
        return []
    start = units_m.end()
    i = start
    while i < len(attrs):
        if attrs[i] == '"' and not attrs[max(0, i - 6):i].endswith("&quot;"):
            break
        i += 1
    try:
        units = json.loads(html_lib.unescape(attrs[start:i]))
    except json.JSONDecodeError:
        return []
    if not isinstance(units, list):
        return []

    by_plan = {}
    for u in units:
        pid = u.get("floorPlanId") or u.get("floorPlanName") or u.get("floorPlanCode")
        if pid is None:
            continue
        by_plan.setdefault(pid, []).append(u)

    rows = []
    for _pid, us in by_plan.items():
        first = us[0]
        prices = [_num(x.get("unitPrice")) for x in us]
        prices = [p for p in prices if p != ""]
        sqfts = []
        for x in us:
            n = _num(x.get("unitInteriorSquareFeet"))
            if n != "":
                sqfts.append(n)
        if not sqfts:
            sqft = ""
        elif min(sqfts) == max(sqfts):
            sqft = int(min(sqfts)) if float(min(sqfts)).is_integer() else min(sqfts)
        else:
            lo, hi = min(sqfts), max(sqfts)
            lo = int(lo) if float(lo).is_integer() else lo
            hi = int(hi) if float(hi).is_integer() else hi
            sqft = f"{lo}-{hi}"
        rent = min(prices) if prices else ""
        n_avail = sum(1 for x in us if x.get("unitAvailable"))
        dates = sorted({x.get("unitAvailableDate") for x in us if x.get("unitAvailableDate")})
        specials = [x.get("unitSpecials") for x in us if x.get("unitSpecials")]
        conc = specials[0] if specials else ""
        ctype, cval = parse_concession(conc) if conc else ("", "")
        img = first.get("floorPlanImageFull") or first.get("floorPlanImage") or ""
        beds = first.get("unitBedrooms")
        if beds is None:
            beds = ""
        rows.append(_row(
            unit_or_floorplan_label=first.get("floorPlanName") or first.get("floorPlanCode") or "",
            beds=beds, baths=first.get("unitBathrooms") or "",
            sqft=sqft,
            base_rent=rent if rent != "" else "",
            price_basis="base" if rent != "" else "",
            concessions_raw=conc if isinstance(conc, str) else json.dumps(conc),
            concessions_type=ctype, concessions_value=cval,
            availability=" — ".join(x for x in [
                f"{len(us)} unit(s) in feed",
                f"{n_avail} marked available" if n_avail else "none marked available",
                f"dates {', '.join(dates[:3])}" if dates else "",
            ] if x),
            layout_image_url=img,
            price_status="listed" if rent != "" else "not_publicly_listed",
        ))
    rows.sort(key=lambda r: (r.get("beds") or "", r.get("unit_or_floorplan_label") or ""))
    return rows


EXTRACTORS["fp_units_modal_v2"] = fp_units_modal_v2


def webflow_product7(url, params):
    """Webflow Relume product7 floor-plan grid (24 Longview 2026 redesign).

    Server-rendered cards: layout image + name + beds/baths/sqft. Rent is not
    published on the page (availability/apply is a separate form). Prefer the
    CDN URL from the Webflow lightbox JSON over the relative img src.
    """
    html = fetch(url)
    rows = []
    for chunk in re.split(r'<div class="product7_item">', html)[1:]:
        name_m = re.search(
            r'product7_title-wrapper[\s\S]*?text-weight-bold[^>]*>\s*(?:<strong>)?([^<]+)',
            chunk)
        if not name_m:
            continue
        name = re.sub(r"\s+", " ", name_m.group(1)).strip()
        meta = re.search(
            r'(\d+)\s*Bed\s*/\s*([\d.]+)\s*Bath[\s\S]{0,80}?([\d,]+)\s*sq\.?\s*ft',
            chunk, re.I)
        beds = baths = sqft = ""
        if meta:
            beds, baths, sqft = meta.group(1), meta.group(2), meta.group(3).replace(",", "")
        img = ""
        jm = re.search(r'"url":\s*"(https://cdn\.prod\.website-files\.com/[^"]+)"', chunk)
        if jm:
            img = jm.group(1)
        else:
            sm = re.search(
                r'<img[^>]+(?:src|data-src)="([^"]+)"[^>]*class="product7_image"'
                r'|<img[^>]+class="product7_image"[^>]+(?:src|data-src)="([^"]+)"',
                chunk)
            if sm:
                img = _abs(url, sm.group(1) or sm.group(2))
        rent_m = re.search(r'\$\s*([\d,]{3,5})', chunk)
        rent = float(rent_m.group(1).replace(",", "")) if rent_m else ""
        rows.append(_row(
            unit_or_floorplan_label=name,
            beds=beds, baths=baths, sqft=sqft,
            base_rent=rent if rent != "" else "",
            price_basis="base" if rent != "" else "",
            availability=("See site" if rent != ""
                          else "plan advertised; no rate shown on site"),
            layout_image_url=img,
            price_status="listed" if rent != "" else "not_publicly_listed",
        ))
    return rows


EXTRACTORS["webflow_product7"] = webflow_product7


def webflow_cms_floorplans(url, params):
    """Webflow CMS floor-plan collection.

    Shared card family, two list-item class names seen in the wild:
    - Sparq on Rio: ``collection-item-4``; CSS-background layout image; rent
      is typically the visible "Call for Pricing" block.
    - GrandMarc Austin: ``floorplan-collection-item``; ``<img class=floorplan-image>``;
      published rent is ``.price.bold``. A hidden "Call for Pricing" sibling
      (``w-condition-invisible``) and a strikethrough ``.slashed`` price sit
      beside it — the bold figure is the advertised plan rent.

    Bed/bath/sqft are split across ``floorplan-details`` or ``promo-details``
    divs. Availability badges and promo blurbs use ``w-condition-invisible``
    when inactive.
    """
    html = fetch(url)
    rows = []
    splitter = re.compile(
        r'<div role="listitem" class="(?:collection-item-4|floorplan-collection-item) w-dyn-item">'
    )
    for chunk in splitter.split(html)[1:]:
        if "floorplan-linkblock" not in chunk[:4000] and "floorplan-name" not in chunk[:5000]:
            continue
        cut = chunk.find('class="section-features"')
        block = chunk[:cut] if 0 < cut < 12000 else chunk[:12000]
        name_m = re.search(r'data-name="([^"]+)"', block)
        if not name_m:
            name_m = re.search(r'class="floorplan-name">([^<]+)', block)
        if not name_m:
            continue
        name = re.sub(r"\s+", " ", name_m.group(1)).strip()
        details = re.findall(
            r'class="(?:floorplan-details|promo-details)">([^<]*)', block)
        beds = baths = sqft = ""
        joined = " ".join(d.strip() for d in details if d.strip())
        meta = re.search(
            r"(\d+)\s*Bed\s*/\s*([\d.]+)\s*Bath\s*/\s*([\d,]+)\s*Sqft",
            joined, re.I)
        if meta:
            beds, baths, sqft = meta.group(1), meta.group(2), meta.group(3).replace(",", "")
        else:
            if re.search(r"\bstudio\b", joined, re.I):
                beds = "0"
            beds_m = re.search(r'data-beds="([^"]+)"', block)
            if beds == "" and beds_m:
                beds = beds_m.group(1)
            bam = re.search(r"([\d.]+)\s*Bath", joined, re.I)
            sqm = re.search(r"([\d,]+)\s*Sqft", joined, re.I)
            if bam and baths == "":
                baths = bam.group(1)
            if sqm and sqft == "":
                sqft = sqm.group(1).replace(",", "")
        img = ""
        im = re.search(r"background-image:url\(&quot;([^&]+)&quot;\)", block)
        if im:
            img = im.group(1)
        if not img:
            for tag in re.findall(r"<img\b[^>]*>", block):
                if "w-dyn-bind-empty" in tag or "floorplan-image" not in tag:
                    continue
                sm = re.search(r'\ssrc="([^"]+)"', tag)
                if sm and sm.group(1) and not sm.group(1).startswith("data:"):
                    img = _abs(url, sm.group(1))
                    break
        avail_bits = []
        for cls, text in re.findall(r'<div class="filter-text([^"]*)">([\s\S]*?)</div>', block):
            if "w-condition-invisible" in cls:
                continue
            t = re.sub(r"<[^>]+>", " ", text)
            t = re.sub(r"\s+", " ", t.replace("\xa0", " ")).strip()
            if t:
                avail_bits.append(t)
        for cls, text in re.findall(
                r'<div class="([^"]*\bavailability\b[^"]*)">([^<]*)', block):
            if "w-condition-invisible" in cls or "w-dyn-bind-empty" in cls:
                continue
            t = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
            if t and not re.search(r"call for pricing", t, re.I):
                avail_bits.append(t)
        rent = ""
        slashed = ""
        # Only trust a $ amount inside a visible .price-range block, not nav/phone copy.
        # Strikethrough (.slashed) is the pre-promo figure; .price.bold is the advertised rent.
        for cls, inner in re.findall(
                r'<div class="(price-range[^"]*)">([\s\S]*?)</div>(?=\s*(?:<div class="price-range|</a>))',
                block):
            if "w-condition-invisible" in cls:
                continue
            text = re.sub(r"<[^>]+>", " ", inner)
            text = re.sub(r"\s+", " ", text).strip()
            rm = re.search(r"\$\s*([\d,]{3,6})", text)
            if not rm:
                continue
            val = float(rm.group(1).replace(",", ""))
            if "slashed" in cls:
                slashed = val
                continue
            if "bold" in inner:
                rent = val
                break
            if rent == "":
                rent = val
        specials = []
        for cls, text in re.findall(
                r'<div class="(specials-container[^"]*)">\s*<p class="specials-text[^"]*">([^<]*)',
                block):
            if "w-condition-invisible" in cls:
                continue
            t = re.sub(r"\s+", " ", text).strip()
            if t and "w-dyn-bind-empty" not in cls:
                specials.append(t)
        raw_bits = list(specials)
        if slashed != "" and rent != "" and slashed > rent:
            shown = int(slashed) if float(slashed).is_integer() else slashed
            raw_bits.append(f"was ${shown:,}" if isinstance(shown, int) else f"was ${shown}")
        concessions_raw = "; ".join(raw_bits)
        if slashed != "" and rent != "" and slashed > rent:
            diff = slashed - rent
            concessions_type = "flat_discount"
            concessions_value = str(int(diff) if float(diff).is_integer() else diff)
        elif concessions_raw:
            concessions_type, concessions_value = parse_concession(concessions_raw)
        else:
            concessions_type, concessions_value = "", ""
        if avail_bits:
            avail = " / ".join(avail_bits)
        elif rent != "":
            avail = "See site"
        else:
            avail = "plan advertised; no rate shown on site"
        rows.append(_row(
            unit_or_floorplan_label=name,
            beds=beds, baths=baths, sqft=sqft,
            base_rent=rent if rent != "" else "",
            price_basis="base" if rent != "" else "",
            concessions_raw=concessions_raw,
            concessions_type=concessions_type,
            concessions_value=concessions_value,
            availability=avail,
            layout_image_url=img,
            price_status="listed" if rent != "" else "not_publicly_listed",
        ))
    return rows


EXTRACTORS["webflow_cms_floorplans"] = webflow_cms_floorplans
