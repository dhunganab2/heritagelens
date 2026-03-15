#!/usr/bin/env python3
"""
Filter manifest.csv to at most MAX_EXT exterior + MAX_OBJ object images
per monument, writing a filtered CSV for the conversion step.

Usage:
  python3 scripts/filter_manifest.py [--max-ext 2] [--max-obj 3]
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def filter_manifest(
    manifest_path: Path,
    output_path: Path,
    max_ext: int = 2,
    max_obj: int = 3,
) -> None:
    with open(manifest_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())

    ext_counts: dict[str, int] = defaultdict(int)
    obj_counts: dict[str, int] = defaultdict(int)
    kept: list[dict] = []

    for row in rows:
        mid = row["monument_id"]
        itype = row.get("image_type", "exterior")
        if itype == "exterior":
            if ext_counts[mid] < max_ext:
                kept.append(row)
                ext_counts[mid] += 1
        else:
            if obj_counts[mid] < max_obj:
                kept.append(row)
                obj_counts[mid] += 1

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    ext_total = sum(ext_counts.values())
    obj_total = sum(obj_counts.values())
    print(f"Filtered manifest written to: {output_path}")
    print(f"  Total rows  : {len(kept)}  (exterior={ext_total}, object={obj_total})")
    print(f"  Monuments   : {len(set(ext_counts) | set(obj_counts))}")
    print(f"  Max ext/mon : {max_ext}   Max obj/mon : {max_obj}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest",  default="data/raw/danam/manifest.csv")
    parser.add_argument("--output",    default="data/raw/danam/manifest_filtered.csv")
    parser.add_argument("--max-ext",   type=int, default=2)
    parser.add_argument("--max-obj",   type=int, default=3)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    filter_manifest(
        root / args.manifest,
        root / args.output,
        max_ext=args.max_ext,
        max_obj=args.max_obj,
    )


if __name__ == "__main__":
    main()
