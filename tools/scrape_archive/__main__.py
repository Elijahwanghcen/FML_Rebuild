"""CLI: python -m tools.scrape_archive <ingest|rebuild-history|upload-plan|upload>."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.scrape_archive.archive import DEFAULT_OUT, ingest, write_upload_plan
from tools.scrape_archive.history import rebuild_history
from tools.scrape_archive.schema import DEFAULT_DRIVE_ROOT


def _out(value: str | None) -> Path:
    return Path(value) if value else DEFAULT_OUT


def _print_counts(result: dict) -> None:
    counts = result.get("counts") or {}
    if result.get("skipped"):
        print(f"skip {result.get('source')} ({result.get('reason')})")
        return
    print(
        f"{result['run_date']}  {Path(result['source']).name}  "
        f"added={counts.get('added', 0)}  "
        f"removed={counts.get('no_longer_advertised', 0)}  "
        f"reappeared={counts.get('reappeared', 0)}  "
        f"renamed={counts.get('renamed', 0)}  "
        f"field_changes={counts.get('field_changes', 0)}  "
        f"carried_forward={counts.get('carried_forward_listings', 0)}  "
        f"master_advertised={counts.get('master_advertised', 0)}"
    )


def cmd_ingest(args: argparse.Namespace) -> int:
    result = ingest(
        args.campus,
        args.input,
        _out(args.out),
        run_date=args.run_date,
        run_id=args.run_id,
        scraper_commit=args.scraper_commit,
        full=args.full,
    )
    _print_counts(result)
    if not result.get("skipped"):
        print(f"snapshot {result['snapshot_dir']}")
        print(f"master   {result['master_csv']}")
        print(f"plan     {result['upload_plan']}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    summary = rebuild_history(
        args.campus,
        args.fml_data,
        _out(args.out),
        full=args.full,
        reset=args.reset,
        scraper_commit=args.scraper_commit,
    )
    print(f"campus {summary['campus']}  discovered {summary['files_discovered']} dated files")
    for run in summary["runs"]:
        flag = "skip" if run["skipped"] else "ok  "
        print(
            f"  {flag} {run['date']}  {run['reason']:32}  "
            f"added={run['added']} removed={run['no_longer_advertised']} "
            f"reappeared={run['reappeared']} renamed={run['renamed']} "
            f"field_changes={run['field_changes']} carried={run['carried_forward_listings']}"
        )
    totals = summary["totals"]
    print(
        f"ingested {summary['runs_ingested']}  skipped {summary['runs_skipped']}  "
        f"added={totals['added']} removed={totals['no_longer_advertised']} "
        f"reappeared={totals['reappeared']} renamed={totals['renamed']} "
        f"field_changes={totals['field_changes']}"
    )
    print(
        f"master listings={summary['master_listings']}  "
        f"advertised={summary['master_advertised']}"
    )
    print(f"archive {summary['archive_root']}")
    print(f"plan    {summary['upload_plan']}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    plan = write_upload_plan(_out(args.out), args.root_name)
    print(f"{plan['file_count']} files -> {_out(args.out) / 'upload_plan.json'}")
    print(f"root folder name: {plan['root_folder_name']}")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    from tools.scrape_archive.drive_upload import DriveError, upload
    plan_path = Path(args.plan) if args.plan else _out(args.out) / "upload_plan.json"
    if not plan_path.is_file():
        print(f"no upload plan at {plan_path}", file=sys.stderr)
        return 1
    try:
        result = upload(plan_path, dry_run=args.dry_run, root_name=args.root_name)
    except DriveError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.scrape_archive",
        description="Archive every scrape and catalogue listing changes.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", help=f"archive directory (default: {DEFAULT_OUT})")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", parents=[common], help="archive one CSV or JSON scrape")
    ing.add_argument("--campus", required=True, help="ut-austin, texas-am, or a new slug")
    ing.add_argument("--input", required=True, help="scrape CSV or JSON")
    ing.add_argument("--run-date", help="YYYY-MM-DD (default: the date in the filename)")
    ing.add_argument("--run-id", help="override the id derived from the file sha256")
    ing.add_argument("--scraper-commit", help="scraper git SHA to store in the manifest")
    ing.add_argument(
        "--full", action="store_true",
        help="treat a property missing from this file as no longer advertised",
    )
    ing.set_defaults(func=cmd_ingest)

    hist = sub.add_parser("rebuild-history", parents=[common], help="backfill from dated FML_Data scrapes, oldest first")
    hist.add_argument("--campus", required=True)
    hist.add_argument("--fml-data", required=True, help="FML_Data checkout, or a folder of dated scrapes")
    hist.add_argument("--full", action="store_true", help="same as ingest --full, for every file")
    hist.add_argument("--reset", action="store_true", help="delete this campus archive before replaying")
    hist.add_argument("--scraper-commit", help="scraper git SHA stored on every manifest")
    hist.set_defaults(func=cmd_history)

    plan = sub.add_parser("upload-plan", parents=[common], help="rewrite upload_plan.json from the archive")
    plan.add_argument("--root-name", default=DEFAULT_DRIVE_ROOT)
    plan.set_defaults(func=cmd_plan)

    up = sub.add_parser("upload", parents=[common], help="upload upload_plan.json with Drive credentials from the environment")
    up.add_argument("--plan", help="path to upload_plan.json (default: <out>/upload_plan.json)")
    up.add_argument("--root-name", help=f"Drive folder name (default: {DEFAULT_DRIVE_ROOT})")
    up.add_argument("--dry-run", action="store_true", help="print the plan size and do not authenticate")
    up.set_defaults(func=cmd_upload)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
