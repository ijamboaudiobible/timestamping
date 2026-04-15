#!/usr/bin/env python3
"""
Rename files in the same directory as this script by stripping a leading prefix.

Example:
  python strip_filename_prefix.py pre_
  renames pre_romans1.json -> romans1.json (only files whose names start with pre_)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove a prefix from the start of filenames in this script's folder."
    )
    parser.add_argument(
        "prefix",
        help="Prefix to remove (e.g. pre_). Only files whose names start with this are renamed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be renamed without changing anything.",
    )
    args = parser.parse_args()
    prefix: str = args.prefix

    if not prefix:
        print("Error: prefix must be non-empty.", file=sys.stderr)
        return 1

    here = Path(__file__).resolve().parent
    self_name = Path(__file__).name

    planned: list[tuple[Path, Path]] = []
    for path in sorted(here.iterdir()):
        if not path.is_file():
            continue
        if path.name == self_name:
            continue
        if not path.name.startswith(prefix):
            continue
        new_name = path.name[len(prefix) :]
        if not new_name:
            print(f"skip (nothing left after strip): {path.name!r}", file=sys.stderr)
            continue
        planned.append((path, here / new_name))

    if not planned:
        print("No files matched that prefix in this folder.")
        return 0

    exit_code = 0
    for src, dst in planned:
        if dst.exists():
            print(
                f"skip (target already exists): {src.name!r} -> {dst.name!r}",
                file=sys.stderr,
            )
            exit_code = 1
            continue
        if args.dry_run:
            print(f"would rename: {src.name} -> {dst.name}")
        else:
            src.rename(dst)
            print(f"renamed: {src.name} -> {dst.name}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
