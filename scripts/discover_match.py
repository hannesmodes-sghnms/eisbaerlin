#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from delstats.discovery import SeasonDiscoverer, save_match_discovery


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List all public S3 resources belonging to a DEL match."
    )
    parser.add_argument("match_id", type=int)
    parser.add_argument("--verify-shots", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("data/discovery"))
    args = parser.parse_args()

    result = SeasonDiscoverer().discover_match_resources(
        args.match_id, verify_shots=args.verify_shots
    )
    output = save_match_discovery(result, args.output_dir)

    print(f"Match: {result.match_id}")
    print(f"Objects below {result.match_prefix}: {len(result.all_keys)}")
    for category, keys in result.resources.items():
        if keys:
            print(f"\n{category} ({len(keys)}):")
            for key in keys:
                print(f"  {key}")
    print(f"\nshots candidate: {result.shot_url}")
    if result.shot_exists is not None:
        print(f"shots verified:  {result.shot_exists}")
    print(f"\nSaved: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
