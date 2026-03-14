#!/usr/bin/env python3
"""
Convert DANAM manifest.csv (v3) → metadata_danam.json for training.

EXTERIOR images get 2 training captions:
  Cap 1: Architecture-derived visual description
         "A 3-storey Buddhist tiered temple with a hip roof, 32 wooden struts,
          traditional brick walls, and 4 doors."
  Cap 2: First sentence of monument_description, or image view caption if
         the description is missing.

  If the DANAM image_caption is descriptive (>4 words, not just "view from W"),
  it is used as an additional Cap 3 (view description).

OBJECT images get 2 training captions:
  Cap 1: DANAM object caption expanded with material/type
         "Gilt wooden and copper toraṇa (tympanum) at Jogeśvara Mandira."
  Cap 2: Structured material + type + position description.

Cap 3 (templated Name,Type,Nepal) is always excluded from training — it caused
mode collapse in earlier runs.
"""

import csv
import json
import re
from collections import Counter
from pathlib import Path


# ── Constants ──────────────────────────────────────────────────────────────────

_COMPASS = {
    "N": "northern", "S": "southern", "E": "eastern", "W": "western",
    "NE": "northeastern", "NW": "northwestern",
    "SE": "southeastern", "SW": "southwestern",
}

_COMPASS_RE = re.compile(
    r",?\s*(?:views?\s+)?(?:from\s+)?([NSEW]{1,3})\s*$",
    re.IGNORECASE,
)

_OBJECT_SENTENCES = {
    "toraṇa": (
        "A toraṇa is a decorative carved arch above a temple doorway, "
        "typically depicting deities, mythical creatures, and floral motifs "
        "in wood or metal."
    ),
    "torana": (
        "A torana is a carved decorative gateway arch above a Nepali temple "
        "doorway, depicting deities and mythical figures in wood or gilded metal."
    ),
    "statue": (
        "A devotional statue at a Nepali temple, typically carved in stone "
        "or cast in metal, representing a deity or guardian figure."
    ),
    "bell": (
        "A temple bell, traditionally cast in bronze, hung at the entrance "
        "and rung by devotees before worship."
    ),
    "pillar": (
        "A stone or metal pillar erected in front of a temple, often bearing "
        "an inscription or a votive image of the deity."
    ),
    "caitya": (
        "A votive caitya (miniature stupa), a hemispherical stone monument "
        "marking a sacred spot within a monastery courtyard."
    ),
    "liṅga": (
        "A śivaliṅga, the aniconic representation of Śiva, typically "
        "carved in stone and housed in the sanctum of a Śaiva temple."
    ),
    "shrine": (
        "A subsidiary shrine within a temple complex, housing a deity "
        "or sacred object."
    ),
    "relief": (
        "A carved stone or wooden relief panel depicting religious iconography, "
        "mounted on the exterior wall of a Nepali temple."
    ),
    "platform": (
        "A raised stone platform in front of a temple, used for rituals, "
        "community gatherings, and memorial rites."
    ),
}

_OBJECT_SENTENCE_DEFAULT = (
    "A traditional architectural or devotional element at a Nepali heritage "
    "monument in the Kathmandu Valley."
)


# ── Text helpers ───────────────────────────────────────────────────────────────

def _expand_direction(caption: str) -> str:
    """Replace trailing compass abbreviation with full word."""
    m = _COMPASS_RE.search(caption)
    if m:
        key  = m.group(1).upper()
        word = _COMPASS.get(key, key.lower())
        return caption[:m.start()].strip(", ") + f", {word} view"
    m2 = re.search(r",?\s*view from ([\w-]+)\s*$", caption, re.IGNORECASE)
    if m2:
        return caption[:m2.start()].strip(", ") + f", {m2.group(1)} view"
    return caption


def _humanize_materials(raw: str) -> str:
    """'Wood,Gold,Copper' → 'wood, gold, and copper'"""
    if not raw:
        return ""
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _clean_monument_type(raw: str) -> str:
    """'Monastic building (bāhāḥ),Tiered temple' → 'monastic building (bāhāḥ) and tiered temple'"""
    if not raw:
        return "heritage monument"
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 1:
        return parts[0].lower()
    if len(parts) == 2:
        return f"{parts[0].lower()} and {parts[1].lower()}"
    return ", ".join(p.lower() for p in parts[:-1]) + f", and {parts[-1].lower()}"


def _clean_object_type(raw: str) -> str:
    return raw.strip().lower() if raw else "object"


def _strip_monument_prefix(caption: str, monument_name: str) -> str:
    """Remove monument name prefix from DANAM caption."""
    base = re.split(r"\s*[\(\[,]", monument_name)[0].strip()
    if base and caption.lower().startswith(base.lower()):
        rest = caption[len(base):].lstrip(" ,").strip()
        return rest
    return caption


def _clean_int(val: str) -> str:
    """'3.0' → '3', '0' or '0.0' → '' (treat as missing)."""
    if not val or val in ("", "None"):
        return ""
    try:
        f = float(val)
        if f == 0.0:
            return ""
        return str(int(f)) if f == int(f) else str(f)
    except ValueError:
        return val


def _clean_religion(val: str) -> str:
    """Remove 'Unspecified' and normalize."""
    if not val or val.strip().lower() in ("unspecified", "none", ""):
        return ""
    return val.strip()


def _clean_desc(raw: str) -> str:
    """Clean DANAM description: remove reference codes, collapse whitespace."""
    if not raw:
        return ""
    text = re.sub(r"\(\s*[A-Z]{2,5}\d{3,5}[\s,andA-Z\d]*\)", "", raw)
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text)  # "in in" → "in"
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text and not text.endswith("."):
        text += "."
    return text


def _get_object_sentence(object_type: str) -> str:
    obj_lower = object_type.lower()
    for key, sentence in _OBJECT_SENTENCES.items():
        if key in obj_lower:
            return sentence
    return _OBJECT_SENTENCE_DEFAULT


def _is_view_only_caption(caption: str) -> bool:
    """True if the caption is just a short view direction, not a real description."""
    clean = caption.strip().rstrip(".")
    words = clean.split()
    if len(words) <= 5:
        return True
    if re.match(r"^(general\s+)?view(\s+from\s+\w+)?$", clean, re.IGNORECASE):
        return True
    return False


def _is_photographer_credit(caption: str) -> bool:
    """True if caption is just a photo credit or date stamp."""
    c = caption.strip()
    if re.match(r"^[Pp]hoto\s+(by|:)", c):
        return True
    if re.match(r"^\d{4}-\d{2}-\d{2}", c):
        return True
    return False


# ── Caption builders ───────────────────────────────────────────────────────────

def _build_exterior_captions(row: dict) -> list[str]:
    """Build 3 captions for an exterior monument photo.
    Training uses Cap 1 + Cap 2 (Cap 3 excluded to prevent mode collapse)."""
    name         = row["monument_name"]
    mtype_raw    = row["monument_type"]
    religion_raw = row["religion"]
    deity        = row["deity"]
    roof         = row["roof_type"]
    struts       = _clean_int(row["num_struts"])
    brick        = row["brick_type"]
    doors        = _clean_int(row["num_doors"])
    storeys      = _clean_int(row["num_storeys"])
    description  = row["monument_description"]
    img_caption  = row.get("image_caption", "")

    mtype    = _clean_monument_type(mtype_raw)
    religion = _clean_religion(religion_raw)

    # ── Cap 1: Architecture-derived visual description ────────────────────────
    parts = []
    if storeys:
        parts.append(f"a {storeys}-storey")
    else:
        parts.append("a")

    if religion:
        parts.append(religion.capitalize())
    parts.append(mtype)

    features = []
    if roof and roof.lower() not in ("", "none"):
        features.append(f"a {roof.lower()}")
    if struts:
        features.append(f"{struts} wooden struts")
    if brick and brick.lower() not in ("", "none"):
        first_brick = brick.split(",")[0].strip()
        if first_brick.lower() in ("stone", "wood"):
            features.append(f"{first_brick.lower()} walls")
        else:
            features.append(f"{first_brick} brick walls")
    if doors:
        door_word = "door" if doors == "1" else "doors"
        features.append(f"{doors} {door_word}")

    cap1 = " ".join(parts)
    if features:
        cap1 += " with " + ", ".join(features)
    cap1 = cap1.strip()
    cap1 = cap1[0].upper() + cap1[1:] + "."

    # Fallback if still too short (no architecture data at all)
    if len(cap1.split()) < 5:
        if religion:
            cap1 = f"A {religion.capitalize()} {mtype} in Nepal."
        else:
            cap1 = f"A historic {mtype} in Nepal."

    # ── Cap 2: Monument description (academic, per-monument) ─────────────────
    desc_clean = _clean_desc(description)
    if desc_clean and len(desc_clean.split()) >= 8:
        cap2 = desc_clean
    else:
        # Description missing — build a factual sentence from metadata
        if religion and deity and deity.lower() not in ("", "none"):
            cap2 = f"{name} is a {religion.capitalize()} {mtype} dedicated to {deity}, located in Nepal."
        elif religion:
            cap2 = f"{name} is a {religion.capitalize()} {mtype} in Nepal."
        else:
            cap2 = f"{name} is a historic {mtype} in Nepal."

    # ── Append view direction to Cap 1 when available (disambiguates multi-images) ──
    if img_caption and not _is_photographer_credit(img_caption):
        # Extract trailing compass/view phrase from DANAM image caption
        m = re.search(
            r",?\s*(?:view\s+from\s+([\w\s-]+)|"
            r"([\w]+)\s+view|"
            r"(?:from\s+)?([NSEW]{1,3})\s*)$",
            img_caption.strip(), re.IGNORECASE
        )
        if m:
            direction = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            if direction:
                direction_expanded = _COMPASS.get(direction.upper(), direction.lower())
                # Only append if not already mentioned
                if direction_expanded.lower() not in cap1.lower():
                    cap1 = cap1.rstrip(".") + f", {direction_expanded} view."

    # ── Cap 3: Name + context (not used in training) ───────────────────────────
    ctx = f"a {religion.capitalize()} {mtype}" if religion else f"a {mtype}"
    if deity and deity.lower() not in ("", "none"):
        ctx += f" dedicated to {deity}"
    cap3 = f"{name}, {ctx}, Nepal."

    return [cap1, cap2, cap3]


def _build_object_captions(row: dict) -> list[str]:
    """Build 3 captions for an object photo.
    Training uses Cap 1 + Cap 2."""
    name         = row["monument_name"]
    mtype        = _clean_monument_type(row["monument_type"])
    caption      = row.get("image_caption", "")
    obj_type_raw = row["object_type"]
    material_raw = row["object_material"]
    position     = row.get("object_position", "")

    obj_type = _clean_object_type(obj_type_raw)
    material = _humanize_materials(material_raw)

    detail = _strip_monument_prefix(caption, name)
    detail = _expand_direction(detail)

    # Filter out photographer credits leaking in as captions
    if _is_photographer_credit(detail):
        detail = ""

    # ── Cap 1: Expanded DANAM caption with material ──────────────────────────
    if detail and len(detail.split()) > 3:
        detail_cap = detail[0].upper() + detail[1:]
        if not detail_cap.endswith("."):
            detail_cap += "."
        # Prepend material if not already in caption
        if material and material.split()[0].lower() not in detail_cap.lower():
            cap1 = f"{material.capitalize()} {obj_type}, {detail_cap}"
        else:
            cap1 = detail_cap
    elif material and obj_type and obj_type != "object":
        cap1 = f"{material.capitalize()} {obj_type} at {name}."
    elif obj_type and obj_type != "object":
        cap1 = f"{obj_type.capitalize()} at {name}."
    elif detail and len(detail.split()) >= 2:
        cap1 = detail[0].upper() + detail[1:]
        if not cap1.endswith("."):
            cap1 += "."
    else:
        cap1 = f"A devotional object at {name}."

    # ── Cap 2: Structured material + type + position ─────────────────────────
    pos_phrase = ""
    if position and position.lower() not in ("", "none"):
        pos_lower = position.lower()
        if "inside" in pos_lower or "sanctum" in pos_lower:
            pos_phrase = " inside the sanctum"
        elif "attached" in pos_lower or "door" in pos_lower:
            pos_phrase = " attached to the temple entrance"
        elif "separate" in pos_lower or "court" in pos_lower:
            pos_phrase = " in the temple courtyard"

    # Only use "A object at..." if we truly have no type info
    effective_type = obj_type if (obj_type and obj_type != "object") else None
    if material and effective_type:
        cap2 = f"A {material} {effective_type}{pos_phrase} at a Nepali {mtype}."
    elif effective_type:
        cap2 = f"A {effective_type}{pos_phrase} at a Nepali {mtype}."
    elif material:
        cap2 = f"A {material} devotional object{pos_phrase} at a Nepali {mtype}."
    else:
        # Last resort: use cap1 rephrased instead of the placeholder
        cap2 = f"A devotional element{pos_phrase} at a Nepali {mtype}."
    cap2 = cap2[0].upper() + cap2[1:]

    # ── Cap 3: Educational (not used in training) ────────────────────────────
    cap3 = _get_object_sentence(obj_type_raw)

    return [cap1, cap2, cap3]


# ── Main conversion ────────────────────────────────────────────────────────────

def _validate_captions(caps: list[str], image_id: str) -> list[str]:
    """Final quality gate: fix any remaining issues."""
    fixed = []
    for i, c in enumerate(caps):
        c = re.sub(r"\bUnspecified\b", "", c)
        c = re.sub(r"\b0\.0-storey\b", "", c)
        c = re.sub(r",\s*0\.0 doors?", "", c)
        c = re.sub(r"\bA object\b", "A devotional object", c)
        c = re.sub(r"\bA  +", "A ", c)
        c = re.sub(r"  +", " ", c).strip()
        if not c.endswith("."):
            c += "."
        if len(c.split()) < 4:
            c = "A historic Nepali heritage monument."
        fixed.append(c)
    return fixed


def convert_danam_manifest(
    manifest_path: Path,
    images_dir: Path,
    output_path: Path,
    batch_size: int = 0,
    batch_num:  int = 0,
) -> list[dict]:
    """Convert manifest to training JSON.

    If batch_size > 0, only process entries [batch_num*batch_size : (batch_num+1)*batch_size].
    Useful for reviewing a subset before full conversion.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if batch_size > 0:
        start = batch_num * batch_size
        end   = start + batch_size
        rows  = rows[start:end]
        print(f"  Batch mode: rows {start}–{min(end, len(rows)+start)}")

    data: list[dict] = []
    skipped = 0

    for row in rows:
        filename = row["filename"].strip()

        # Find image on disk (search monument subdirs)
        image_path = None
        for d in images_dir.iterdir():
            if d.is_dir():
                candidate = d / filename
                if candidate.exists():
                    image_path = candidate
                    break

        if image_path is None:
            skipped += 1
            continue

        img_type = row.get("image_type", "exterior")
        if img_type == "object":
            captions = _build_object_captions(row)
        else:
            captions = _build_exterior_captions(row)

        captions = _validate_captions(captions, filename)

        entry = {
            "image_id":      filename,
            "category":      image_path.parent.name,
            "cultural_label":_clean_monument_type(row.get("monument_type", "")),
            "monument_name": row["monument_name"],
            "source":        "danam",
            "image_type":    img_type,
            "captions":      captions,
        }
        data.append(entry)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    type_counts: Counter = Counter(e["image_type"] for e in data)
    print(f"\nConverted {len(data)} entries, {skipped} skipped (missing file).")
    print(f"  Exterior : {type_counts.get('exterior', 0)}")
    print(f"  Object   : {type_counts.get('object', 0)}")
    return data


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Convert DANAM v3 manifest → metadata_danam.json"
    )
    parser.add_argument("--manifest",    default="data/raw/danam/manifest.csv")
    parser.add_argument("--images-dir",  default="data/raw/danam/images")
    parser.add_argument("--output",      default="data/processed/metadata_danam.json")
    parser.add_argument("--batch-size",  type=int, default=0,
                        help="Entries per batch for review (0 = all)")
    parser.add_argument("--batch-num",   type=int, default=0,
                        help="Which batch to process (0-indexed)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    convert_danam_manifest(
        root / args.manifest,
        root / args.images_dir,
        root / args.output,
        batch_size=args.batch_size,
        batch_num=args.batch_num,
    )
    print(f"Wrote: {root / args.output}")


if __name__ == "__main__":
    main()
