#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from delstats.podcast import export_season_tables


def main() -> None:
    parser = argparse.ArgumentParser(description="Export DEL team game/season analytics as CSV.")
    parser.add_argument("--db", type=Path, default=Path("data/del_2026_27.duckdb"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports/analytics"))
    args = parser.parse_args()
    game_path, season_path = export_season_tables(db_path=args.db, output_dir=args.output_dir)
    print(game_path)
    print(season_path)


if __name__ == "__main__":
    main()
