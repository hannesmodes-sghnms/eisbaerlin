#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from delstats.schema import inspect_match_directory, write_schema_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect downloaded DEL match JSON and create a schema report."
    )
    parser.add_argument("match_id", type=int)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/schema"))
    args = parser.parse_args()

    match_dir = args.raw_dir / str(args.match_id)
    report = inspect_match_directory(match_dir)
    json_path, md_path = write_schema_report(report, output_dir=args.output_dir)

    print(f"Match: {args.match_id}")
    print(f"Files inspected: {report['file_count']}")
    for file_report in report["files"]:
        print(
            f"  {file_report['file']}: root={file_report['root_type']}, "
            f"paths={file_report['path_count']}, size={file_report['size_bytes']}"
        )
    print(f"\nSaved: {json_path}")
    print(f"Saved: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
