#!/usr/bin/env python3
"""Copy FML_Data's Austin extractors into this repo and re-apply Rebuild's browser options.

The shared package is reference/legacy_ut_scraper/extractors/ plus the sibling
run.py and properties_config.json. http_extractors.py, run.py and
properties_config.json are byte-copies of FML_Data main. dom_extract.js is the
FML_Data file plus an additive launch/wait block that runs only when
DOM_PROFILE, DOM_HEADED or DOM_CHALLENGE_WAIT_S is set. With those unset, the
browser launch and the challenge waits are the FML_Data statements.

  python3 scripts/sync_fml_extractors.py [/path/to/FML_Data]
  python3 scripts/sync_fml_extractors.py --check [/path/to/FML_Data]

Default root: $FML_DATA_ROOT or /agent/repos/FML_Data.
Never writes to FML_Data.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "reference" / "legacy_ut_scraper"
EXT = PKG / "extractors"
STAMP = PKG / "SYNCED_FROM.json"

FILES = {
    "extractors/http_extractors.py": EXT / "http_extractors.py",
    "extractors/dom_extract.js": EXT / "dom_extract.js",
    "run.py": PKG / "run.py",
    "properties_config.json": PKG / "properties_config.json",
}


def fml_root(argv):
    args = [a for a in argv if not a.startswith("--")]
    if args:
        return Path(args[0]).resolve()
    import os
    env = os.environ.get("FML_DATA_ROOT")
    if env:
        return Path(env).resolve()
    return Path("/agent/repos/FML_Data")


def scraper_dir(root: Path) -> Path:
    return root / "austin_leases_units" / "scraper"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_sha(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def apply_dom_overlay_simple(src: str) -> str:
    """Gate Rebuild's persistent profile, headed window and challenge wait. Defaults off."""
    old_launch = (
        "  const browser = await chromium.launch();\n"
        "  const ctx = await browser.newContext({ userAgent: UA, viewport: { width: 1440, height: 900 } });"
    )
    new_launch = """  // Rebuild addition. Default off: with DOM_PROFILE, DOM_HEADED and DOM_CHALLENGE_WAIT_S
  // unset, launch and context match FML_Data (headless chromium.launch + newContext).
  const domOptsOn = !!(process.env.DOM_PROFILE || process.env.DOM_HEADED === '1' || process.env.DOM_CHALLENGE_WAIT_S);
  const opts = { userAgent: UA, viewport: { width: 1440, height: 900 } };
  let browser, ctx;
  if (!domOptsOn) {
    browser = await chromium.launch();
    ctx = await browser.newContext(opts);
  } else {
    const prof = process.env.DOM_PROFILE;
    const headed = process.env.DOM_HEADED === '1';
    browser = prof
      ? await chromium.launchPersistentContext(prof, { headless: !headed, ...opts })
      : await chromium.launch({ headless: !headed });
    ctx = prof ? browser : await browser.newContext(opts);
  }"""
    if old_launch not in src:
        raise SystemExit("dom_extract.js launch block not found; FML_Data changed and the overlay must be updated")
    src = src.replace(old_launch, new_launch, 1)

    gated_8000 = """          if (process.env.DOM_PROFILE || process.env.DOM_HEADED === '1' || process.env.DOM_CHALLENGE_WAIT_S) {
            const ws = parseInt(process.env.DOM_CHALLENGE_WAIT_S || (process.env.DOM_HEADED === '1' ? '170' : '8'), 10);
            for (let w = 0; w < ws; w += 2) {
              await page.waitForTimeout(2000);
              if (!/just a moment|attention required|access denied/i.test(await page.title())) break;
            }
          } else {
            await page.waitForTimeout(8000);
          }"""
    gated_12000 = """      if (process.env.DOM_PROFILE || process.env.DOM_HEADED === '1' || process.env.DOM_CHALLENGE_WAIT_S) {
        const ws = parseInt(process.env.DOM_CHALLENGE_WAIT_S || (process.env.DOM_HEADED === '1' ? '170' : '8'), 10);
        for (let w = 0; w < ws; w += 2) {
          await page.waitForTimeout(2000);
          if (!/just a moment|attention required|access denied/i.test(await page.title())) break;
        }
      } else {
        await page.waitForTimeout(12000);
      }"""
    needle8 = "          await page.waitForTimeout(8000);"
    if src.count(needle8) != 1:
        raise SystemExit(f"expected one 8000ms challenge wait, found {src.count(needle8)}")
    src = src.replace(needle8, gated_8000, 1)
    marker = "      // give the Cloudflare managed (non-interactive) check a chance to clear\n      await page.waitForTimeout(12000);"
    gated_marker = "      // give the Cloudflare managed (non-interactive) check a chance to clear\n" + gated_12000
    if marker not in src:
        raise SystemExit("main-page challenge wait not found")
    src = src.replace(marker, gated_marker, 1)
    return src


def load_sources(root: Path):
    base = scraper_dir(root)
    if not (base / "extractors" / "http_extractors.py").exists():
        raise SystemExit(f"FML_Data scraper not found at {base}")
    out = {}
    for rel in FILES:
        out[rel] = (base / rel).read_bytes()
    return out


def expected_bytes(raw: dict) -> dict:
    out = dict(raw)
    text = raw["extractors/dom_extract.js"].decode("utf-8")
    out["extractors/dom_extract.js"] = apply_dom_overlay_simple(text).encode("utf-8")
    return out


def check(root: Path) -> int:
    raw = load_sources(root)
    want = expected_bytes(raw)
    bad = []
    for rel, dest in FILES.items():
        got = dest.read_bytes()
        if got != want[rel]:
            bad.append(f"{rel}: on disk {sha256(got)[:12]} expected {sha256(want[rel])[:12]}")
    if bad:
        print("extractor drift vs", root)
        print("\n".join(bad))
        return 1
    print(f"extractors match {root} @ {git_sha(root)}")
    return 0


def sync(root: Path) -> None:
    raw = load_sources(root)
    want = expected_bytes(raw)
    for rel, dest in FILES.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(want[rel])
    stamp = {
        "fml_data_root": str(root),
        "fml_data_commit": git_sha(root),
        "files": {rel: sha256(want[rel]) for rel in FILES},
        "dom_overlay": "default-off DOM_PROFILE / DOM_HEADED / DOM_CHALLENGE_WAIT_S",
        "note": "Byte-copies except dom_extract.js, which adds the gated browser options.",
    }
    STAMP.write_text(json.dumps(stamp, indent=2) + "\n")
    print(f"synced {len(FILES)} files from {git_sha(root)}")


def main():
    check_only = "--check" in sys.argv
    root = fml_root([a for a in sys.argv[1:] if a != "--check"])
    if check_only:
        sys.exit(check(root))
    sync(root)
    sys.exit(check(root))


if __name__ == "__main__":
    main()
