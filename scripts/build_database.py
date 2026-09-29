#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from delstats.database import build_match_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/update the local DEL DuckDB database from raw match JSON.")
    parser.add_argument("match_id", type=int)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--db", type=Path, default=Path("data/del_2026_27.duckdb"))
    parser.add_argument(
        "--discovery",
        type=Path,
        default=Path("data/discovery/season_2026_27_type_1.json"),
        help="Optional season discovery JSON for start datetime/status metadata.",
    )
    args = parser.parse_args()

    summary = build_match_database(
        match_dir=args.raw_dir / str(args.match_id),
        db_path=args.db,
        discovery_path=args.discovery,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
