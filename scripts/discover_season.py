#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from delstats.discovery import SeasonDiscoverer, save_season_discovery


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover all DEL match IDs for a season from the public S3 schedules."
    )
    parser.add_argument("--season", type=int, default=2026, help="Season start year")
    parser.add_argument("--game-type", type=int, default=1, help="Historical DEL game type ID (1=regular season)")
    parser.add_argument("--output-dir", type=Path, default=Path("data/discovery"))
    args = parser.parse_args()

    result = SeasonDiscoverer().discover_season(args.season, args.game_type)
    json_path, csv_path = save_season_discovery(result, args.output_dir)

    print(f"Season:       {result.season}/{str(result.season + 1)[-2:]}")
    print(f"Game type:    {result.game_type}")
    print(f"Schedule keys:{len(result.schedule_keys):>6}")
    print(f"Team IDs:     {len(result.team_ids):>6}  {result.team_ids}")
    print(f"Unique games: {len(result.matches):>6}")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
