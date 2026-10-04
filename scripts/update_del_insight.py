#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from delstats.del_insight import derive_game_deltas, fetch_snapshot, persist_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch public PENNY DEL / Wisehockey player stats and persist cumulative snapshots."
    )
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--phase", default="hauptrunde")
    parser.add_argument("--output-dir", type=Path, default=Path("data/del_insight"))
    parser.add_argument(
        "--discovery",
        type=Path,
        default=Path("data/discovery/season_2026_27_type_1.json"),
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on DEL Insight fetch/parse errors. Default is warning-only fallback.",
    )
    args = parser.parse_args()

    try:
        snapshot = fetch_snapshot(season=args.season, phase=args.phase, timeout=args.timeout)
        path, changed = persist_snapshot(snapshot, args.output_dir)
        game_paths = derive_game_deltas(root=args.output_dir, discovery_path=args.discovery)
        print(f"DEL Insight players: {len(snapshot.get('players', []))}")
        print(f"Snapshot: {path} ({'changed' if changed else 'unchanged'})")
        print(f"Derived game files: {len(game_paths)}")
        return 0
    except Exception as exc:  # noqa: BLE001 - optional upstream must not break the main pipeline
        message = f"DEL Insight update skipped: {type(exc).__name__}: {exc}"
        print(f"WARNING: {message}")
        if os.getenv("GITHUB_ACTIONS") == "true":
            print(f"::warning title=DEL Insight fallback::{message}")
        return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
