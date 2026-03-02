#!/usr/bin/env python3
"""
Convert manifest.csv → metadata.json for training.

Caption strategy (3 captions per image):
  1. Real Wikimedia ImageDescription  (if available and good English)
     OR  a template like "A Stupa in Nepal."
  2. Architectural detail sentence     (template, based on cultural_label)
  3. Cultural/historical context       (template, based on cultural_label)
"""

import csv
import json
import re
from pathlib import Path
from collections import Counter


# Non-English archive/metadata keywords commonly found in Wikimedia descriptions
_NON_ENGLISH_MARKERS = [
    "Collectie", "Archief", "Bestanddeelnr", "Beschrijving", "Trefwoorden",
    "Fotograaf", "Auteursrechthebbende", "Inventarisnummer", "Reportage",
    "Beschreibung", "Quelle", "Urheber", "Genehmigung", "Lizenz",
    "Auteur", "Licence", "Permission", "bekijk toegang", "Bestand", "Datum :",
]


def _is_good_english(text: str, min_len: int = 25) -> bool:
    """Return True only if the description is usable English."""
    if not text or len(text) < min_len:
        return False
    if text.startswith("http://") or text.startswith("https://"):
        return False
    non_ascii = sum(1 for c in text if ord(c) > 127)
    if non_ascii / len(text) > 0.15:
        return False
    for marker in _NON_ENGLISH_MARKERS:
        if marker in text:
            return False
    return True


def map_cultural_label(category: str, page_title: str, filename: str) -> str:
    """Map category + filename keywords to a specific cultural label."""
    text = (page_title + " " + filename).lower()

    if category == "Swayambhunath":
        return "Stupa"
    if category == "Boudhanath":
        return "Stupa"
    if category == "Pashupatinath_Temple":
        return "Hindu Temple"
    if category == "Thangka":
        return "Thangka Painting"
    if category == "Tibetan_Buddhist_art":
        return "Tibetan Art"
    if category == "Traditional_clothing_of_Nepal":
        return "Traditional Clothing"

    if "stupa" in text or "boudha" in text:
        return "Stupa"
    if "pagoda" in text or "nyatapola" in text:
        return "Newari Pagoda"
    if category == "Buddhist_temples_in_Nepal":
        return "Buddhist Temple"
    if category == "Hindu_temples_in_Nepal":
        return "Hindu Temple"

    return category.replace("_", " ").title()


def generate_captions(
    page_title: str,
    category: str,
    cultural_label: str,
    description: str = "",
) -> list[str]:
    """Return exactly 3 captions for one image.

    Caption 1  — Real Wikimedia description (preferred) or template fallback.
    Caption 2  — Architectural detail (template).
    Caption 3  — Cultural/historical context (template).
    """
    captions: list[str] = []

    # --- Caption 1: real description or template ---
    if _is_good_english(description):
        # Ensure it ends with a period
        cap1 = description.rstrip(".!?,") + "."
        captions.append(cap1)
    else:
        captions.append(f"A {cultural_label} in Nepal.")

    # --- Caption 2: architectural detail ---
    if "Stupa" in cultural_label:
        captions.append(
            "A white dome stupa with traditional Buddhist architecture, "
            "often featuring the eyes of Buddha and prayer flags."
        )
    elif "Pagoda" in cultural_label or "Temple" in cultural_label:
        captions.append(
            f"A {cultural_label} with traditional Nepali architecture, "
            "tiered roofs, and intricate wood or stone carvings."
        )
    elif "Thangka" in cultural_label or "Tibetan" in cultural_label:
        captions.append(
            "Traditional Buddhist artwork with detailed iconography and symbolic imagery."
        )
    elif "Traditional Clothing" in cultural_label:
        captions.append(
            "Traditional Nepali dress or ornamentation reflecting local cultural heritage."
        )
    else:
        captions.append(f"Traditional {cultural_label} architecture or craft in Nepal.")

    # --- Caption 3: cultural / historical context ---
    if "Stupa" in cultural_label:
        captions.append(
            "An ancient Buddhist monument of deep significance to Nepali "
            "and Tibetan Buddhist tradition."
        )
    elif "Temple" in cultural_label:
        captions.append(
            "A place of worship and cultural significance in Nepal's heritage landscape."
        )
    elif "Thangka" in cultural_label or "Tibetan" in cultural_label:
        captions.append("Buddhist devotional art with deep religious and cultural meaning.")
    else:
        captions.append(
            "An example of Nepali cultural heritage and traditional craftsmanship."
        )

    return captions[:3]


def convert_manifest_to_json(
    manifest_path: Path,
    images_dir: Path,
    output_path: Path,
) -> list[dict]:
    """Read manifest.csv and write metadata.json. Skips rows with missing images."""
    data: list[dict] = []
    skipped: list[str] = []
    category_counts: Counter = Counter()
    real_caption_count = 0

    with open(manifest_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            filename = row["filename"].strip('"')
            category = row["category"].strip()
            page_title = row.get("page_title", "").strip('"')
            description = row.get("description", "").strip()

            category_dir = images_dir / f"Category:{category}"
            image_path = category_dir / filename

            if not image_path.exists():
                skipped.append(filename)
                continue

            cultural_label = map_cultural_label(category, page_title, filename)
            captions = generate_captions(page_title, category, cultural_label, description)

            if _is_good_english(description):
                real_caption_count += 1

            entry = {
                "image_id": filename,
                "category": category,
                "cultural_label": cultural_label,
                "captions": captions,
            }
            data.append(entry)
            category_counts[category] += 1

            if (idx + 1) % 100 == 0:
                print(f"  Processed {idx + 1} rows...")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    total = len(data)
    template_count = total - real_caption_count
    print(f"\nDone. {total} images written, {len(skipped)} skipped (missing file).")
    print(f"  Real Wikimedia captions : {real_caption_count} / {total} ({100*real_caption_count//max(total,1)}%)")
    print(f"  Template fallback used  : {template_count} / {total}")
    print("Per-category counts:", dict(category_counts))
    if skipped[:5]:
        print("First skipped:", skipped[:5])
    return data


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Convert manifest.csv to metadata.json")
    parser.add_argument("--manifest", default="data/raw/wikimedia/manifest.csv")
    parser.add_argument("--images-dir", default="data/raw/wikimedia/images")
    parser.add_argument("--output", default="data/processed/metadata.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_path = root / args.manifest
    images_dir = root / args.images_dir
    output_path = root / args.output

    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return

    print("Converting manifest.csv → metadata.json ...")
    convert_manifest_to_json(manifest_path, images_dir, output_path)
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
