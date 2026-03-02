#!/usr/bin/env python3
"""
Merge Wikimedia and DANAM metadata files into a single training dataset.

Reads:
  - data/processed/metadata.json       (from Wikimedia, via convert_to_training_json.py)
  - data/processed/metadata_danam.json  (from DANAM, via convert_danam_to_json.py)

Writes:
  - data/processed/metadata_merged.json (combined dataset ready for HeritageDataset)

Each entry has: image_id, category, cultural_label, captions, source
"""

import json
from collections import Counter
from pathlib import Path


def merge(
    wikimedia_path: Path,
    danam_path: Path,
    output_path: Path,
):
    merged: list[dict] = []
    source_counts: Counter = Counter()

    if wikimedia_path.exists():
        with open(wikimedia_path, "r", encoding="utf-8") as f:
            wiki_data = json.load(f)
        for entry in wiki_data:
            entry.setdefault("source", "wikimedia")
        merged.extend(wiki_data)
        source_counts["wikimedia"] = len(wiki_data)
        print(f"  Wikimedia : {len(wiki_data)} images")
    else:
        print(f"  Wikimedia : not found ({wikimedia_path})")

    if danam_path.exists():
        with open(danam_path, "r", encoding="utf-8") as f:
            danam_data = json.load(f)
        for entry in danam_data:
            entry.setdefault("source", "danam")
        merged.extend(danam_data)
        source_counts["danam"] = len(danam_data)
        print(f"  DANAM     : {len(danam_data)} images")
    else:
        print(f"  DANAM     : not found ({danam_path})")

    if not merged:
        print("No data to merge!")
        return

    label_counts: Counter = Counter()
    for entry in merged:
        label_counts[entry.get("cultural_label", "unknown")] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\n  Total merged : {len(merged)} images")
    print(f"  Output       : {output_path}")
    print(f"\n  Sources: {dict(source_counts)}")
    print(f"  Labels:  {dict(label_counts)}")


def main():
    root = Path(__file__).resolve().parent.parent
    wikimedia_path = root / "data" / "processed" / "metadata.json"
    danam_path = root / "data" / "processed" / "metadata_danam.json"
    output_path = root / "data" / "processed" / "metadata_merged.json"

    print("Merging Wikimedia + DANAM datasets ...")
    merge(wikimedia_path, danam_path, output_path)


if __name__ == "__main__":
    main()
