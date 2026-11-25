"""Hand-solve pass for Cloudflare-blocked buildings (the legacy "headed rescue", made repeatable).

Opens each blocked building's browser adapter in a VISIBLE window, one at a time, and waits up to --wait seconds for
a person to clear the challenge. Rows that come back are saved to data/<campus>/rescues/<objectID>.json, which
enrich_listings.py uses when the live adapters are blocked. The clearance cookie stays in the profile
(~/.fml_dom_profile_manual), so later unattended runs of the same site often pass without a challenge.

  python3 solve_blocked.py <campus> [--only <objectID>] [--wait 300]
Blocked buildings = listings.json coverage_flags containing blocked_bot_wall_needs_headed_browser.
"""
import argparse, json, os, subprocess, time
from common import campus
import listing_adapters as LA


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campus"); ap.add_argument("--only"); ap.add_argument("--wait", type=int, default=300)
    a = ap.parse_args()
    cfg = campus(a.campus)
    rdir = cfg["dir"] / "rescues"; rdir.mkdir(exist_ok=True)
    npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    for lp in sorted((cfg["dir"] / "raw").glob("*/listings.json")):
        l = json.loads(lp.read_text())
        slug = lp.parent.name
        if a.only and slug != a.only:
            continue
        if not a.only and not any("blocked_bot_wall" in f for f in l.get("coverage_flags", [])):
            continue
        cands = [t for t in l.get("adapters_tried", []) if t.get("status", "").startswith("blocked_bot_wall")]
        meta = json.loads((lp.parent / "meta.json").read_text())
        b = {"canonical_name": slug, "aliases": [], "building_type": "apartment"}
        # re-detect to get the blocked adapter's URL + params
        found = [c for c in LA.detect(b | {"canonical_name": meta.get("slug", slug)}, meta,
                                      {k: (lp.parent / f"{k}.html").read_text(errors="replace")
                                       for k in ("floorplans", "home") if (lp.parent / f"{k}.html").exists()}, cfg)
                 if c["backend"] in LA.DOM_BACKENDS and (not cands or c["backend"] in {t["backend"] for t in cands})]
        for c in found[:1]:
            print(f"{slug}: opening {c['url']} - solve the challenge in the window", flush=True)
            out = subprocess.run(["node", str(LA.DOM_JS), c["backend"], c["url"], json.dumps(c["params"])],
                                 capture_output=True, text=True, timeout=a.wait + 120,
                                 env={**os.environ, "NODE_PATH": npm_root, "DOM_HEADED": "1",
                                      "DOM_PROFILE": os.path.expanduser("~/.fml_dom_profile_manual"),
                                      "DOM_CHALLENGE_WAIT_S": str(a.wait)}).stdout
            j = json.loads(out.strip().splitlines()[-1])
            print(f"  {j['status']} rows={len(j['rows'])}")
            if j["rows"]:
                (rdir / f"{slug}.json").write_text(json.dumps({"source_url": c["url"], "backend": c["backend"],
                    "captured_at": time.strftime("%Y-%m-%d"), "how": "solve_blocked.py visible browser", "rows": j["rows"]}, indent=1))


if __name__ == "__main__":
    main()
