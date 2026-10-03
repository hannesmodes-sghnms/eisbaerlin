#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


RAW_INCOMPLETE_ERROR = "raw data incomplete"


def _is_raw_incomplete(error: dict[str, Any]) -> bool:
    return str(error.get("error") or "").strip().lower() == RAW_INCOMPLETE_ERROR


def evaluate_report(
    report: dict[str, Any],
    *,
    max_low_confidence: int = -1,
    allow_incomplete: bool = False,
) -> tuple[list[str], list[str]]:
    """Return (warnings, failures) for one season quality report.

    ``--allow-incomplete`` is intentionally narrow: temporary upstream-data
    gaps (download failures / raw data incomplete) are downgraded to warnings,
    while real importer exceptions and internal DB inconsistencies remain hard
    failures.
    """
    pipeline = report.get("pipeline", {})
    quality = report.get("on_ice_quality", {})
    totals = report.get("totals", {})

    warnings: list[str] = []
    failures: list[str] = []

    failed_downloads = int(pipeline.get("failed_downloads", 0) or 0)
    completed = int(pipeline.get("completed_matches", 0) or 0)
    imported = int(totals.get("matches", 0) or 0)
    low_confidence = int(quality.get("low_confidence", 0) or 0)
    team_game_stats = int(totals.get("team_game_stats", 0) or 0)

    import_errors = list(pipeline.get("import_errors") or [])
    raw_incomplete = [row for row in import_errors if _is_raw_incomplete(row)]
    hard_import_errors = [row for row in import_errors if not _is_raw_incomplete(row)]

    if failed_downloads:
        message = f"{failed_downloads} match download(s) failed"
        (warnings if allow_incomplete else failures).append(message)

    if raw_incomplete:
        ids = ", ".join(str(row.get("match_id")) for row in raw_incomplete)
        message = (
            f"{len(raw_incomplete)} match(es) deferred because upstream raw data is incomplete"
            + (f" (match_id: {ids})" if ids else "")
        )
        (warnings if allow_incomplete else failures).append(message)

    if hard_import_errors:
        failures.append(f"{len(hard_import_errors)} real match import error(s)")
        for row in hard_import_errors:
            failures.append(
                f"match {row.get('match_id', '?')}: {row.get('error') or 'unknown import error'}"
            )

    if imported > completed:
        failures.append(
            f"imported matches ({imported}) exceed completed matches ({completed})"
        )
    elif imported < completed:
        missing = completed - imported
        if allow_incomplete and not hard_import_errors:
            warnings.append(
                f"dataset is temporarily partial: imported {imported}/{completed} completed matches "
                f"({missing} deferred)"
            )
        else:
            failures.append(
                f"imported matches ({imported}) != completed matches ({completed})"
            )

    if team_game_stats != imported * 2:
        failures.append(
            f"team game analytics rows ({team_game_stats}) != expected ({imported * 2})"
        )

    if max_low_confidence >= 0 and low_confidence > max_low_confidence:
        failures.append(
            f"low-confidence shots ({low_confidence}) exceed limit ({max_low_confidence})"
        )

    return warnings, failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the season quality report and fail only on configured hard errors."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/season_quality.json"),
    )
    parser.add_argument(
        "--max-low-confidence",
        type=int,
        default=-1,
        help="Optional hard limit; negative disables this gate.",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help=(
            "Treat temporary upstream gaps (failed downloads / raw data incomplete) "
            "as warnings so the dashboard can continue with successfully imported matches. "
            "Real import exceptions and DB inconsistencies still fail."
        ),
    )
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    pipeline = report.get("pipeline", {})
    quality = report.get("on_ice_quality", {})
    totals = report.get("totals", {})

    completed = int(pipeline.get("completed_matches", 0) or 0)
    imported = int(totals.get("matches", 0) or 0)
    low_confidence = int(quality.get("low_confidence", 0) or 0)
    team_game_stats = int(totals.get("team_game_stats", 0) or 0)
    unclassified_shots = int(totals.get("unclassified_shots", 0) or 0)

    warnings, failures = evaluate_report(
        report,
        max_low_confidence=args.max_low_confidence,
        allow_incomplete=args.allow_incomplete,
    )

    print(f"Completed matches: {completed}")
    print(f"Imported matches:  {imported}")
    print(f"Shots:             {totals.get('shots', 0)}")
    print(f"Low confidence:    {low_confidence}")
    print(f"Boundary adjusted: {quality.get('boundary_adjusted', 0)}")
    print(f"Team game rows:    {team_game_stats}")
    print(f"Unclassified zones: {unclassified_shots}")

    if warnings:
        print("\nQUALITY WARNINGS")
        for warning in warnings:
            print(f"- {warning}")
            if os.getenv("GITHUB_ACTIONS") == "true":
                print(f"::warning title=DEL dataset partial::{warning}")

    if failures:
        print("\nQUALITY GATE FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if warnings:
        print("\nQUALITY GATE PASSED WITH WARNINGS")
        print(
            "Fallback active: downstream dashboard/report steps continue with the "
            "successfully imported matches. Deferred matches will be retried on the next run."
        )
    else:
        print("\nQUALITY GATE PASSED")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
