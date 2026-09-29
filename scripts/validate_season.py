#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail the pipeline when the season quality report contains hard errors.")
    parser.add_argument("--report", type=Path, default=Path("data/reports/season_quality.json"))
    parser.add_argument("--max-low-confidence", type=int, default=-1, help="Optional hard limit; negative disables this gate.")
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    pipeline = report.get("pipeline", {})
    quality = report.get("on_ice_quality", {})
    failures: list[str] = []

    failed_downloads = int(pipeline.get("failed_downloads", 0) or 0)
    failed_imports = int(pipeline.get("failed_imports", 0) or 0)
    completed = int(pipeline.get("completed_matches", 0) or 0)
    imported = int(report.get("totals", {}).get("matches", 0) or 0)
    low_confidence = int(quality.get("low_confidence", 0) or 0)
    team_game_stats = int(report.get("totals", {}).get("team_game_stats", 0) or 0)
    unclassified_shots = int(report.get("totals", {}).get("unclassified_shots", 0) or 0)

    if failed_downloads:
        failures.append(f"{failed_downloads} match download(s) failed")
    if failed_imports:
        failures.append(f"{failed_imports} match import(s) failed")
    if imported != completed:
        failures.append(f"imported matches ({imported}) != completed matches ({completed})")
    if team_game_stats != imported * 2:
        failures.append(
            f"team game analytics rows ({team_game_stats}) != expected ({imported * 2})"
        )
    if args.max_low_confidence >= 0 and low_confidence > args.max_low_confidence:
        failures.append(
            f"low-confidence shots ({low_confidence}) exceed limit ({args.max_low_confidence})"
        )

    print(f"Completed matches: {completed}")
    print(f"Imported matches:  {imported}")
    print(f"Shots:             {report.get('totals', {}).get('shots', 0)}")
    print(f"Low confidence:    {low_confidence}")
    print(f"Boundary adjusted: {quality.get('boundary_adjusted', 0)}")
    print(f"Team game rows:     {team_game_stats}")
    print(f"Unclassified zones: {unclassified_shots}")

    if failures:
        print("\nQUALITY GATE FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nQUALITY GATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
