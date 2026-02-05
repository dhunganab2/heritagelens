#!/usr/bin/env python3
"""
Convert manifest.csv to metadata.json for training.
Generates cultural_label and 3 captions per image from page_title and category.
"""

import csv
import json
import re
from pathlib import Path
from collections import Counter


def map_cultural_label(category: str, page_title: str, filename: str) -> str:
    """Map category and filename/page_title to a specific cultural label."""
    text = (page_title + " " + filename).lower()

    # Category-first for specific categories
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

    # Keyword-based for Buddhist/Hindu temples
    if "stupa" in text or "boudha" in text:
        return "Stupa"
    if "pagoda" in text or "nyatapola" in text:
        return "Newari Pagoda"
    if category == "Buddhist_temples_in_Nepal":
        return "Buddhist Temple"
    if category == "Hindu_temples_in_Nepal":
        return "Hindu Temple"

    # Fallback
    return category.replace("_", " ").title()


def clean_page_title(page_title: str) -> str:
    """Extract descriptive text from page title (remove File: and extension)."""
    title = page_title.replace("File:", "").strip()
    title = re.sub(r"\.[a-zA-Z]{3,4}$", "", title)
    return title


def generate_captions(page_title: str, category: str, cultural_label: str) -> list[str]:
    """Generate exactly 3 captions: general, architectural, cultural."""
    captions = []
    clean_title = clean_page_title(page_title)

    # Caption 1: General description (use page_title if descriptive)
    if len(clean_title) > 25 and " " in clean_title:
        cap1 = clean_title.rstrip(".") + "."
        captions.append(cap1)
    else:
        captions.append(f"A {cultural_label} in Nepal.")

    # Caption 2: Architectural details
    if "Stupa" in cultural_label:
        captions.append(
            "A white dome stupa with traditional Buddhist architecture, often featuring the eyes of Buddha and prayer flags."
        )
    elif "Pagoda" in cultural_label or "Temple" in cultural_label:
        captions.append(
            f"A {cultural_label} with traditional Nepali architecture, tiered roofs, and intricate wood or stone carvings."
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

    # Caption 3: Cultural/historical context
    if "Stupa" in cultural_label:
        captions.append(
            "An ancient Buddhist monument significant to Nepali and Tibetan Buddhist tradition."
        )
    elif "Temple" in cultural_label:
        captions.append(
            "A place of worship and cultural significance in Nepal's heritage landscape."
        )
    elif "Thangka" in cultural_label or "Tibetan" in cultural_label:
        captions.append(
            "Buddhist devotional art with deep religious and cultural meaning."
        )
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
    """Convert manifest.csv to metadata.json. Skip rows where image is missing."""
    data = []
    skipped = []
    category_counts: Counter = Counter()

    with open(manifest_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            filename = row["filename"].strip('"')
            category = row["category"].strip()
            page_title = row.get("page_title", "").strip('"')

            category_dir = images_dir / f"Category:{category}"
            image_path = category_dir / filename

            if not image_path.exists():
                skipped.append(filename)
                continue

            cultural_label = map_cultural_label(category, page_title, filename)
            captions = generate_captions(page_title, category, cultural_label)

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

    print(f"Processed {len(data)} images, skipped {len(skipped)} (missing file).")
    if skipped and len(skipped) <= 5:
        print(f"Skipped: {skipped}")
    elif skipped:
        print(f"First 5 skipped: {skipped[:5]} ...")
    print("Per-category counts:", dict(category_counts))
    return data


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Convert manifest.csv to metadata.json")
    parser.add_argument(
        "--manifest",
        default="data/raw/wikimedia/manifest.csv",
        help="Path to manifest.csv",
    )
    parser.add_argument(
        "--images-dir",
        default="data/raw/wikimedia/images",
        help="Directory containing Category:*/ subdirs",
    )
    parser.add_argument(
        "--output",
        default="data/processed/metadata.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_path = root / args.manifest
    images_dir = root / args.images_dir
    output_path = root / args.output

    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return

    print("Converting manifest to metadata.json...")
    convert_manifest_to_json(manifest_path, images_dir, output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
