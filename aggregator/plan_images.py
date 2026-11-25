"""Floor-plan images for rows that an adapter returned without one (2026-11-24).

Why: text_plan_list, appfolio, headed rescues, university_rates, rentcafe ysi JSON and LLM reads give plan names and
prices but no layout image, though most sites show one per plan (A&M audit 11-24: 50 buildings on the site had plans
and no images; 44 of them had the images in the pages the crawler had already saved). Deterministic, no LLM.

Order per plan (stops at the first hit):
  1. schema.org FloorPlan JSON-LD: name / isPlanForApartment -> layoutImage (Brazos Oaks; Rank Math sites)
  2. an <img> whose own alt/title is the plan name ("Floor Plan A": Tower Park, Duda/Wix)
  3. DOM card walk: the deepest element whose text shows the plan name, climbed until an ancestor holds a plan-like
     image; stops when the ancestor shows another plan's name (left the card). Duplicate names need their sqft.
  4. alt text with beds/baths ("2 Bedroom, 2 Bathroom") unique on the page and to the plan (Razz unit lists)
  5. file name with beds-baths ("floorplan_whitecreek_4-2") - also used to DROP a pick that says other beds/baths
     (captions under images pair each plan with the next card's image: TAMU reslife)
  6. one plan + exactly one image the page calls a floor plan
  7. follow_plan_pages(): the card links to a page per plan (/floorplans/magnolia/) -> that page's plan image
Images most plans share are page chrome and are dropped. Photos (cover/exterior/interior/gallery) are never picked
unless the file or alt says floor plan. Check new sites by eye before trusting them (contact sheet): the 11-24 run
rejected exterior covers, room photos on "Premium" cards, and a "coming soon" placeholder."""
import re, html as _h
from collections import Counter
from urllib.parse import urljoin
import lxml.html

BAD_IMG = re.compile(r"logo|icon|sprite|favicon|avatar|badge|placeholder|spinner|loader|pixel|tracking|facebook|"
                     r"equal-?housing|\beho\b|wheelchair|arrow|chevron|close|search|boxTAM|svgrepo|exclamation|coming[-_ ]?soon|\.svg(\?|$)|\.gif(\?|$)|^data:", re.I)
PLANISH = re.compile(r"floor|plan|\bfp\b|[-_]fp[-_]|layout|\d\s?x\s?\d|\dbed|\dbr\b|\dbd\b|bedroom", re.I)
STRONG = re.compile(r"floor ?plan|floorplan|[-_ ]fp[-_ .]|layout", re.I)
PHOTO = re.compile(r"cover|exterior|photo|hero|banner|aerial|gallery|lifestyle", re.I)
NOT_PLAN = re.compile(r"interior|kitchen|bath(room)?[-_ ]|bedroom[-_ ]photo|living[-_ ]room|pool|gym|fitness|exterior|"
                      r"amenit|clubhouse|aerial|lifestyle|resident|model[-_]|_model|photo|gallery|hero|banner|cover|"
                      r"community|lobby|courtyard", re.I)


def _src(el, base):
    best, bw = "", -1
    for k in ("srcset", "data-srcset", "data-lazy-srcset"):
        for part in re.split(r",\s+", (el.get(k) or "").strip()):   # entries are ", "-separated; URLs may hold commas (Wix)
            bits = part.strip().split()
            if bits:
                w = int(re.sub(r"\D", "", bits[1]) or 0) if len(bits) > 1 and bits[1].endswith("w") else 0
                if w > bw:
                    best, bw = bits[0], w
    s = best or el.get("data-src") or el.get("data-lazy-src") or el.get("data-original") or el.get("src") or ""
    pic = el.getparent()
    if not s and el.tag == "img" and pic is not None and pic.tag in ("picture", "div", "span"):
        s = pic.get("data-iesrc") or pic.get("data-src") or ""
        if not s:
            for src in pic.findall("source"):
                ss = re.split(r",\s+", (src.get("srcset") or src.get("data-srcset") or "").strip())[-1].strip().split(" ")[0]
                if ss:
                    s = ss
        best = best or s
    if el.tag != "img":   # element with an inline background image
        m = re.search(r"url\(\s*['\"]?([^'\")]+)", el.get("style") or "")
        s = m.group(1) if m else ""
    s = s.strip()
    if not s or s.startswith("data:"):
        return ""
    s = urljoin(base or "", s)
    if not best:
        s = re.sub(r"-\d{2,4}x\d{2,4}(\.(?:png|jpe?g|webp))$", r"\1", s, flags=re.I)   # WP thumbnail -> original
    s = re.sub(r"(/uc-image/[0-9a-f-]{36}/).*$", r"\1", s)
    s = re.sub(r"(static\.wixstatic\.com/media/[^/]+)/v1/.*$", r"\1", s)          # Wix rendition -> original                         # Uploadcare preview -> original
    return s


def _imgs(node, base):
    out = []
    for el in node.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag == "img" or (el.get("style") and "url(" in (el.get("style") or "")):
            s = _src(el, base)
            if not s:
                continue
            fname = s.split("?")[0].rsplit("/", 1)[-1]
            if BAD_IMG.search(fname) or BAD_IMG.search(el.get("class") or ""):
                continue
            w, h = el.get("width") or "", el.get("height") or ""
            if (w.isdigit() and int(w) < 80) or (h.isdigit() and int(h) < 80):
                continue
            out.append((s, (el.get("alt") or "") + " " + (el.get("title") or "")))
    return out


def _label_rx(label):
    words = re.findall(r"[A-Za-z0-9]+", re.sub(r"\[Per Installment/Person\]|\(.*?\)", "", label or ""))
    if not words:
        return None
    return re.compile(r"(?<![A-Za-z0-9])" + r"[^A-Za-z0-9]{0,12}".join(map(re.escape, words)) + r"(?![A-Za-z0-9])", re.I)


def _text(el):
    return re.sub(r"\s+", " ", el.text_content() or "")


WORDN = {"studio": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _bedbath(alt):
    m = re.search(r"(studio|\d|one|two|three|four|five|six)\s*(?:bed(?:room)?s?|br|bd)\b[\s,/|&-]*(?:(\d(?:\.\d)?|one|two|three|four)\s*(?:bath(?:room)?s?|ba)\b)?", alt or "", re.I)
    if not m:
        return None
    w = lambda x: WORDN.get(x.lower(), x) if x else None
    b = w(m.group(1)); ba = w(m.group(2))
    return (float(b), float(ba) if ba is not None else None)


def jsonld_plan_images(html):
    """schema.org FloorPlan blocks (Rank Math / Yoast 'FloorPlan' schema, Brazos Oaks): name or isPlanForApartment +
    layoutImage. -> [(name, image_url)]"""
    import json as _j
    out = []

    def walk(x):
        if isinstance(x, dict):
            t = x.get("@type")
            t = t if isinstance(t, list) else [t]
            if "FloorPlan" in t:
                img = x.get("layoutImage") or x.get("image")
                img = img[0] if isinstance(img, list) and img else img
                img = img.get("url") or img.get("contentUrl") or img.get("@id") if isinstance(img, dict) else img
                nm = x.get("name") or x.get("isPlanForApartment")
                nm = nm.get("name") if isinstance(nm, dict) else nm
                if img and nm and isinstance(nm, str):
                    out.append((nm, img))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for m in re.finditer(r"<script[^>]*application/ld\+json[^>]*>([\s\S]*?)</script>", html or "", re.I):
        try:
            walk(_j.loads(m.group(1)))
        except Exception:
            pass
    return out


FN_BB = re.compile(r"(?:^|(?<=[_\s-]))(\d)(?:x|-)(\d(?:\.5)?)(?=[-_.\s]|$)", re.I)


def _fname_bb(url):
    """beds/baths written in a plan image's file name: floorplan_whitecreek_4-2, Tower_2x2, 1x1LG -> (4, 2)"""
    f = (url or "").split("?")[0].rsplit("/", 1)[-1]
    f = re.sub(r"\d{3,4}x\d{3,4}", "", f)                 # image sizes
    m = FN_BB.search(f)
    return (float(m.group(1)), float(m.group(2))) if m and STRONG.search(f + " floorplan") else None


def find_images(labels, pages, max_levels=14, hints=None, bedbath=None, weak=None):
    """weak: optional set; gets the indexes whose image was only the card's image (not named/alt'd as a plan)."""
    """labels: plan names. pages: [(html, base_url)]. -> {index: image_url}.
    For each element whose own text shows a plan name, climb its ancestors to the first one that holds an image.
    Stop (no answer) if that ancestor also shows another plan's name and no image there names this plan
    (= we left the plan's card). Images that most plans share are page chrome, not plans."""
    rxs = [_label_rx(l) for l in labels]
    pat = Counter(r.pattern for r in rxs if r)
    dup = [bool(r) and pat[r.pattern] > 1 for r in rxs]
    out = {}
    for html, base in pages:
        if not html or len(out) == len(labels):
            continue
        for nm, img in jsonld_plan_images(html):     # machine-readable plan -> image first
            for i, rx in enumerate(rxs):
                if i not in out and rx and rx.fullmatch(nm.strip()) and not dup[i]:
                    out[i] = urljoin(base or "", img)
        try:
            root = lxml.html.fromstring(html)
        except Exception:
            continue
        for bad in root.xpath("//script|//style|//header|//footer|//nav"):
            bad.drop_tree()
        alts = _imgs(root, base)
        for i, rx in enumerate(rxs):        # an image whose own alt/title is the plan name ("Floor Plan A")
            if i in out or not rx or dup[i]:
                continue
            hit = [s for s, alt in alts if rx.search(alt) and len(alt.strip()) <= 2 * len(labels[i]) + 30
                   and not any(o.search(alt) for j, o in enumerate(rxs) if o and j != i and o.pattern != rx.pattern and len(o.pattern) > len(rx.pattern))]
            if hit:
                out[i] = hit[0]
        for i, rx in enumerate(rxs):
            if i in out or not rx:
                continue
            others = [r for j, r in enumerate(rxs) if j != i and r and r.pattern != rx.pattern]
            for el in root.iter():
                if not isinstance(el.tag, str) or el.tag in ("html", "body"):
                    continue
                tc = _text(el)
                if len(tc) > 250 or not rx.search(tc) or any(isinstance(c.tag, str) and rx.search(_text(c)) for c in el):
                    continue                    # deepest element whose whole text shows the name
                node, found, fallback = el, None, None
                for _ in range(max_levels):
                    node = node.getparent()
                    if node is None or node.tag in ("body", "html"):
                        break
                    t_wo = rx.sub(" ", _text(node))
                    crossed = any(o.search(t_wo) and not o.search(rx.pattern) for o in others) or (
                        dup[i] and hints and any(hints[j] and j != i and set(hints[j]) != set(hints[i] or []) and rxs[j] is not None and rxs[j].pattern == rx.pattern
                                                 and any(re.search(r"(?<!\d)" + re.escape(h) + r"(?!\d)", _text(node)) for h in hints[j])
                                                 for j in range(len(labels))))
                    ims = _imgs(node, base)
                    named = [s for s, alt in ims if (rx.search(alt) or rx.search(re.sub(r"[-_+]|%20", " ", s.rsplit("/", 1)[-1])))
                             and (STRONG.search(s.rsplit("/", 1)[-1] + " " + alt) or not PHOTO.search(s.rsplit("/", 1)[-1] + " " + alt))]
                    if named:
                        found = named[0]; break
                    if crossed:
                        break                       # left this plan's card
                    if dup[i] and hints and hints[i] and not any(re.search(r"(?<!\d)" + re.escape(h) + r"(?!\d)", _text(node)) for h in hints[i]):
                        continue                    # same name as another plan: its card must also show this plan's sqft
                    cand = [s for s, alt in ims if STRONG.search(s.rsplit("/", 1)[-1] + " " + alt) or not NOT_PLAN.search(s.rsplit("/", 1)[-1] + " " + alt)]
                    planish = [s for s, alt in ims if s in cand and PLANISH.search(s.rsplit("/", 1)[-1] + " " + alt)]
                    if planish:
                        found = planish[0]; break
                    if cand and not fallback:
                        fallback = cand[0]
                if not found and fallback and weak is not None:
                    weak.add(i)
                found = found or fallback
                if found:
                    out[i] = found
                    break
        # last: an image whose alt states beds/baths ("2 Bedroom, 2 Bathroom") that no other image shares, for the one
        # unmatched plan with those beds/baths (Razz/RealPage unit lists label plans by unit number only)
        if bedbath:
            imgs_bb = {}
            for s_, alt in alts:
                bb = _bedbath(alt)
                if bb and s_ not in out.values():
                    imgs_bb.setdefault(bb, set()).add(s_)
            for i in range(len(labels)):
                if i in out or not bedbath[i] or bedbath[i][0] is None:
                    continue
                key = (float(bedbath[i][0]), float(bedbath[i][1]) if bedbath[i][1] is not None else None)
                same = [j for j in range(len(labels)) if j not in out and bedbath[j] and bedbath[j][0] == bedbath[i][0] and bedbath[j][1] == bedbath[i][1]]
                hit = imgs_bb.get(key) or (imgs_bb.get((key[0], None)) if key[1] is not None else None)
                if hit and len(hit) == 1 and len(same) == 1:
                    out[i] = next(iter(hit))
    # a picked image whose file name says other beds/baths than the plan is a mis-pairing (captions under images)
    if bedbath:
        for i in list(out):
            fb = _fname_bb(out[i])
            if fb and bedbath[i] and bedbath[i][0] is not None and bedbath[i][1] is not None and \
                    fb != (float(bedbath[i][0]), float(bedbath[i][1])):
                del out[i]
        allimgs = {s_ for html, base in pages for s_ in re.findall(r"(?:src|data-src)=[\"']([^\"']+)", html or "")}
        byfb = {}
        for s_ in allimgs:
            fb = _fname_bb(s_)
            if fb and re.search(r"floor|plan|fp", s_.rsplit("/", 1)[-1], re.I):
                byfb.setdefault(fb, set()).add(urljoin(pages[0][1] if pages else "", s_))
        for i in range(len(labels)):
            if i in out or not bedbath[i] or bedbath[i][0] is None or bedbath[i][1] is None:
                continue
            key = (float(bedbath[i][0]), float(bedbath[i][1]))
            same = [j for j in range(len(labels)) if j not in out and bedbath[j] and bedbath[j][0] == bedbath[i][0] and bedbath[j][1] == bedbath[i][1]]
            if len(byfb.get(key, ())) == 1 and len(same) == 1:
                out[i] = next(iter(byfb[key]))
    if len(labels) == 1 and 0 not in out:
        strong = set()
        for html, base in pages[:2]:
            try:
                r_ = lxml.html.fromstring(html)
            except Exception:
                continue
            strong |= {s_ for s_, alt in _imgs(r_, base) if re.search(r"floor ?plan", alt, re.I)}
        if len(strong) == 1:
            out[0] = next(iter(strong))              # one plan, one image the page calls a floor plan
    c = Counter(out.values())
    n = max(1, len(labels))
    return {i: u for i, u in out.items() if not (c[u] > 1 and c[u] >= max(3, n * 0.6))}


def follow_plan_pages(labels, pages, fetch, skip=()):
    """Plan cards that show a photo and link to a page per plan (Charleston Mills: /floorplans/magnolia/): open the
    link whose last path segment is the plan's name and take that page's first plan-like image. -> {index: url}"""
    out = {}
    links = {}
    for html, base in pages:
        for m in re.finditer(r"""<a[^>]+href=["']([^"'#]+)["']""", html or "", re.I):
            u = urljoin(base or "", _h.unescape(m.group(1)))
            seg = u.rstrip("/").rsplit("/", 1)[-1].lower()
            links.setdefault(seg, u)
    for i, l in enumerate(labels):
        if i in skip:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"\[Per Installment/Person\]|\(.*?\)", "", l or "").lower()).strip("-")
        u = links.get(slug)
        if not slug or not u:
            continue
        try:
            h = fetch(u)
        except Exception:
            continue
        root = lxml.html.fromstring(h)
        for bad in root.xpath("//script|//style|//header|//footer|//nav"):
            bad.drop_tree()
        ims = _imgs(root, u)
        strong = [s for s, alt in ims if STRONG.search(s.rsplit("/", 1)[-1] + " " + alt) or re.search(r"\b(1st|first)[-_ ]?floor", s, re.I)]
        if strong:
            out[i] = strong[0]
    return out


def attach_layout_images(rows, pages, fetch=None, overrides=None, verify=False):
    """Fill rows[i]["layout_image_url"] where empty. rows: converted unit rows (name, beds, baths, sqft).
    pages: [(html, page_url)] - the building's saved pages, floor-plans page first. fetch(url)->html enables step 7.
    overrides: {plan name: image url} from data/<campus>/plan_image_overrides.json (sites that print the plan name
    only inside the image, e.g. Richmond Ridge). Returns the number of rows that got an image."""
    want = [i for i, r in enumerate(rows) if not r.get("layout_image_url") and r.get("name")]
    if not want:
        return 0
    n = 0
    def _ov(r):
        ov = overrides or {}
        if isinstance(ov, dict):                       # {exact plan name: url}
            return ov.get(r["name"])
        for o in ov:                                   # [{"name_regex"?, "sqft"?, "beds"?, "image"}] - all given keys must match
            if o.get("name_regex") and not re.search(o["name_regex"], r["name"], re.I):
                continue
            if o.get("sqft") is not None and r.get("sqft") != o["sqft"]:
                continue
            if o.get("beds") is not None and r.get("beds") != o["beds"]:
                continue
            return o["image"]
    for i in want:
        u = _ov(rows[i])
        if u:
            rows[i]["layout_image_url"], rows[i]["layout_image_how"] = u, "hand-checked override"
            n += 1
    want = [i for i in want if not rows[i].get("layout_image_url")]
    if not want:
        return n
    labels = [rows[i]["name"] for i in want]
    sq = [rows[i].get("sqft") for i in want]
    hints = [[str(x), f"{x:,}"] if isinstance(x, (int, float)) and x else None for x in sq]
    bb = [(rows[i].get("beds"), rows[i].get("baths")) for i in want]
    weak = set()
    got = find_images(labels, pages, hints=hints, bedbath=bb, weak=weak)
    how = {j: ("card image, not named as a plan - check by eye" if j in weak else "plan card on the saved page") for j in got}
    if fetch and len(got) < len(want):
        more = follow_plan_pages(labels, pages, fetch, skip=set(got))
        got.update(more)
        how.update({j: "plan detail page" for j in more})
    for j, u in got.items():
        u = re.sub(r"^http://", "https://", u)
        if verify:
            g = image_gate(u)
            if g["verdict"] in ("not_image", "too_small", "error"):
                continue                                   # dead link, redirect to a page, icon
            u = g["final_url"]
            if g["verdict"] == "photo_like":
                alt = follow_plan_pages([labels[j]], pages, fetch).get(0) if fetch else None
                g2 = image_gate(alt) if alt else None
                if g2 and g2["verdict"] == "plan_like":
                    u, how[j] = g2["final_url"], "plan detail page (card showed a photo)"
                elif j in weak:
                    continue                               # card photo, not a plan (SOHO houses, London rooms)
                else:
                    how[j] = how[j] + "; border says photo - check by eye"
        rows[want[j]]["layout_image_url"] = u
        rows[want[j]]["layout_image_how"] = how[j]
        n += 1
    return n


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")      # a short UA gets 403 from several WordPress hosts (Charleston Mills)
PLAN_BORDER_MIN = 0.40                   # 11-24 sample: 273/273 accepted plans >= 0.43; 9/9 rejected photos <= 0.35


def image_gate(url, timeout=25):
    """No-LLM image check. Downloads the image (following redirects, https) and returns
    {"ok", "final_url", "content_type", "w", "h", "border_uniformity", "verdict"}.
    verdict: "plan_like" (border is one flat colour: white/black/transparent/brand colour - diagrams and 3D renders
    on a background), "photo_like" (border varies: sky, rooms, exteriors), "not_image", "too_small", "error".
    A placeholder on a flat colour ("image coming soon") still passes: names with coming-soon are filtered earlier."""
    import io, urllib.request
    from collections import Counter
    out = {"ok": False, "final_url": url, "verdict": "error"}
    try:
        r = urllib.request.urlopen(urllib.request.Request(re.sub(r"^http://", "https://", url),
                                   headers={"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*"}), timeout=timeout)
        data = r.read(40_000_000)          # some plan PNGs are 15+ MB (12 North)
        out.update(final_url=r.geturl(), content_type=r.headers.get("Content-Type", ""))
    except Exception as e:
        out["error"] = str(e)[:80]
        return out
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)); im.load()
    except Exception:
        out["verdict"] = "not_image"
        return out
    w, h = im.size
    out.update(w=w, h=h)
    if w < 200 or h < 150:
        out["verdict"] = "too_small"
        return out
    im = im.convert("RGBA"); px = im.load()
    pts = [(x, y) for x in range(0, w, max(1, w // 80)) for y in (0, h - 1)] + \
          [(x, y) for y in range(0, h, max(1, h // 80)) for x in (0, w - 1)]
    q = Counter((255, 255, 255) if px[p][3] < 20 else (px[p][0] // 24, px[p][1] // 24, px[p][2] // 24) for p in pts)
    u = q.most_common(1)[0][1] / len(pts)
    out.update(ok=True, border_uniformity=round(u, 2), verdict="plan_like" if u >= PLAN_BORDER_MIN else "photo_like")
    return out
