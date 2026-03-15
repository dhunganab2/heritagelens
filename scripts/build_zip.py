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


def find_image(filename: str) -> Path | None:
    fn_nfc = nfc(filename)
    for d in IMAGES_DIR.iterdir():
        if not d.is_dir():
            continue
        for candidate in [d / filename, d / fn_nfc]:
            if candidate.exists():
                return candidate
    return None


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

    missing = []
    packed  = 0

    print(f"\nPacking → {out_path.name} ...")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # Add metadata JSON (always named metadata_merged.json inside zip)
        zf.write(meta_path, arcname="metadata_merged.json")

        for fn in tqdm.tqdm(filenames, desc="Images", unit="img"):
            src = find_image(fn)
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
        print(f"\n  ⚠ Missing files (first 10): {missing[:10]}")

    print("\nUpload heritagelens-data.zip to Google Drive, then run Colab.")


if __name__ == "__main__":
    main()
