#!/usr/bin/env python3
"""
Filter the Wikimedia manifest.csv to remove non-monument images.

Removes:
  - Thangka paintings, traditional clothing, and Tibetan art (not monument photos)
  - Images with Japanese/Hiragana/Katakana/CJK characters in the title (foreign sites)

Writes a cleaned manifest back to the same path (or --output if specified).
Also moves the corresponding image files to a separate quarantine folder so they
are not picked up by convert_to_training_json.py.
"""

import csv
import shutil
import unicodedata
from pathlib import Path

# Categories that are not heritage monuments
NON_MONUMENT_CATEGORIES = {
    "Thangka",
    "Traditional_clothing_of_Nepal",
    "Tibetan_Buddhist_art",
}


def _has_cjk(text: str) -> bool:
    """Return True if any character in text is CJK, Hiragana, or Katakana."""
    for ch in text:
        name = unicodedata.name(ch, "")
        if "HIRAGANA" in name or "KATAKANA" in name or "CJK" in name:
            return True
    return False


def filter_manifest(
    manifest_path: Path,
    images_dir: Path,
    output_path: Path,
    quarantine_dir: Path | None = None,
) -> dict:
    """
    Read manifest_path, drop non-monument rows, write output_path.
    If quarantine_dir is given, move removed image files there.
    Returns stats dict.
    """
    rows: list[dict] = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    kept: list[dict] = []
    removed_category: list[dict] = []
    removed_cjk: list[dict] = []

    for row in rows:
        category = row.get("category", "").strip()
        page_title = row.get("page_title", "").strip()

        if category in NON_MONUMENT_CATEGORIES:
            removed_category.append(row)
            continue

        if _has_cjk(page_title):
            removed_cjk.append(row)
            continue

        kept.append(row)

    # Write cleaned manifest
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    # Optionally quarantine removed files
    if quarantine_dir:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        for row in removed_category + removed_cjk:
            filename = row.get("filename", "").strip().strip('"')
            category = row.get("category", "").strip()
            img_path = images_dir / f"Category:{category}" / filename
            if img_path.exists():
                dest_dir = quarantine_dir / category
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(img_path), str(dest_dir / filename))

    return {
        "original": len(rows),
        "kept": len(kept),
        "removed_bad_category": len(removed_category),
        "removed_cjk": len(removed_cjk),
        "total_removed": len(removed_category) + len(removed_cjk),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Filter non-monument images from manifest.csv")
    parser.add_argument(
        "--manifest", default="data/raw/wikimedia/manifest.csv",
        help="Input manifest CSV",
    )
    parser.add_argument(
        "--images-dir", default="data/raw/wikimedia/images",
        help="Root directory of downloaded images",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output path (default: overwrite input manifest)",
    )
    parser.add_argument(
        "--quarantine-dir", default=None,
        help="If set, move removed image files here instead of deleting",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be removed without writing anything",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_path = root / args.manifest
    images_dir = root / args.images_dir
    output_path = root / (args.output or args.manifest)
    quarantine_dir = root / args.quarantine_dir if args.quarantine_dir else None

    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return

    if args.dry_run:
        rows = []
        with open(manifest_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        bad_cat = [r for r in rows if r.get("category", "").strip() in NON_MONUMENT_CATEGORIES]
        bad_cjk = [r for r in rows if _has_cjk(r.get("page_title", ""))]
        print(f"DRY RUN: would remove {len(bad_cat)} bad-category + {len(bad_cjk)} CJK-titled images")
        print(f"  Bad categories: { {r['category'] for r in bad_cat} }")
        print(f"  CJK examples: {[r['page_title'][:60] for r in bad_cjk[:5]]}")
        return

    stats = filter_manifest(manifest_path, images_dir, output_path, quarantine_dir)
    print("Manifest filter complete:")
    print(f"  Original rows  : {stats['original']}")
    print(f"  Kept           : {stats['kept']}")
    print(f"  Removed (bad category): {stats['removed_bad_category']}")
    print(f"  Removed (CJK title)   : {stats['removed_cjk']}")
    print(f"  Total removed  : {stats['total_removed']}")
    print(f"  Output written : {output_path}")


if __name__ == "__main__":
    main()
