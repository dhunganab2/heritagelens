#!/usr/bin/env python3
"""
Build heritagelens-data.zip for Google Colab training.

Flat structure inside the zip:
  metadata_merged.json          ← training metadata
  images/<filename>.jpg         ← all referenced images (NFC-normalized names)

Usage:
  python3 scripts/build_zip.py
  python3 scripts/build_zip.py --metadata data/processed/metadata_gemini.json
  python3 scripts/build_zip.py --output   my_custom_name.zip
"""

import argparse
import json
import unicodedata
import zipfile
from pathlib import Path

import tqdm

ROOT       = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "data/raw/danam/images"
DEFAULT_META   = ROOT / "data/processed/metadata_merged.json"
DEFAULT_OUTPUT = ROOT / "heritagelens-data.zip"


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def build_image_lookup(images_dir: Path) -> dict[str, Path]:
    """Build filename → path lookup once; avoids O(N*M) per-file scan."""
    lookup: dict[str, Path] = {}
    for subdir in images_dir.iterdir():
        if not subdir.is_dir():
            continue
        for p in subdir.iterdir():
            if p.is_file():
                lookup[nfc(p.name)] = p
                lookup[p.name] = p  # also store original for exact match
    return lookup


def main():
    parser = argparse.ArgumentParser(description="Build heritagelens-data.zip for Colab")
    parser.add_argument("--metadata", default=str(DEFAULT_META),   help="Metadata JSON to pack")
    parser.add_argument("--output",   default=str(DEFAULT_OUTPUT),  help="Output zip path")
    args = parser.parse_args()

    meta_path = Path(args.metadata)
    out_path  = Path(args.output)

    with open(meta_path, encoding="utf-8") as f:
        entries = json.load(f)

    print(f"Metadata : {meta_path.name}  ({len(entries)} entries)")

    # Collect unique image filenames
    filenames = list(dict.fromkeys(e["image_id"] for e in entries))
    print(f"Images   : {len(filenames)} unique filenames")

    print("Building image lookup ...")
    lookup = build_image_lookup(IMAGES_DIR)

    missing = []
    packed  = 0

    print(f"\nPacking → {out_path.name} ...")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # Add metadata JSON (always named metadata_merged.json inside zip)
        zf.write(meta_path, arcname="metadata_merged.json")

        for fn in tqdm.tqdm(filenames, desc="Images", unit="img"):
            src = lookup.get(nfc(fn)) or lookup.get(fn)
            if src is None:
                missing.append(fn)
                continue
            zf.write(src, arcname=f"images/{nfc(fn)}")
            packed += 1

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"\n{'='*50}")
    print(f"  Images packed  : {packed}")
    print(f"  Images missing : {len(missing)}")
    print(f"  Zip size       : {size_mb:.0f} MB")
    print(f"  Output         : {out_path}")

    if missing:
        print(f"\n  Missing files ({len(missing)} total, first 10):")
        for fn in missing[:10]:
            print(f"    {fn}")

    print("\nUpload heritagelens-data.zip to Google Drive, then run Colab.")


if __name__ == "__main__":
    main()
