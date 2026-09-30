#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from delstats.dashboard import generate_dashboard_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate static EBB dashboard JSON from DuckDB, raw data and season discovery data.")
    parser.add_argument("--db", type=Path, default=Path("data/del_2026_27.duckdb"))
    parser.add_argument("--discovery", type=Path, default=Path("data/discovery/season_2026_27_type_1.json"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("site/data"))
    parser.add_argument("--upcoming", type=int, default=3, help="Number of upcoming EBB games to include")
    args = parser.parse_args()
    index_path, games = generate_dashboard_data(
        db_path=args.db,
        discovery_path=args.discovery,
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
        upcoming_limit=args.upcoming,
    )
    print(f"Dashboard index: {index_path}")
    print(f"Completed EBB games: {len(games)}")


if __name__ == "__main__":
    main()
