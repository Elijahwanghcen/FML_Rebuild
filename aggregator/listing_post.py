"""FML_Data row post-processing for locked sources.

Mirrors austin_leases_units/scraper/run.py: clean_labels dedupe, the failure stub,
and the decision to keep explicit unlisted placeholders such as
`(no public pricing on site)`. Those placeholders start with "(" and Rebuild's
discovery filter used to drop them.
"""
import re

LABEL_TAIL_RE = re.compile(
    r"\s+(?:Studio,|\d+\s*Beds?,|\d+\s*Bed\b|Call for Pricing|\d+\s*Space Option).*$",
    re.I,
)

# Production refresh must not re-parse a build machine's saved HTML.
SAVED_HTML_BACKENDS = {"text_plan_list"}


def clean_dedupe_rows(rows):
    """params.clean_labels: Entrata white-label pages render each plan in
    several overlapping layouts. Cut the glued card text and merge copies."""
    merged, order = {}, []
    for r in rows:
        raw = r.get("unit_or_floorplan_label") or ""
        label = LABEL_TAIL_RE.sub("", raw).strip() or raw
        m_b = re.search(r"(\d+)\s*Beds?\b", raw, re.I)
        m_ba = re.search(r"(\d+(?:\.\d+)?)\s*Baths?\b", raw, re.I)
        beds = r.get("beds")
        if beds in (None, ""):
            beds = 0 if re.search(r"\bStudio\b", raw, re.I) else (m_b.group(1) if m_b else "")
        baths = r.get("baths")
        if baths in (None, "") and m_ba:
            baths = m_ba.group(1)
        new = dict(r, unit_or_floorplan_label=label, beds=beds, baths=baths)
        key = label.casefold()
        if key not in merged:
            merged[key] = new
            order.append(key)
            continue
        cur = merged[key]
        for k, v in new.items():
            if cur.get(k) in (None, "") and v not in (None, ""):
                cur[k] = v
    return [merged[k] for k in order]


def saved_html_banned(prop):
    """True when a production run would be reading a frozen HTML snapshot."""
    if prop.get("backend") in SAVED_HTML_BACKENDS:
        return True
    params = prop.get("params") or {}
    return bool(params.get("html_files"))


def is_explicit_placeholder(row):
    label = (row.get("unit_or_floorplan_label") or "").strip()
    return label.startswith("(") and row.get("price_status") == "not_publicly_listed"


def keep_row(row):
    """Discovery filter: drop blank labels. Keep explicit unlisted placeholders."""
    label = (row.get("unit_or_floorplan_label") or "").strip()
    if not label:
        return False
    if label.startswith("(") and not is_explicit_placeholder(row):
        return False
    return True


def failure_stub(status):
    return dict(
        unit_or_floorplan_label="(extraction failed)",
        beds="", baths="", sqft="", base_rent="",
        total_price_with_mandatory_fees="", price_basis="",
        concessions_raw="", concessions_type="", concessions_value="",
        availability=f"extractor status: {status}",
        layout_image_url="", price_image_url="", concessions_image_url="",
        price_status="not_publicly_listed",
    )


def apply_row_policy(rows, params, status="ok"):
    """clean_labels, then the same failure stub run.py writes."""
    params = params or {}
    if rows and params.get("clean_labels"):
        rows = clean_dedupe_rows(rows)
    if status != "ok" or not rows:
        return [failure_stub(status if status != "ok" else "no rows")], False
    return rows, True
