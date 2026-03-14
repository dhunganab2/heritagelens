#!/usr/bin/env python3
"""
Fold BLIP-2 captions back into metadata_merged.json.

Run AFTER generate_blip2_captions.py has produced blip2_captions.json.

For each image that has a BLIP-2 entry:
  - Replace Cap 1 with the BLIP-2 unconditional caption
  - Keep Cap 2 and Cap 3 (text-derived, carry domain vocabulary)

For images without a BLIP-2 entry (Tier A, or if BLIP-2 was skipped):
  - Keep all three captions unchanged

Writes an upgraded metadata_merged.json in-place
(backs up the original as metadata_merged.pre_blip2.json).
"""

import json
import shutil
from pathlib import Path


def assemble(
    merged_path: Path,
    blip2_path: Path,
    output_path: Path,
) -> None:
    with open(merged_path, "r", encoding="utf-8") as f:
        data: list[dict] = json.load(f)

    with open(blip2_path, "r", encoding="utf-8") as f:
        blip2: dict[str, list[str]] = json.load(f)

    upgraded = 0
    for entry in data:
        img_id = entry["image_id"]
        if img_id in blip2:
            caps = blip2[img_id]
            uncond   = caps[0].strip() if len(caps) > 0 else ""
            prompted = caps[1].strip() if len(caps) > 1 else ""
            # Use unconditional as Cap 1 (most accurate visual description)
            # Use prompted as Cap 2 only if it adds content beyond Cap 1
            if uncond:
                entry["captions"][0] = uncond
            if prompted and prompted != uncond and len(prompted) > 10:
                entry["captions"][1] = prompted
            upgraded += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Assembled {upgraded} BLIP-2 upgrades into {output_path}")
    print(f"Unchanged entries: {len(data) - upgraded}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Fold BLIP-2 captions into metadata_merged.json"
    )
    parser.add_argument("--merged",  default="data/processed/metadata_merged.json")
    parser.add_argument("--blip2",   default="data/processed/blip2_captions.json")
    parser.add_argument("--output",  default=None,
                        help="Output path (default: overwrite merged JSON, backup kept)")
    args = parser.parse_args()

    root        = Path(__file__).resolve().parent.parent
    merged_path = root / args.merged
    blip2_path  = root / args.blip2
    output_path = root / (args.output or args.merged)

    if not merged_path.exists():
        print(f"File not found: {merged_path}")
        return
    if not blip2_path.exists():
        print(f"BLIP-2 captions not found: {blip2_path}")
        print("Run generate_blip2_captions.py first.")
        return

    # Backup original
    backup = merged_path.with_suffix(".pre_blip2.json")
    if not backup.exists():
        shutil.copy(merged_path, backup)
        print(f"Backed up original to {backup}")

    assemble(merged_path, blip2_path, output_path)
    print(f"\nNext step: run test_data_quality.py to verify the upgraded dataset.")


if __name__ == "__main__":
    main()
