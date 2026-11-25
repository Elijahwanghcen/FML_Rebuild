"""Turn pages saved from the user's Chrome (recv_pages.py) into rescue files, using the SAME parsers as the live run.

  python3 rescue_from_page.py <campus> <slug> <backend> [source_url]

Reads data/<campus>/chrome_pages/<slug>.html, runs the backend on it (browser parsers via file://, HTTP parsers on the
text), writes data/<campus>/rescues/<slug>.json. enrich_listings.py uses a rescue only when the live adapters return
nothing. A rescue is a snapshot: re-collect it when prices go stale (refresh_<date>.md lists failed buildings).
"""
import json, os, re, subprocess, sys, time
from common import campus
import listing_adapters as LA


def main(slug_campus, slug, backend, source_url=None):
    cfg = campus(slug_campus)
    page = cfg["dir"] / "chrome_pages" / f"{slug}.html"
    h = page.read_text(errors="replace")
    src = source_url or (re.search(r'<base href="([^"]+)"', h) or [None, ""])[1]
    if backend in LA.DOM_BACKENDS:
        npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        out = subprocess.run(["node", str(LA.DOM_JS), backend, f"file://{page}", "{}"], capture_output=True, text=True,
                             timeout=120, env={**os.environ, "NODE_PATH": npm_root}).stdout
        j = json.loads(out.strip().splitlines()[-1])
        rows, status = j["rows"], j["status"]
    else:
        rows, status = LA.HX.EXTRACTORS[backend](src, {"html_files": [str(page)]}), "ok"
    rd = cfg["dir"] / "rescues"; rd.mkdir(exist_ok=True)
    if rows:
        (rd / f"{slug}.json").write_text(json.dumps({"source_url": src, "backend": backend,
                                                     "captured_at": time.strftime("%Y-%m-%d"),
                                                     "how": "Claude in Chrome page save + " + backend, "rows": rows}, indent=1))
    print(f"{slug}: {status} rows={len(rows)} priced={sum(1 for r in rows if r.get('base_rent') not in ('', None))}")


if __name__ == "__main__":
    main(*sys.argv[1:])
