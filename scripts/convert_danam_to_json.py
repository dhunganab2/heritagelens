#!/usr/bin/env python3
"""
Convert DANAM manifest.csv → metadata_danam.json for training.

Caption strategy (3 captions per image):
  1. Cleaned image caption from DANAM (describes what's in the photo)
  2. Monument name + description sentence (provides context)
  3. Architectural/cultural template based on monument type keywords
"""

import csv
import json
import re
from collections import Counter
from pathlib import Path


# ── Monument type detection from name / description keywords ──────────────────

_TYPE_PATTERNS = [
    (r"\bstupa\b|\bcaitya\b|\bchaity[ae]\b", "Stupa"),
    (r"\bbāhāḥ\b|\bbaha[hḥ]?\b|\bvihar[a]?\b|\bvihāra\b|\bmonastery\b", "Buddhist Monastery"),
    (r"\bpagoda\b", "Newari Pagoda"),
    (r"\btemple\b|\bmandir[a]?\b|\bdev[aā]l[a]?\b", "Temple"),
    (r"\bshrine\b|\bpīṭh[a]?\b", "Shrine"),
    (r"\bfountain\b|\bhiti\b|\bdhārā\b|\bspout\b", "Water Fountain"),
    (r"\bpalace\b|\bdarbār\b|\bdurbar\b", "Palace"),
    (r"\bstatue\b|\bsculpture\b|\bimage\b|\bmūrti\b", "Sculpture"),
    (r"\binscription\b|\babhilekh\b", "Inscription"),
    (r"\bgate\b|\bdhok[āa]\b|\bentrance\b", "Gate"),
    (r"\bpond\b|\bpokharī\b|\btank\b", "Sacred Pond"),
    (r"\bpillar\b|\bstambh[a]?\b|\bcolumn\b", "Pillar"),
    (r"\bbouddha\b|\bbuddhist\b|\bbuddha\b", "Buddhist Monument"),
    (r"\bśiva\b|\bshiva\b|\bmahadeva\b|\bmaheśvara\b", "Hindu Temple"),
]


def _detect_type(name: str, description: str) -> str:
    """Infer a cultural-label from monument name and description keywords."""
    combined = f"{name} {description}".lower()
    for pattern, label in _TYPE_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return label
    return "Heritage Monument"


def _first_sentence(text: str, max_len: int = 200) -> str:
    """Return the first sentence of a text, capped at max_len chars."""
    if not text:
        return ""
    match = re.match(r"([^.!?]+[.!?])", text)
    sentence = match.group(1).strip() if match else text.strip()
    if len(sentence) > max_len:
        sentence = sentence[:max_len].rsplit(" ", 1)[0] + "."
    return sentence


def generate_danam_captions(
    image_caption: str,
    monument_name: str,
    description: str,
    cultural_label: str,
) -> list[str]:
    """Return up to 3 captions for one DANAM image."""
    captions: list[str] = []

    if image_caption and len(image_caption) >= 10:
        cap = image_caption.rstrip(".!?,") + "."
        captions.append(cap)
    else:
        captions.append(f"{monument_name}, a {cultural_label} in Nepal.")

    short_desc = _first_sentence(description)
    if short_desc and len(short_desc) >= 20:
        captions.append(short_desc)
    else:
        captions.append(f"{monument_name} is a historic {cultural_label} in Nepal.")

    if "Stupa" in cultural_label or "Caitya" in cultural_label:
        captions.append(
            "A Buddhist stupa with traditional Nepali architecture "
            "and religious significance."
        )
    elif "Monastery" in cultural_label or "Bāhāḥ" in cultural_label:
        captions.append(
            "A traditional Buddhist monastery complex in the Kathmandu Valley "
            "with ornate woodcarvings and courtyards."
        )
    elif "Temple" in cultural_label or "Pagoda" in cultural_label:
        captions.append(
            f"A {cultural_label} featuring traditional Nepali architecture "
            "with tiered roofs and intricate carvings."
        )
    elif "Fountain" in cultural_label:
        captions.append(
            "A traditional stone water spout, an important feature of "
            "Nepali urban heritage and water supply systems."
        )
    elif "Palace" in cultural_label:
        captions.append(
            "A historic palace structure in Nepal reflecting the architectural "
            "grandeur of the Malla or Rana era."
        )
    elif "Sculpture" in cultural_label or "Pillar" in cultural_label:
        captions.append(
            "An ancient stone sculpture or carving of religious and cultural "
            "significance in Nepal."
        )
    else:
        captions.append(
            f"A historic {cultural_label} representing Nepali cultural heritage."
        )

    return captions[:3]


def convert_danam_manifest(
    manifest_path: Path,
    images_dir: Path,
    output_path: Path,
) -> list[dict]:
    """Read DANAM manifest.csv and produce metadata_danam.json."""
    data: list[dict] = []
    skipped: list[str] = []
    type_counts: Counter = Counter()

    with open(manifest_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            filename = row["filename"].strip()
            monument_name = row["monument_name"].strip()
            image_caption = row.get("image_caption", "").strip()
            description = row.get("monument_description", "").strip()
            monument_id = row.get("monument_id", "").strip()

            image_path = None
            for d in images_dir.iterdir():
                if d.is_dir():
                    candidate = d / filename
                    if candidate.exists():
                        image_path = candidate
                        break

            if image_path is None:
                skipped.append(filename)
                continue

            cultural_label = _detect_type(monument_name, description)
            captions = generate_danam_captions(
                image_caption, monument_name, description, cultural_label
            )

            parent_dir = image_path.parent.name

            entry = {
                "image_id": filename,
                "category": parent_dir,
                "cultural_label": cultural_label,
                "monument_name": monument_name,
                "source": "danam",
                "captions": captions,
            }
            data.append(entry)
            type_counts[cultural_label] += 1

            if (idx + 1) % 100 == 0:
                print(f"  Processed {idx + 1} rows...")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(data)} images written, {len(skipped)} skipped (missing file).")
    print("Type distribution:", dict(type_counts))
    if skipped[:5]:
        print("First skipped:", skipped[:5])
    return data


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert DANAM manifest.csv to metadata_danam.json"
    )
    parser.add_argument("--manifest", default="data/raw/danam/manifest.csv")
    parser.add_argument("--images-dir", default="data/raw/danam/images")
    parser.add_argument("--output", default="data/processed/metadata_danam.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_path = root / args.manifest
    images_dir = root / args.images_dir
    output_path = root / args.output

    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return

    print("Converting DANAM manifest.csv → metadata_danam.json ...")
    convert_danam_manifest(manifest_path, images_dir, output_path)
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
