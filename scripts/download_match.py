#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from delstats.raw import RawMatchDownloader


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download every discovered raw JSON resource for one DEL match."
    )
    parser.add_argument("match_id", type=int)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Resource manifest from discover_match.py. Defaults to data/discovery/match_<id>_resources.json",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--no-shots",
        action="store_true",
        help="Do not download the separate visualization/shots resource.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files that already exist locally.",
    )
    args = parser.parse_args()

    manifest = args.manifest or Path(
        f"data/discovery/match_{args.match_id}_resources.json"
    )
    if not manifest.exists():
        parser.error(
            f"Resource manifest not found: {manifest}. Run discover_match.py first."
        )

    output_manifest, result = RawMatchDownloader().download_from_manifest(
        manifest,
        output_dir=args.output_dir,
        include_shots=not args.no_shots,
        force=args.force,
    )

    if result.match_id != args.match_id:
        parser.error(
            f"Manifest belongs to match {result.match_id}, not {args.match_id}."
        )

    print(f"Match: {result.match_id}")
    print(f"Resources: {len(result.resources)}")
    for resource in result.resources:
        print(
            f"  {resource.status:10} {resource.size_bytes:8} bytes  "
            f"{resource.local_path}"
        )
    print(f"\nSaved: {output_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
