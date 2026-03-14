#!/usr/bin/env python3
"""
Convert DANAM manifest.csv → metadata_danam.json for training.

Caption strategy — 3 captions per image:

  Cap 1  — Expanded DANAM image_caption
             DANAM captions are structured like:
               "Nārāyaṇa Mandira, toraṇa with struts, view from W"
               "view from W"
               "Bhīmasena Mandira, buffalo skulls above the door, view from E"
             We expand compass directions to words and restructure into a
             natural sentence, so every image gets a unique visual description:
               → "Toraṇa with struts at Nārāyaṇa Mandira, western view."
               → "Western view of Jogeśvara Mandira."
               → "Buffalo skulls above the door at Bhīmasena Mandira, eastern view."

  Cap 2  — First sentence of monument_description
             This is academic but monument-specific; it is shared by 2–3 images
             of the same monument and never generated from a template.
             Example: "The Nārāyaṇa temple at Dhālāchẽ Ṭola, Lalitpur, was
             originally constructed in the medieval period in the multi-tiered
             pagoda style."

  Cap 3  — Monument-type architectural sentence
             Based on detected monument type, specific enough to teach the model
             correct vocabulary (torana, struts, harmika, etc.)
"""

import csv
import json
import re
from collections import Counter
from pathlib import Path

# ── Compass direction expansion ───────────────────────────────────────────────
_COMPASS = {
    "N": "northern", "S": "southern", "E": "eastern", "W": "western",
    "NE": "northeastern", "NW": "northwestern",
    "SE": "southeastern", "SW": "southwestern",
    "NNE": "north-northeastern", "NNW": "north-northwestern",
    "SSE": "south-southeastern", "SSW": "south-southwestern",
    "ENE": "east-northeastern", "WNW": "west-northwestern",
    "ESE": "east-southeastern", "WSW": "west-southwestern",
}

# Regex for a compass suffix: ", view from W" / ", views from NW" / "from N"
_COMPASS_RE = re.compile(
    r",?\s*(?:views?\s+)?from\s+([NSEW]{1,3})\b.*$",
    re.IGNORECASE,
)

# Phrases that add no visual information
_FILLER_PHRASES = {
    "view", "lower view", "close view", "full view", "aerial view",
    "detail view", "close-up view", "historical image", "top-down view",
}


def _expand_caption(image_caption: str, monument_name: str) -> str:
    """
    Turn a structured DANAM caption into a natural English sentence.

    Examples
    --------
    "Nārāyaṇa Mandira, toraṇa with struts, view from W"
        → "Toraṇa with struts at Nārāyaṇa Mandira, western view."

    "Kṛṣṇa Mandira, upper part with pinnacle, view from E"
        → "Upper part with pinnacle at Kṛṣṇa Mandira, eastern view."

    "view from W"
        → "Western view of Jogeśvara Mandira."

    "Bhīmasena Mandira, buffalo skulls above the door, view form E"
        → "Buffalo skulls above the door at Bhīmasena Mandira, eastern view."

    "Thãhiti Caitya, aerial view, from S"
        → "Southern aerial view of Thãhiti Caitya."

    "Gaddi Baithak, views from W before and after restoration"
        → "Views of Gaddi Baithak from the west before and after restoration."
    """
    cap = image_caption.strip().rstrip(".")

    # Extract compass direction
    m = _COMPASS_RE.search(cap)
    direction_str = ""
    if m:
        dir_key = m.group(1).upper()
        direction_str = _COMPASS.get(dir_key, dir_key.lower())
        cap = cap[: m.start()].strip(" ,")

    # Strip monument_name prefix from the caption.
    # DANAM captions look like: "MonumentName, detail text, view from X"
    # The monument name may include parentheticals like "(before 608 CE)" that
    # are NOT in the caption prefix, so we match only the base name part.
    base_name = re.split(r"\s*[\(\[,]", monument_name)[0].strip()
    if base_name and cap.lower().startswith(base_name.lower()):
        cap = cap[len(base_name):].lstrip(" ,").strip()

    # Check if what's left is a filler phrase or empty
    cap_lower = cap.lower().strip()
    is_filler = not cap_lower or cap_lower in _FILLER_PHRASES

    safe_monument = monument_name.rstrip(".").strip()

    if is_filler:
        if direction_str:
            return f"{direction_str.capitalize()} view of {safe_monument}."
        return f"{safe_monument}."

    # Compose: detail + monument + direction
    detail = cap.rstrip(" ,").rstrip(".!?,")
    detail_cap = detail[:1].upper() + detail[1:] if detail else detail

    if direction_str:
        return f"{detail_cap} at {safe_monument}, {direction_str} view."
    return f"{detail_cap} at {safe_monument}."


# ── Monument type detection ───────────────────────────────────────────────────
_TYPE_PATTERNS = [
    (r"\bcaitya\b|\bchaity[ae]\b|\bchorten\b", "Stupa"),
    (r"\bstupa\b", "Stupa"),
    (r"\bbāhāḥ\b|\bbaha[hḥ]?\b|\bvihar[a]?\b|\bvihāra\b|\bmonastery\b", "Buddhist Monastery"),
    (r"\bpagoda\b", "Newari Pagoda"),
    (r"\bfountain\b|\bhiti\b|\bdhārā\b|\bspout\b|\bdhunge dhāra\b", "Water Fountain"),
    (r"\bpalace\b|\bdarbār\b|\bdurbar\b", "Palace"),
    (r"\bpillar\b|\bstambh[a]?\b|\bcolumn\b|\bpole\b", "Pillar"),
    (r"\bpond\b|\bpokharī\b|\btank\b", "Sacred Pond"),
    (r"\binscription\b|\babhilekh\b", "Inscription"),
    (r"\bsataḥ\b|\bsattal\b|\bphalcā\b|\brest house\b", "Rest House"),
    (r"\bmandir[a]?\b|\btemple\b|\bdev[aā]l[a]?\b|\bshrine\b|\bpīṭh[a]?\b", "Temple"),
]

# Cap 3 sentences per monument type — use domain vocabulary the model should learn
_TYPE_CAP3: dict[str, str] = {
    "Stupa": (
        "A Buddhist stupa or caitya — a hemispherical votive monument with a"
        " whitewashed dome, a square harmika, and a gilded spire — marking a"
        " sacred site in the Kathmandu Valley."
    ),
    "Buddhist Monastery": (
        "A traditional Nepali Buddhist monastery (bāhāḥ or bahī) built around a"
        " central courtyard with a main shrine, votive caityas, and intricate"
        " woodcarvings on windows and doorways."
    ),
    "Newari Pagoda": (
        "A Newari pagoda temple with two or three tiered roofs of fired clay"
        " tiles, carved wooden struts depicting deities, and an ornate toraṇa"
        " above the main entrance."
    ),
    "Temple": (
        "A traditional Hindu or Buddhist temple in Nepal with tiered roofs,"
        " carved wooden struts, and a gilded toraṇa or metal finial marking the"
        " sanctum."
    ),
    "Water Fountain": (
        "A traditional Newari stone water fountain (hiti or dhunge dhārā) with"
        " carved makara-head spouts fed by an ancient underground aquifer system,"
        " historically the main water source for nearby residents."
    ),
    "Palace": (
        "A historic palace or durbar complex built by the Malla or Shah kings,"
        " featuring multi-storey brick facades, carved wooden windows, and an"
        " ornate entrance courtyard."
    ),
    "Pillar": (
        "A stone or metal pillar erected in front of a temple, often bearing an"
        " inscription or a votive image of the deity to whom the adjacent shrine"
        " is dedicated."
    ),
    "Rest House": (
        "A traditional Newari phalcā (rest house or sattal) — an open pavilion"
        " with a tiered roof where travellers and residents could rest, often"
        " located at a road junction or temple entrance."
    ),
    "Sacred Pond": (
        "A sacred rectangular pond (pokharī) in the Kathmandu Valley, used for"
        " ritual bathing and water supply, often surrounded by shrines and"
        " bordered by stone ghāṭas."
    ),
    "Inscription": (
        "A stone inscription recording the foundation, renovation, or endowment"
        " of a monument, providing a rare primary historical source for the dating"
        " of Nepali heritage sites."
    ),
}
_TYPE_CAP3_FALLBACK = (
    "A historic heritage monument in the Kathmandu Valley representing Nepali"
    " architectural and cultural traditions spanning the medieval Malla period."
)


def _detect_type(name: str, description: str) -> str:
    combined = f"{name} {description}".lower()
    for pattern, label in _TYPE_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return label
    return "Heritage Monument"


def _first_sentence(text: str, max_len: int = 220) -> str:
    """Return the first complete sentence of text, capped at max_len chars."""
    if not text:
        return ""
    # Match up to the first sentence-ending punctuation
    m = re.match(r"([^.!?]+[.!?])", text.strip())
    sentence = m.group(1).strip() if m else text.strip()
    if len(sentence) > max_len:
        sentence = sentence[:max_len].rsplit(" ", 1)[0] + "."
    return sentence


def _build_captions(
    image_caption: str,
    monument_name: str,
    description: str,
    cultural_label: str,
) -> list[str]:
    # Cap 1: expanded visual description
    cap1 = _expand_caption(image_caption, monument_name)

    # Cap 2: first sentence of monument description (academic, specific per monument)
    first_sent = _first_sentence(description)
    if first_sent and len(first_sent) >= 20:
        cap2 = first_sent
    else:
        cap2 = f"{monument_name} is a historic {cultural_label} in the Kathmandu Valley, Nepal."

    # Cap 3: monument-type architectural sentence
    cap3 = _TYPE_CAP3.get(cultural_label, _TYPE_CAP3_FALLBACK)

    return [cap1, cap2, cap3]


# ── Main conversion ───────────────────────────────────────────────────────────

def convert_danam_manifest(
    manifest_path: Path,
    images_dir: Path,
    output_path: Path,
) -> list[dict]:
    """Read DANAM manifest.csv and produce metadata_danam.json."""
    rows: list[dict] = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    data: list[dict] = []
    skipped: list[str] = []
    type_counts: Counter = Counter()

    for idx, row in enumerate(rows):
        filename      = row["filename"].strip()
        monument_name = row["monument_name"].strip()
        image_caption = row.get("image_caption", "").strip()
        description   = row.get("monument_description", "").strip()

        # Find image file under any sub-directory
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
        captions = _build_captions(image_caption, monument_name, description, cultural_label)

        entry = {
            "image_id":     filename,
            "category":     image_path.parent.name,
            "cultural_label": cultural_label,
            "monument_name": monument_name,
            "source":       "danam",
            "captions":     captions,
        }
        data.append(entry)
        type_counts[cultural_label] += 1

        if (idx + 1) % 100 == 0:
            print(f"  Processed {idx + 1} / {len(rows)} rows…")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(data)} images written, {len(skipped)} skipped (missing file).")
    print("Monument type distribution:", dict(type_counts))
    if skipped[:5]:
        print("First skipped:", skipped[:5])
    return data


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert DANAM manifest.csv → metadata_danam.json"
    )
    parser.add_argument("--manifest",   default="data/raw/danam/manifest.csv")
    parser.add_argument("--images-dir", default="data/raw/danam/images")
    parser.add_argument("--output",     default="data/processed/metadata_danam.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_path = root / args.manifest
    images_dir    = root / args.images_dir
    output_path   = root / args.output

    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return

    print("Converting DANAM manifest.csv → metadata_danam.json …")
    convert_danam_manifest(manifest_path, images_dir, output_path)
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
