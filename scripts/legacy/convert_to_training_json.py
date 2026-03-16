#!/usr/bin/env python3
"""
Convert Wikimedia manifest.csv → metadata.json for training.

Caption strategy — 3 tiers based on what text is available:

  Tier A  (197 images)  — unique, image-specific Wikimedia description
    Cap 1: The real description (clean, period-terminated)
    Cap 2: Category-specific architectural sentence (one per category, not per type)
    Cap 3: Category-specific cultural/historical sentence

  Tier B  (473 images)  — duplicate description (shared by many images)
    Cap 1: Filename-parsed visual hint  e.g. "Nyatapola Temple, Bhaktapur, Nepal."
    Cap 2: The shared description (category-accurate even if not image-specific)
    Cap 3: Category-specific cultural/historical sentence

  Tier C  (254 images)  — no usable description at all
    Cap 1: Best-effort from filename + category
    Cap 2: Category-specific architectural sentence
    Cap 3: Category-specific cultural/historical sentence

The key improvement over the old script is that Cap 2 and Cap 3 are
per-CATEGORY (not per monument-type), so all 9 categories produce
distinct sentences rather than having every stupa share the same template.
"""

import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

# ── Non-English metadata markers ─────────────────────────────────────────────
_NON_ENGLISH_MARKERS = [
    "Collectie", "Archief", "Bestanddeelnr", "Beschrijving", "Trefwoorden",
    "Fotograaf", "Auteursrechthebbende", "Inventarisnummer", "Reportage",
    "Beschreibung", "Quelle", "Urheber", "Genehmigung", "Lizenz",
    "Auteur", "bekijk toegang", "Bestand", "Datum :",
    "Albumblad", "Linksboven",
]

# ── Per-category sentence pairs (architectural | cultural) ───────────────────
# These are specific to each location — NOT generic per monument-type.
_CATEGORY_SENTENCES: dict[str, tuple[str, str]] = {
    "Swayambhunath": (
        "A whitewashed Buddhist stupa with the painted all-seeing eyes of Buddha on"
        " the harmika, prayer flags stretching outward, and a gilded spire rising"
        " above the dome.",
        "Swayambhunath, known as the Monkey Temple, is one of the oldest and most"
        " sacred Buddhist sites in Nepal, perched atop a hill overlooking the"
        " Kathmandu Valley.",
    ),
    "Boudhanath": (
        "A massive hemispherical stupa with a whitewashed dome, a square harmika,"
        " and the painted all-seeing eyes of Buddha below a gilded spire.",
        "Boudhanath Stupa is one of the largest stupas in the world and the centre"
        " of Tibetan Buddhism in Nepal, a UNESCO World Heritage Site in the"
        " Kathmandu Valley.",
    ),
    "Pashupatinath": (
        "A multi-tiered Hindu temple with a gilded copper roof, carved wooden"
        " struts, and an ornate entrance facing the Bagmati River.",
        "Pashupatinath Temple is Nepal's most sacred Hindu shrine, dedicated to"
        " Lord Shiva, located on the banks of the Bagmati River in Kathmandu.",
    ),
    "Patan_Durbar_Square": (
        "A traditional Newari pagoda-style temple with layered brick facades,"
        " carved wooden struts and torana, set within the royal square of Patan"
        " (Lalitpur).",
        "Patan Durbar Square is one of three medieval royal squares in the"
        " Kathmandu Valley, renowned for its exceptional Newari architecture and"
        " medieval Hindu and Buddhist temples, a UNESCO World Heritage Site.",
    ),
    "Bhaktapur_Durbar_Square": (
        "A historic temple or palace structure with traditional brick masonry,"
        " tiered roofs, and carved wooden elements in the Newari architectural"
        " style.",
        "Bhaktapur Durbar Square is a well-preserved medieval royal complex in the"
        " Kathmandu Valley, famous for its Newari craftsmanship and the 55-Window"
        " Palace, a UNESCO World Heritage Site.",
    ),
    "Durbar_Square_temples_(Kathmandu)": (
        "A Newari pagoda-style temple with multi-tiered roofs, intricate"
        " woodcarvings on the struts and torana, rising from the historic Hanuman"
        " Dhoka palace square in Kathmandu.",
        "Hanuman Dhoka Durbar Square in Kathmandu is a historic royal palace"
        " complex with numerous temples and monuments built between the 12th and"
        " 18th centuries by the Malla kings.",
    ),
    "Changu_Narayan_Temple": (
        "A two-tiered Newari pagoda with detailed stone and wooden carvings,"
        " decorated struts depicting deities, and a gilded metal torana above the"
        " main entrance.",
        "Changu Narayan Temple is one of the oldest surviving temples in Nepal,"
        " dedicated to Vishnu, located east of Kathmandu and recognised as a"
        " UNESCO World Heritage Site.",
    ),
    "Hindu_temples_in_Nepal": (
        "A traditional Hindu temple with tiered roofs, carved wooden struts, and"
        " ornate stone or metal decorations characteristic of Nepali religious"
        " architecture.",
        "A historic Hindu place of worship reflecting Nepal's rich tradition of"
        " temple architecture and devotion across the hills and valleys of the"
        " country.",
    ),
    "Buddhist_temples_in_Nepal": (
        "A Buddhist shrine or monastery with traditional Nepali architectural"
        " features, including a whitewashed stupa, prayer flags, and carved stone"
        " or wooden decorations.",
        "A Buddhist monument in Nepal, reflecting the country's deep Buddhist"
        " heritage along the ancient Himalayan trade and pilgrimage routes.",
    ),
}

# Fallback sentences for any category not listed above
_FALLBACK_SENTENCES = (
    "A traditional heritage structure with Nepali architectural features including"
    " carved woodwork, tiered roofs, and ornate religious decorations.",
    "A historic monument representing Nepal's rich cultural heritage and"
    " architectural traditions spanning centuries of artistic craftsmanship.",
)


def _category_sentences(category: str) -> tuple[str, str]:
    return _CATEGORY_SENTENCES.get(category, _FALLBACK_SENTENCES)


# ── Text helpers ──────────────────────────────────────────────────────────────

def _is_good_english(text: str, min_len: int = 25) -> bool:
    """Return True only if the description is usable English."""
    if not text or len(text.strip()) < min_len:
        return False
    t = text.strip()
    if t.startswith("http://") or t.startswith("https://"):
        return False
    non_ascii = sum(1 for c in t if ord(c) > 127)
    if non_ascii / len(t) > 0.15:
        return False
    for marker in _NON_ENGLISH_MARKERS:
        if marker in t:
            return False
    return True


def _clean_description(text: str) -> str:
    """Strip leading/trailing whitespace and ensure a terminal period."""
    t = text.strip().rstrip(".!?,") + "."
    # Collapse internal whitespace
    t = re.sub(r"\s{2,}", " ", t)
    return t


def _filename_to_caption(page_title: str, category: str) -> str:
    """
    Derive a best-effort visual caption from a Wikimedia page_title.

    'File:Nyatapola Temple - east view.jpg'  →  'Nyatapola Temple - east view.'
    'File:DSC_1234.jpg'                      →  'A historic monument at Bhaktapur Durbar Square, Nepal.'
    """
    # Remove 'File:' prefix and extension
    title = re.sub(r"^File:", "", page_title, flags=re.IGNORECASE)
    title = re.sub(r"\.[a-zA-Z]{2,5}$", "", title)

    # Remove camera model codes
    title = re.sub(r"\b(DSC[F]?\d+|IMG_\d+|P\d{6,}|DSCF?\d+|MVC-?\d+)\b", "", title, flags=re.IGNORECASE)
    # Remove ISO date patterns
    title = re.sub(r"\b\d{4}[-_]\d{2}[-_]\d{2}\b", "", title)
    # Remove bracketed numbers and panoramio suffix
    title = re.sub(r"\(\d+\)", "", title)
    title = re.sub(r"\s*-\s*panoramio\s*$", "", title, flags=re.IGNORECASE)
    # Remove trailing numbers
    title = re.sub(r"\s+\d+$", "", title)
    # Replace underscores AND hyphens with spaces, then collapse whitespace
    title = re.sub(r"[_\-]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    # Check if what remains has CJK (would produce garbage)
    for ch in title:
        name = unicodedata.name(ch, "")
        if "HIRAGANA" in name or "KATAKANA" in name or "CJK" in name:
            title = ""
            break

    # Check for Dutch/archival language markers
    for marker in _NON_ENGLISH_MARKERS:
        if marker in title:
            title = ""
            break

    cat_name = category.replace("_", " ")

    if len(title) < 5:
        return f"A historic monument at {cat_name}, Nepal."

    if len(title) <= 20:
        return f"{title} at {cat_name}, Nepal."

    return title.rstrip(".!?,") + "."


def _map_cultural_label(category: str, page_title: str, filename: str) -> str:
    """Map category + filename keywords to a cultural label."""
    text = (page_title + " " + filename).lower()
    if category in ("Swayambhunath", "Boudhanath"):
        return "Stupa"
    if category == "Pashupatinath":
        return "Hindu Temple"
    if "stupa" in text or "boudha" in text or "chorten" in text:
        return "Stupa"
    if "pagoda" in text or "nyatapola" in text:
        return "Newari Pagoda"
    if category == "Buddhist_temples_in_Nepal":
        return "Buddhist Temple"
    if category == "Hindu_temples_in_Nepal":
        return "Hindu Temple"
    if category == "Changu_Narayan_Temple":
        return "Hindu Temple"
    return category.replace("_", " ").title()


# ── Caption assembly ──────────────────────────────────────────────────────────

def _build_captions(
    page_title: str,
    category: str,
    cultural_label: str,
    description: str,
    desc_is_unique: bool,
) -> list[str]:
    """
    Return exactly 3 captions based on description availability.

    Tier A: description is good English AND unique across the manifest.
    Tier B: description is good English BUT shared by multiple images.
    Tier C: no usable description.
    """
    arch_sent, cultural_sent = _category_sentences(category)
    desc_ok = _is_good_english(description)

    if desc_ok and desc_is_unique:
        # ── Tier A ───────────────────────────────────────────────────────────
        cap1 = _clean_description(description)
        cap2 = arch_sent
        cap3 = cultural_sent

    elif desc_ok and not desc_is_unique:
        # ── Tier B ───────────────────────────────────────────────────────────
        # The description is shared by many images so we cannot use it as Cap 1
        # (it would produce hundreds of identical Cap 1 strings).
        # Instead use the architectural sentence as Cap 1 — it's category-specific
        # and guaranteed to be different from Cap 2 (the shared description).
        cap1 = arch_sent
        cap2 = _clean_description(description)   # category-accurate shared description
        cap3 = cultural_sent

    else:
        # ── Tier C ───────────────────────────────────────────────────────────
        cap1 = _filename_to_caption(page_title, category)
        # If the filename gave us a short monument name, extend with type for context
        if len(cap1.split()) < 4:
            cap1 = cap1.rstrip(".") + f", a {cultural_label} in Nepal."
        cap2 = arch_sent
        cap3 = cultural_sent

    return [cap1, cap2, cap3]


# ── Main conversion ───────────────────────────────────────────────────────────

def convert_manifest_to_json(
    manifest_path: Path,
    images_dir: Path,
    output_path: Path,
) -> list[dict]:
    """Read manifest.csv and write metadata.json."""
    rows: list[dict] = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Pre-compute description uniqueness
    desc_counts: Counter = Counter()
    for row in rows:
        desc = row.get("description", "").strip()
        if _is_good_english(desc):
            desc_counts[desc] += 1

    data: list[dict] = []
    skipped: list[str] = []
    tier_counts: Counter = Counter()

    for idx, row in enumerate(rows):
        filename = row["filename"].strip().strip('"')
        category = row["category"].strip()
        page_title = row.get("page_title", "").strip().strip('"')
        description = row.get("description", "").strip()

        category_dir = images_dir / f"Category:{category}"
        image_path = category_dir / filename
        if not image_path.exists():
            skipped.append(filename)
            continue

        cultural_label = _map_cultural_label(category, page_title, filename)
        desc_ok = _is_good_english(description)
        desc_is_unique = desc_ok and desc_counts.get(description.strip(), 0) == 1

        if desc_ok and desc_is_unique:
            tier_counts["A (unique desc)"] += 1
        elif desc_ok:
            tier_counts["B (duplicate desc)"] += 1
        else:
            tier_counts["C (no desc)"] += 1

        captions = _build_captions(
            page_title, category, cultural_label, description, desc_is_unique
        )

        entry = {
            "image_id": filename,
            "category": category,
            "cultural_label": cultural_label,
            "source": "wikimedia",
            "captions": captions,
        }
        data.append(entry)

        if (idx + 1) % 200 == 0:
            print(f"  Processed {idx + 1} / {len(rows)} rows…")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(data)} images written, {len(skipped)} skipped (missing file).")
    print("Caption tier breakdown:")
    for tier, count in sorted(tier_counts.items()):
        print(f"  {tier}: {count}")
    if skipped[:5]:
        print("First skipped:", skipped[:5])
    return data


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Convert Wikimedia manifest.csv → metadata.json")
    parser.add_argument("--manifest",   default="data/raw/wikimedia/manifest.csv")
    parser.add_argument("--images-dir", default="data/raw/wikimedia/images")
    parser.add_argument("--output",     default="data/processed/metadata.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_path = root / args.manifest
    images_dir    = root / args.images_dir
    output_path   = root / args.output

    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return

    print("Converting Wikimedia manifest.csv → metadata.json …")
    convert_manifest_to_json(manifest_path, images_dir, output_path)
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
