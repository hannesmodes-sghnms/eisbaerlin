#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from delstats.season import update_season


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover, download, rebuild, and quality-check one DEL season."
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--game-type", type=int, default=1)
    parser.add_argument("--refresh-days", type=int, default=3)
    parser.add_argument("--discovery-dir", type=Path, default=Path("data/discovery"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--db", type=Path, default=Path("data/del_2026_27.duckdb"))
    parser.add_argument("--reports-dir", type=Path, default=Path("data/reports"))
    parser.add_argument("--team-id", type=int, default=3, help="Only download/import matches involving this team (default: EBB=3)")
    args = parser.parse_args()

    summary = update_season(
        season=args.season,
        game_type=args.game_type,
        refresh_days=args.refresh_days,
        discovery_dir=args.discovery_dir,
        raw_dir=args.raw_dir,
        db_path=args.db,
        reports_dir=args.reports_dir,
        focus_team_id=args.team_id,
    )
    print(json.dumps(asdict(summary), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
