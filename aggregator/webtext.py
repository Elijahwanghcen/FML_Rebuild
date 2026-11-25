"""Fetch a page (plain HTTP first, Playwright render fallback) and reduce it to LLM-readable text."""
import hashlib, html, os, re, subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse
from common import http_get, ROOT

HERE = Path(__file__).resolve().parent
BLOCK = re.compile(r"just a moment|cf-challenge|attention required|access denied|captcha|are you a human", re.I)


def fetch_html(url, cache_dir, render="auto"):
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    h = None
    if render != "always":
        try:
            h = http_get(url, cache_dir, timeout=25)
        except Exception:
            h = None
    if render == "never":
        return h
    if h is None or len(to_text(h, url)) < 400 or BLOCK.search(h[:3000]):
        out = cache_dir / (hashlib.sha1(("pw" + url).encode()).hexdigest()[:20] + ".html")
        if not out.exists():
            npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
            subprocess.run(["node", str(HERE / "render.js"), url, str(out)], capture_output=True, timeout=120,
                           env={**os.environ, "NODE_PATH": npm_root})
        if out.exists():
            h = out.read_text(errors="replace")
    return h


def to_text(h, base="", keep_links=True, limit=60000):
    h = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", h or "")
    if keep_links:
        def a(m):
            href = re.search(r'href=["\']([^"\']+)', m.group(1))
            t = re.sub(r"<[^>]+>", " ", m.group(2)).strip()
            if not href or href.group(1).startswith(("#", "javascript", "mailto", "tel")):
                return t
            return f"[{t}]({urljoin(base, href.group(1))})"
        h = re.sub(r"(?is)<a\b([^>]*)>(.*?)</a>", a, h)
    h = re.sub(r'(?is)<img\b[^>]*alt=["\']([^"\']{4,})["\'][^>]*>', r" (img: \1) ", h)
    h = re.sub(r"(?i)<(br|/p|/div|/li|/h\d|/tr|/section)\b[^>]*>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()[:limit]


def site_hosts(h, base):
    """Hosts that count as 'this site': the URL's own host plus the page's canonical / og:url host. A property
    whose Google URL redirects to a sister brand (retreatcollegestation.com -> redpoint-collegestation.com) links
    to its pages on the other host; same-host-only link following found no floor-plans page there."""
    out = {urlparse(base).netloc.replace("www.", "")}
    for m in re.finditer(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)|<meta[^>]+property=["\']og:url["\'][^>]*content=["\']([^"\']+)', h or "", re.I):
        u = m.group(1) or m.group(2)
        if u.startswith("http"):
            out.add(urlparse(u).netloc.replace("www.", ""))
    return out


def links(h, base, hosts=None):
    out = []
    hosts = hosts or site_hosts(h, base)
    for m in re.finditer(r'(?is)<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', h or ""):
        u = urljoin(base, m.group(1))
        if urlparse(u).netloc.replace("www.", "") in hosts:
            out.append((u.split("#")[0], re.sub(r"<[^>]+>", " ", m.group(2)).strip()))
    return out
