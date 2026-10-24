#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from delstats.database import build_match_database
from delstats.season import _raw_match_ready, build_quality_report, write_quality_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline rebuild + cross-source QA for all locally available DEL raw matches."
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--discovery",
        type=Path,
        default=Path("data/discovery/season_2026_27_type_1.json"),
    )
    parser.add_argument("--db", type=Path, default=Path("/tmp/del-dataset-qa.duckdb"))
    parser.add_argument("--report-dir", type=Path, default=Path("qa-output"))
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--game-type", type=int, default=1)
    args = parser.parse_args()

    if args.db.exists():
        args.db.unlink()

    raw_dirs = sorted(
        (path for path in args.raw_dir.iterdir() if path.is_dir() and path.name.isdigit()),
        key=lambda path: int(path.name),
    )
    ready = [path for path in raw_dirs if _raw_match_ready(path)]
    skipped = [path.name for path in raw_dirs if not _raw_match_ready(path)]
    import_errors: list[dict[str, str]] = []

    for index, match_dir in enumerate(ready, start=1):
        print(f"[{index}/{len(ready)}] rebuild match {match_dir.name}")
        try:
            build_match_database(
                match_dir=match_dir,
                db_path=args.db,
                discovery_path=args.discovery if args.discovery.exists() else None,
            )
        except Exception as exc:  # noqa: BLE001 - audit must report all broken matches
            import_errors.append(
                {"match_id": match_dir.name, "error": f"{type(exc).__name__}: {exc}"}
            )

    if not args.db.exists():
        print("No QA database could be built.")
        return 1

    report = build_quality_report(args.db, season=args.season, game_type=args.game_type)
    report["offline_audit"] = {
        "raw_match_dirs": len(raw_dirs),
        "ready_match_dirs": len(ready),
        "skipped_incomplete_match_ids": skipped,
        "import_errors": import_errors,
    }
    json_path, md_path = write_quality_report(report, args.report_dir)

    integrity = report.get("integrity") or {}
    hard = list(integrity.get("hard_failures") or [])
    warnings = list(integrity.get("warnings") or [])

    print()
    print("OFFLINE DATASET QA")
    print(f"Raw match dirs:     {len(raw_dirs)}")
    print(f"Ready/rebuilt:      {len(ready) - len(import_errors)}/{len(ready)}")
    print(f"Skipped incomplete: {len(skipped)}")
    print(f"Import errors:      {len(import_errors)}")
    print(f"Integrity failures: {len(hard)}")
    print(f"Integrity warnings: {len(warnings)}")
    print(f"Report:             {json_path}")
    print(f"Markdown:           {md_path}")

    if skipped:
        print(f"Skipped match IDs: {', '.join(skipped)}")

    if warnings:
        print("\nQA WARNINGS")
        for issue in warnings[:30]:
            print(
                f"- {issue.get('code')}: match {issue.get('match_id', '?')} · "
                f"{issue.get('message')}"
            )
        if len(warnings) > 30:
            print(f"- ... {len(warnings) - 30} more; see report")

    if import_errors or hard:
        print("\nQA FAILED")
        for row in import_errors:
            print(f"- import {row['match_id']}: {row['error']}")
        for issue in hard[:50]:
            print(
                f"- {issue.get('code')}: match {issue.get('match_id', '?')} · "
                f"{issue.get('message')}"
            )
        if len(hard) > 50:
            print(f"- ... {len(hard) - 50} more; see report")
        return 1

    print("\nQA PASSED WITH WARNINGS" if warnings else "\nQA PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
