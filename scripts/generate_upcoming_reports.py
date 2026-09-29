#!/usr/bin/env python
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from delstats.podcast import generate_matchup_report, upcoming_matchups


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate podcast prep for upcoming DEL games.")
    parser.add_argument("--season-json", type=Path, default=Path("data/discovery/season_2026_27_type_1.json"))
    parser.add_argument("--db", type=Path, default=Path("data/del_2026_27.duckdb"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports/podcast"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--last-games", type=int, default=5)
    parser.add_argument("--timezone", default="Europe/Berlin")
    args = parser.parse_args()

    today = datetime.now(ZoneInfo(args.timezone)).date()
    matches = upcoming_matchups(season_json=args.season_json, today=today, days=args.days)
    if not matches:
        print("No upcoming matches in requested window.")
        return
    for match in matches:
        try:
            out = generate_matchup_report(
                db_path=args.db,
                team_a=int(match["home_team_id"]),
                team_b=int(match["away_team_id"]),
                output_root=args.output_dir,
                last_games=args.last_games,
            )
            print(f"{match['match_id']}: {out}")
        except ValueError as exc:
            # Early season: a team may not yet have imported game stats. Keep the
            # daily pipeline alive and make the gap visible in the log.
            print(f"{match.get('match_id')}: skipped: {exc}")


if __name__ == "__main__":
    main()
