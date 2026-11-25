"""Write the Drive-ready archive for one campus and keep its master state.

Layout under the output directory::

    upload_plan.json
    {campus}/snapshots/{date}_{runid}/   raw file + manifest.json
    {campus}/changes/{date}_changes.csv
    {campus}/changes/{date}_changes.json
    {campus}/changes/{date}_changes.md
    {campus}/master/master_latest.csv
    {campus}/master/master_{date}.csv
    {campus}/changes_log.csv
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from tools.scrape_archive.diff import apply_run
from tools.scrape_archive.normalize import classify, load_buildings, read_rows, scraped_dates
from tools.scrape_archive.schema import (
    CHANGE_COLUMNS,
    DATE_RE,
    DEFAULT_DRIVE_ROOT,
    MASTER_COLUMNS,
    resolve_campus,
)

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = PACKAGE_DIR / "output"
REPO_ROOT = PACKAGE_DIR.parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit(path: Path) -> str:
    """HEAD of the repo that contains ``path``, or "" when it is not a checkout."""
    try:
        return subprocess.check_output(
            ["git", "-C", str(path if path.is_dir() else path.parent), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def buildings_file(campus: str) -> Path | None:
    _slug, meta = resolve_campus(campus)
    for folder in meta.get("data_dirs") or []:
        candidate = REPO_ROOT / "data" / folder / "out" / "buildings.json"
        if candidate.exists():
            return candidate
    return None


def load_master(path: Path) -> dict:
    if not path.exists():
        return {}
    master = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            record = {column: (row.get(column) or "") for column in MASTER_COLUMNS}
            key = record["listing_key"]
            if key:
                master[key] = record
    return master


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def save_master(campus_dir: Path, master: dict, run_date: str) -> Path:
    rows = sorted(
        master.values(),
        key=lambda record: (
            record.get("property_name", "").lower(),
            record.get("label", "").lower(),
            record.get("listing_key", ""),
        ),
    )
    latest = campus_dir / "master" / "master_latest.csv"
    dated = campus_dir / "master" / f"master_{run_date}.csv"
    _write_csv(latest, MASTER_COLUMNS, rows)
    shutil.copyfile(latest, dated)
    return latest


def _stamp(changes: list[dict], run_date: str, run_id: str, campus: str) -> list[dict]:
    stamped = []
    for change in changes:
        row = {column: "" for column in CHANGE_COLUMNS}
        row.update(change)
        row["run_date"] = run_date
        row["run_id"] = run_id
        row["campus"] = campus
        stamped.append(row)
    return stamped


def _changes_stem(campus_dir: Path, run_date: str, run_id: str) -> Path:
    changes_dir = campus_dir / "changes"
    changes_dir.mkdir(parents=True, exist_ok=True)
    plain = changes_dir / f"{run_date}_changes"
    existing = plain.with_suffix(".json")
    if existing.exists():
        try:
            prior = json.loads(existing.read_text(encoding="utf-8")).get("run_id")
        except (OSError, json.JSONDecodeError):
            prior = None
        if prior and prior != run_id:
            return changes_dir / f"{run_date}_{run_id}_changes"
    return plain


def _render_markdown(campus: str, run_date: str, run_id: str, full: bool, result: dict, source_name: str) -> str:
    counts = result["counts"]
    lines = [
        f"# {campus} changes — {run_date}",
        "",
        f"Run `{run_id}` from `{source_name}`.",
        "",
    ]
    if full:
        lines.append(
            "Full snapshot: a property missing from this file (and not an extraction failure) "
            "is no longer advertised. Failure stubs keep the last real listings."
        )
    else:
        lines.append(
            "Partial scrape: listings whose property was not in this file are carried forward. "
            "A property is updated only when the file has real rows for it. "
            "An extraction-failed stub does not wipe that property."
        )
    lines += [
        "",
        "| | count |",
        "| --- | ---: |",
        f"| added | {counts['added']} |",
        f"| no longer advertised | {counts['no_longer_advertised']} |",
        f"| reappeared | {counts['reappeared']} |",
        f"| renamed | {counts['renamed']} |",
        f"| field changes | {counts['field_changes']} |",
        f"| unchanged (seen, same values) | {counts['unchanged']} |",
        f"| carried forward (not in this scrape) | {counts['carried_forward_listings']} |",
        f"| master listings advertised | {counts['master_advertised']} |",
        "",
        "## By building",
        "",
    ]
    active = [
        slot for slot in result["by_building"]
        if any(slot[name] for name in ("added", "no_longer_advertised", "reappeared", "renamed", "field_changes"))
    ]
    quiet = len(result["by_building"]) - len(active)
    if not active:
        lines.append("No building had a listing change.")
    else:
        lines += [
            "| building | added | removed | reappeared | renamed | field changes |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for slot in active:
            lines.append(
                f"| {slot['property_name']} | {slot['added']} | {slot['no_longer_advertised']} | "
                f"{slot['reappeared']} | {slot['renamed']} | {slot['field_changes']} |"
            )
    lines.append("")
    lines.append(f"{quiet} touched building(s) had no listing changes.")
    lines.append("")

    grouped: dict[str, list] = {name: [] for name in (
        "added", "reappeared", "renamed", "no_longer_advertised", "changed",
    )}
    for change in result["changes"]:
        grouped.setdefault(change["change_type"], []).append(change)

    def heading(title: str, rows: list[dict]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        if not rows:
            lines.append("_None._")
            lines.append("")

    heading("Added", grouped["added"])
    for change in grouped["added"]:
        bits = [change["label"] or "(no label)"]
        if change.get("base_rent"):
            bits.append(f"${change['base_rent']}")
        detail = " / ".join(
            part for part in (
                f"{change['beds']} bd" if change.get("beds") else "",
                f"{change['baths']} ba" if change.get("baths") else "",
                f"{change['sqft']} sqft" if change.get("sqft") else "",
            ) if part
        )
        if detail:
            bits.append(detail)
        lines.append(f"- **{change['property_name']}** — {', '.join(bits)}")
    if grouped["added"]:
        lines.append("")

    heading("No longer advertised", grouped["no_longer_advertised"])
    for change in grouped["no_longer_advertised"]:
        price = f" (was ${change['base_rent']})" if change.get("base_rent") else ""
        lines.append(f"- **{change['property_name']}** — {change['label']}{price}")
    if grouped["no_longer_advertised"]:
        lines.append("")

    heading("Reappeared", grouped["reappeared"])
    for change in grouped["reappeared"]:
        lines.append(f"- **{change['property_name']}** — {change['label']}")
    if grouped["reappeared"]:
        lines.append("")

    heading("Renamed", grouped["renamed"])
    for change in grouped["renamed"]:
        lines.append(
            f"- **{change['property_name']}** — {change['old_value']} → {change['new_value']}"
        )
    if grouped["renamed"]:
        lines.append("")

    lines.append("## Field changes")
    lines.append("")
    if not grouped["changed"]:
        lines.append("_None._")
        lines.append("")
    else:
        by_listing: dict[str, list] = {}
        for change in grouped["changed"]:
            by_listing.setdefault(change["listing_key"], []).append(change)
        for listing_changes in by_listing.values():
            head = listing_changes[0]
            parts = [
                f"{change['field']} {change['old_value'] or '∅'} → {change['new_value'] or '∅'}"
                for change in listing_changes
            ]
            lines.append(f"- **{head['property_name']}** — {head['label']}: " + "; ".join(parts))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _append_log(path: Path, rows: list[dict]) -> None:
    """Append rows for a new run id. A rerun of the same id replaces only those rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ids = {row.get("run_id", "") for row in rows}
    if not path.exists() or path.stat().st_size == 0:
        _write_csv(path, CHANGE_COLUMNS, rows)
        return
    with path.open(newline="", encoding="utf-8") as handle:
        prior = list(csv.DictReader(handle))
    present = {row.get("run_id", "") for row in prior}
    if run_ids and run_ids <= present:
        return
    if run_ids & present:
        kept = [row for row in prior if row.get("run_id", "") not in run_ids]
        _write_csv(path, CHANGE_COLUMNS, kept + rows)
        return
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CHANGE_COLUMNS, extrasaction="ignore", lineterminator="\n")
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in CHANGE_COLUMNS})


def _already_ingested(campus_dir: Path, source_sha: str) -> str:
    snaps = campus_dir / "snapshots"
    if not snaps.exists():
        return ""
    for manifest_path in snaps.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for source in manifest.get("sources") or []:
            if source.get("sha256") == source_sha:
                return manifest.get("run_id") or manifest_path.parent.name
    return ""


def infer_run_date(path: Path, raw_rows: list[dict], override: str | None) -> str:
    if override:
        if not DATE_RE.fullmatch(override):
            raise ValueError(f"--run-date must be YYYY-MM-DD, got {override!r}")
        return override
    match = DATE_RE.search(path.name)
    if match:
        return match.group(1)
    found = scraped_dates(raw_rows)
    if found:
        return Counter(found).most_common(1)[0][0]
    return datetime.now(timezone.utc).date().isoformat()


def ingest(
    campus: str,
    input_path: str | Path,
    out_dir: str | Path | None = None,
    *,
    run_date: str | None = None,
    run_id: str | None = None,
    scraper_commit: str | None = None,
    full: bool = False,
    buildings: dict | None = None,
) -> dict:
    """Archive one scrape file and fold it into the campus master.

    Returns a result dict. ``skipped`` is true when this exact file (sha256)
    is already in a snapshot manifest — re-running does not double-count.
    """
    slug, meta = resolve_campus(campus)
    source = Path(input_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    campus_dir = out / slug
    source_sha = sha256_file(source)
    seen = _already_ingested(campus_dir, source_sha)
    if seen:
        return {
            "skipped": True,
            "reason": f"already archived as run {seen}",
            "campus": slug,
            "run_id": seen,
            "source": str(source),
            "source_sha256": source_sha,
            "counts": {},
        }

    if buildings is None:
        buildings = load_buildings(buildings_file(slug))
    raw_rows = read_rows(source)
    records, failure_only = classify(raw_rows, buildings)
    day = infer_run_date(source, raw_rows, run_date)
    rid = run_id or source_sha[:12]
    commit = scraper_commit if scraper_commit is not None else git_commit(source)

    master_path = campus_dir / "master" / "master_latest.csv"
    master = load_master(master_path)
    result = apply_run(
        master, records, day,
        full=full, campus=slug, failure_only=failure_only,
    )
    stamped = _stamp(result["changes"], day, rid, slug)
    result["changes"] = stamped

    snapshot = campus_dir / "snapshots" / f"{day}_{rid}"
    snapshot.mkdir(parents=True, exist_ok=True)
    raw_dest = snapshot / source.name
    if source.resolve() != raw_dest.resolve():
        shutil.copyfile(source, raw_dest)

    stem = _changes_stem(campus_dir, day, rid)
    _write_csv(stem.with_suffix(".csv"), CHANGE_COLUMNS, stamped)
    catalogue = {
        "campus": slug,
        "campus_name": meta["name"],
        "run_id": rid,
        "run_date": day,
        "partial": not full,
        "scraper_commit": commit,
        "source": source.name,
        "summary": result["counts"],
        "by_building": result["by_building"],
        "changes": stamped,
    }
    stem.with_suffix(".json").write_text(
        json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    stem.with_suffix(".md").write_text(
        _render_markdown(slug, day, rid, full, result, source.name), encoding="utf-8",
    )
    _append_log(campus_dir / "changes_log.csv", stamped)
    latest = save_master(campus_dir, master, day)

    real_rows = sum(1 for record in records if not record.get("explicit_empty"))
    manifest = {
        "campus": slug,
        "campus_name": meta["name"],
        "run_id": rid,
        "run_date": day,
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scraper_commit": commit,
        "partial": not full,
        "sources": [{
            "filename": source.name,
            "sha256": source_sha,
            "bytes": source.stat().st_size,
            "rows": len(raw_rows),
            "real_rows": real_rows,
            "properties_touched": result["counts"]["properties_touched"],
            "properties_failed": result["counts"]["properties_failed"],
        }],
        "row_counts": result["counts"],
        "failure_only_properties": sorted(failure_only.values()),
    }
    (snapshot / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    plan = write_upload_plan(out)
    return {
        "skipped": False,
        "campus": slug,
        "campus_name": meta["name"],
        "run_id": rid,
        "run_date": day,
        "source": str(source),
        "source_sha256": source_sha,
        "scraper_commit": commit,
        "counts": result["counts"],
        "snapshot_dir": str(snapshot),
        "changes_csv": str(stem.with_suffix(".csv")),
        "changes_md": str(stem.with_suffix(".md")),
        "master_csv": str(latest),
        "upload_plan": str(out / "upload_plan.json"),
        "upload_plan_files": plan["file_count"],
    }


def write_upload_plan(out_dir: str | Path, root_name: str = DEFAULT_DRIVE_ROOT) -> dict:
    """List every archived file as local path -> Drive path under ``root_name``.

    The plan itself is not an entry. An agent that has Google Drive access
    uploads ``files`` and creates folders to match ``drive_path``.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    if out.exists():
        for path in sorted(p for p in out.rglob("*") if p.is_file()):
            if path.name == "upload_plan.json":
                continue
            relative = path.relative_to(out).as_posix()
            files.append({
                "local_path": str(path.resolve()),
                "drive_path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            })
    plan = {
        "root_folder_name": root_name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "archive_root": str(out.resolve()),
        "file_count": len(files),
        "files": files,
    }
    (out / "upload_plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return plan
