#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from delstats.podcast import generate_matchup_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate podcast prep for two DEL teams.")
    parser.add_argument("--team-a", required=True, help="Team id, shortcut (e.g. EBB) or exact/unique team name")
    parser.add_argument("--team-b", required=True, help="Team id, shortcut (e.g. MAN) or exact/unique team name")
    parser.add_argument("--db", type=Path, default=Path("data/del_2026_27.duckdb"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports/podcast"))
    parser.add_argument("--last-games", type=int, default=5)
    parser.add_argument("--season-label", default="2026/27")
    args = parser.parse_args()
    out = generate_matchup_report(
        db_path=args.db,
        team_a=args.team_a,
        team_b=args.team_b,
        output_root=args.output_dir,
        last_games=args.last_games,
        season_label=args.season_label,
    )
    print(out)


if __name__ == "__main__":
    main()
