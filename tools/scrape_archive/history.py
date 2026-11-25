"""Backfill a campus master from the dated scrapes already in FML_Data.

For each date, a CSV that contains at least one real listing wins. A date
whose CSV is missing or is only an extraction-failed stub (2026-08-06 is
one failure row; the scrape itself is the JSON) uses the JSON snapshot.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from tools.scrape_archive.archive import ingest
from tools.scrape_archive.normalize import classify, read_rows
from tools.scrape_archive.schema import CAMPUSES, DATE_RE, resolve_campus

_NAME_TOKENS = ("advertised_prices", "units", "listings")
_SKIP_PARTS = {"algolia_backups", "node_modules", ".git", "snapshots"}


def _real_count(path: Path) -> int:
    rows = read_rows(path)
    records, _failures = classify(rows)
    return sum(1 for record in records if not record.get("explicit_empty"))


def _is_history_file(path: Path) -> bool:
    if path.suffix.lower() not in {".csv", ".json"}:
        return False
    if any(part in _SKIP_PARTS for part in path.parts):
        return False
    lowered = path.name.lower()
    if not DATE_RE.search(lowered):
        return False
    return any(token in lowered for token in _NAME_TOKENS)


def _all_tokens() -> list[str]:
    tokens = []
    for meta in CAMPUSES.values():
        tokens.extend(meta.get("path_tokens") or [])
    return tokens


def discover(root: str | Path, campus: str) -> list[dict]:
    """Return ``[{date, path, reason, real_rows}]`` in chronological order."""
    slug, meta = resolve_campus(campus)
    root_path = Path(root).resolve()
    if not root_path.exists():
        raise FileNotFoundError(root_path)
    tokens = [token.lower() for token in (meta.get("path_tokens") or [slug])]
    known = [token.lower() for token in _all_tokens()]
    files = [path for path in root_path.rglob("*") if path.is_file() and _is_history_file(path)]

    def matches(path: Path, needles: list[str]) -> bool:
        relative = str(path.relative_to(root_path)).lower()
        return any(token in relative for token in needles)

    chosen = [path for path in files if matches(path, tokens)]
    if not chosen and files and not any(matches(path, known) for path in files):
        # The folder is already campus-specific (no campus token in any path).
        chosen = files

    by_date: dict[str, list[Path]] = {}
    for path in chosen:
        match = DATE_RE.search(path.name)
        if not match:
            continue
        by_date.setdefault(match.group(1), []).append(path)

    selected = []
    for day in sorted(by_date):
        scored = []
        for path in by_date[day]:
            try:
                real = _real_count(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            scored.append((path, real, path.stat().st_size))
        if not scored:
            continue
        csvs = [item for item in scored if item[0].suffix.lower() == ".csv" and item[1] > 0]
        jsons = [item for item in scored if item[0].suffix.lower() == ".json" and item[1] > 0]
        if csvs:
            path, real, _size = max(csvs, key=lambda item: (item[1], item[2]))
            reason = "csv"
        elif jsons:
            path, real, _size = max(jsons, key=lambda item: (item[1], item[2]))
            csv_stubs = [item for item in scored if item[0].suffix.lower() == ".csv"]
            reason = "json (csv had no real listings)" if csv_stubs else "json (no csv for this date)"
        else:
            path, real, _size = max(scored, key=lambda item: item[2])
            reason = "largest file (no real listings)"
        selected.append({
            "date": day,
            "path": path,
            "reason": reason,
            "real_rows": real,
        })
    return selected


def rebuild_history(
    campus: str,
    fml_data: str | Path,
    out_dir: str | Path | None = None,
    *,
    full: bool = False,
    reset: bool = False,
    scraper_commit: str | None = None,
) -> dict:
    """Ingest every dated scrape for ``campus``, oldest first."""
    slug, meta = resolve_campus(campus)
    files = discover(fml_data, slug)
    out = Path(out_dir) if out_dir else None
    if reset and out is not None:
        campus_dir = Path(out) / slug
        if campus_dir.exists():
            shutil.rmtree(campus_dir)
    elif reset and out is None:
        from tools.scrape_archive.archive import DEFAULT_OUT
        campus_dir = DEFAULT_OUT / slug
        if campus_dir.exists():
            shutil.rmtree(campus_dir)

    runs = []
    totals = {
        "added": 0,
        "no_longer_advertised": 0,
        "reappeared": 0,
        "renamed": 0,
        "field_changes": 0,
    }
    ingested = 0
    skipped = 0
    for item in files:
        result = ingest(
            slug,
            item["path"],
            out,
            scraper_commit=scraper_commit,
            full=full,
        )
        counts = result.get("counts") or {}
        if result.get("skipped"):
            skipped += 1
        else:
            ingested += 1
            for key in totals:
                totals[key] += counts.get(key, 0)
        runs.append({
            "date": result.get("run_date") or item["date"],
            "file": str(item["path"]),
            "reason": item["reason"],
            "real_rows": item["real_rows"],
            "skipped": bool(result.get("skipped")),
            "skip_reason": result.get("reason", "") if result.get("skipped") else "",
            "run_id": result.get("run_id", ""),
            "added": counts.get("added", 0),
            "no_longer_advertised": counts.get("no_longer_advertised", 0),
            "reappeared": counts.get("reappeared", 0),
            "renamed": counts.get("renamed", 0),
            "field_changes": counts.get("field_changes", 0),
            "carried_forward_listings": counts.get("carried_forward_listings", 0),
            "unchanged": counts.get("unchanged", 0),
            "master_advertised": counts.get("master_advertised", 0),
            "master_listings": counts.get("master_listings", 0),
        })

    from tools.scrape_archive.archive import DEFAULT_OUT, write_upload_plan
    target = Path(out) if out else DEFAULT_OUT
    summary = {
        "campus": slug,
        "campus_name": meta["name"],
        "fml_data": str(Path(fml_data).resolve()),
        "full_snapshot": full,
        "files_discovered": len(files),
        "runs_ingested": ingested,
        "runs_skipped": skipped,
        "totals": totals,
        "master_listings": runs[-1]["master_listings"] if runs and not runs[-1]["skipped"] else _last_master(runs),
        "master_advertised": runs[-1]["master_advertised"] if runs and not runs[-1]["skipped"] else _last_advertised(runs),
        "runs": runs,
    }
    # The last non-skipped run holds the final master size. Fill it in even
    # when the tail of the list was a skip (it isn't, on a fresh rebuild).
    for run in reversed(runs):
        if run["master_listings"]:
            summary["master_listings"] = run["master_listings"]
            summary["master_advertised"] = run["master_advertised"]
            break
    campus_dir = target / slug
    campus_dir.mkdir(parents=True, exist_ok=True)
    (campus_dir / "history_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    write_upload_plan(target)
    summary["upload_plan"] = str(target / "upload_plan.json")
    summary["archive_root"] = str(target.resolve())
    return summary


def _last_master(runs: list[dict]) -> int:
    for run in reversed(runs):
        if run.get("master_listings"):
            return run["master_listings"]
    return 0


def _last_advertised(runs: list[dict]) -> int:
    for run in reversed(runs):
        if run.get("master_advertised"):
            return run["master_advertised"]
    return 0
