#!/usr/bin/env python3
"""
Generate high-quality training captions using Gemini Vision API.

For each image in manifest_filtered.csv, sends:
  - The actual image file
  - Rich DANAM cultural context (name, type, religion, architecture, description)

Gemini generates a single, visually-grounded, culturally-accurate caption
(50–80 words) per image — far better than template-based captions.

Features:
  - Resumable: saves cache JSON after every API call. Safe to Ctrl-C and re-run.
  - Rate-limited: configurable RPM (default 14 = safe for free tier).
  - Outputs: data/processed/metadata_gemini.json  (ready for Colab training)

Install:
  pip install google-genai Pillow tqdm

Usage:
  export GEMINI_API_KEY="your_key_here"

  # Dry-run on first 5 images to verify prompts (no API calls):
  python3 scripts/generate_captions_gemini.py --dry-run --limit 5

  # Full run (paid tier: 4K RPM, 150K RPD for gemini-3.1-flash-lite):
  python3 scripts/generate_captions_gemini.py

  # 10 random images for test review:
  python3 scripts/generate_captions_gemini.py --limit 10 --random
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional


class RateLimiter:
    """Limit to rpm requests per rolling 60-second window."""
    def __init__(self, rpm: float):
        self.rpm = max(1, int(rpm))
        self.timestamps: deque = deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        with self.lock:
            now = time.time()
            cutoff = now - 60.0
            while self.timestamps and self.timestamps[0] < cutoff:
                self.timestamps.popleft()
            if len(self.timestamps) >= self.rpm:
                wait = 60.0 - (now - self.timestamps[0])
                if wait > 0:
                    time.sleep(wait)
                self.timestamps.popleft()
            self.timestamps.append(time.time())

try:
    from google import genai
    from google.genai import types as gtypes
    from PIL import Image
    from tqdm import tqdm
except ImportError:
    print("Missing dependencies. Run:")
    print("  pip install google-genai Pillow tqdm")
    sys.exit(1)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
MANIFEST    = ROOT / "data/raw/danam/manifest_filtered.csv"
IMAGES_DIR  = ROOT / "data/raw/danam/images"
CACHE_PATH  = ROOT / "data/processed/captions_cache.json"
OUTPUT_PATH = ROOT / "data/processed/metadata_gemini.json"

# ── Compass expansion ─────────────────────────────────────────────────────────
_COMPASS = {
    "N": "northern", "S": "southern", "E": "eastern", "W": "western",
    "NE": "northeastern", "NW": "northwestern",
    "SE": "southeastern", "SW": "southwestern",
}


# ── Prompt builders ───────────────────────────────────────────────────────────

def _build_exterior_prompt(row: dict) -> str:
    name        = row["monument_name"].strip()
    mtype       = row["monument_type"].strip() or "heritage monument"
    religion    = row["religion"].strip()
    deity       = row["deity"].strip()
    roof        = row["roof_type"].strip()
    struts      = row["num_struts"].strip()
    doors       = row["num_doors"].strip()
    storeys     = row["num_storeys"].strip()
    description = row["monument_description"].strip()
    img_cap     = row.get("image_caption", "").strip()

    # Expand view direction from DANAM image caption
    view_hint = ""
    m = re.search(r"view from ([NSEW]{1,3})\b", img_cap, re.IGNORECASE)
    if m:
        view_hint = _COMPASS.get(m.group(1).upper(), m.group(1).lower()) + " side"

    # Build architecture summary
    arch_parts = []
    if storeys and storeys not in ("0", "0.0", ""):
        arch_parts.append(f"{int(float(storeys))}-storey")
    if religion and religion.lower() not in ("unspecified", ""):
        arch_parts.append(religion)
    arch_parts.append(mtype)
    if roof and roof.lower() not in ("", "none"):
        arch_parts.append(f"with {roof.lower()} roof")
    if struts and struts not in ("0", "0.0", ""):
        arch_parts.append(f"{int(float(struts))} wooden struts")
    if doors and doors not in ("0", "0.0", ""):
        arch_parts.append(f"{int(float(doors))} doors")
    arch_summary = ", ".join(arch_parts)

    ctx = [f"Monument: {name}"]
    ctx.append(f"Type    : {arch_summary}" if arch_summary else f"Type: {mtype}")
    if religion and religion.lower() not in ("unspecified", ""):
        ctx.append(f"Religion: {religion}")
    if deity and deity.lower() not in ("", "none", "unspecified"):
        ctx.append(f"Deity   : {deity}")
    if description:
        sentences = re.split(r'(?<=[.!?])\s+', description.strip())
        ctx.append(f"Scholarly note: {' '.join(sentences[:3])}")
    if view_hint:
        ctx.append(f"Photo angle: {view_hint}")

    context = "\n".join(f"  {l}" for l in ctx)

    return f"""You are an expert on Nepali cultural heritage and Newari architecture.

Look at this photograph carefully and write ONE precise English caption (50–75 words).

REQUIREMENTS:
1. Describe what you VISUALLY SEE: the structure's form, height, materials, \
decorative elements, and immediate surroundings.
2. Use accurate Nepali architectural terms where visible: \
pagoda / tiered temple, stupa, pati, mandapa, toraṇa, shikhara, struts, \
pinnacle (āmalaka / gajura), etc.
3. Mention the approximate view angle if clear (frontal, corner, side view).
4. Do NOT include: photographer name, date, or the phrase "view from X".
5. Write as 1–2 flowing sentences; no bullet points.

CULTURAL CONTEXT (use to enrich terminology, not to invent unseen details):
{context}

Caption:"""


def _build_object_prompt(row: dict) -> str:
    name         = row["monument_name"].strip()
    mtype        = row["monument_type"].strip() or "heritage monument"
    religion     = row["religion"].strip()
    obj_type     = row["object_type"].strip() or "object"
    material_raw = row["object_material"].strip()
    position     = row["object_position"].strip()
    description  = row["monument_description"].strip()
    img_cap      = row.get("image_caption", "").strip()

    # Parse material list into readable string
    mats = [m.strip().lower() for m in material_raw.split(",") if m.strip()]
    if len(mats) > 1:
        material_str = ", ".join(mats[:-1]) + f" and {mats[-1]}"
    elif mats:
        material_str = mats[0]
    else:
        material_str = ""

    # Extract object name from DANAM image caption
    obj_name = ""
    if img_cap:
        stripped = re.sub(r"^" + re.escape(name), "", img_cap, flags=re.IGNORECASE).strip(" ,")
        stripped = re.sub(r",?\s*(?:view from\s+)?[NSEW]{1,3}\s*$", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r";?\s*photo by.*$", "", stripped, flags=re.IGNORECASE).strip()
        if len(stripped.split()) >= 2:
            obj_name = stripped

    ctx = [f"Object  : {obj_name or obj_type} ({obj_type})" if obj_name else f"Object type: {obj_type}"]
    if material_str:
        ctx.append(f"Material: {material_str}")
    if position and position.lower() not in ("", "none"):
        ctx.append(f"Position: {position}")
    ctx.append(f"Located at: {name} ({religion} {mtype})" if religion else f"Located at: {name}")
    if description:
        sentences = re.split(r'(?<=[.!?])\s+', description.strip())
        ctx.append(f"Monument context: {sentences[0]}")

    context = "\n".join(f"  {l}" for l in ctx)

    return f"""You are an expert on Nepali cultural heritage and Newari art history.

Look at this photograph of a specific architectural or devotional object carefully \
and write ONE precise English caption (40–65 words).

REQUIREMENTS:
1. Describe what you VISUALLY SEE: the object's form, material, iconography, \
decorative details, condition, and setting.
2. Use accurate art-historical terms: toraṇa (carved arch), śivaliṅga, caitya \
(votive stupa), tympanum, relief panel, dhvajastambha (flagpole), etc.
3. Do NOT mention: photographer name, date, or the monument name as the main subject.
4. Write as 1–2 flowing sentences; no bullet points.

CULTURAL CONTEXT:
{context}

Caption:"""


# ── Gemini API call ───────────────────────────────────────────────────────────

def call_gemini(
    client: genai.Client,
    model_name: str,
    image_path: Path,
    prompt: str,
    max_retries: int = 3,
) -> Optional[str]:
    """Send image + prompt to Gemini, return caption or None on failure."""
    try:
        img = Image.open(image_path)
        img.load()  # force load to catch truncated files early
        img = img.convert("RGB")
    except Exception as e:
        tqdm.write(f"  [SKIP IMG] {image_path.name}: cannot open image ({e})")
        return None

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[img, prompt],
                config=gtypes.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=250,
                    candidate_count=1,
                ),
            )
            text = response.text
            if text and text.strip():
                text = re.sub(r"^[Cc]aption\s*:\s*", "", text.strip())
                return text.strip()
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt * 5
                tqdm.write(f"  [retry {attempt+1}] {e} — waiting {wait}s")
                time.sleep(wait)
            else:
                tqdm.write(f"  [FAIL] {image_path.name}: {e}")
                return None


# ── Image finder ──────────────────────────────────────────────────────────────

def find_image(filename: str, images_dir: Path) -> Optional[Path]:
    for d in images_dir.iterdir():
        if d.is_dir():
            p = d / filename
            if p.exists():
                return p
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Gemini captions for heritage images")
    parser.add_argument("--manifest",   default=str(MANIFEST))
    parser.add_argument("--images-dir", default=str(IMAGES_DIR))
    parser.add_argument("--cache",      default=str(CACHE_PATH))
    parser.add_argument("--output",     default=str(OUTPUT_PATH))
    parser.add_argument("--model",      default="gemini-3.1-flash-lite-preview",

                        help="Gemini model (paid: 4K RPM, 150K RPD)")
    parser.add_argument("--rpm",        type=float, default=2000,
                        help="Max requests per minute (2000 = safe and sufficient under 4K paid tier)")
    parser.add_argument("--limit",      type=int,   default=0,
                        help="Process only first N rows (0 = all)")
    parser.add_argument("--random",     action="store_true",
                        help="When used with --limit, sample N random images instead of first N")
    parser.add_argument("--workers",    type=int, default=8,
                        help="Parallel workers (8 = good balance of speed/stability)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Print prompts without calling API")
    args = parser.parse_args()

    # ── API key ───────────────────────────────────────────────────────────────
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key and not args.dry_run:
        api_key = input("Enter your Gemini API key: ").strip()
    if not api_key and not args.dry_run:
        print("No API key provided. Set GEMINI_API_KEY env var or paste at prompt.")
        sys.exit(1)

    client = None
    if not args.dry_run:
        client = genai.Client(api_key=api_key)
        print(f"Model   : {args.model}")
        print(f"Workers : {args.workers} (parallel)")
        print(f"RPM     : {args.rpm} (rate limit)")

    # ── Load manifest ─────────────────────────────────────────────────────────
    manifest_path = Path(args.manifest)
    images_dir    = Path(args.images_dir)

    with open(manifest_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if args.limit > 0:
        if args.random:
            random.shuffle(rows)
            print(f"\nSampling {args.limit} random images for test run")
        rows = rows[:args.limit]

    print(f"\nManifest : {len(rows)} entries from {manifest_path.name}")

    # ── Load cache ────────────────────────────────────────────────────────────
    cache_path = Path(args.cache)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, str] = {}
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"Cache    : {len(cache)} existing captions — will skip these")

    # ── Filter to work that still needs doing ─────────────────────────────────
    todo = [r for r in rows if r["filename"].strip() not in cache]
    print(f"To do    : {len(todo)} images need captions  ({len(rows)-len(todo)} already cached)")

    if args.dry_run:
        print("\n[DRY RUN — showing first 3 prompts, no API calls]\n")

    skipped = 0
    failed  = 0
    done    = 0
    failed_ids: list[str] = []
    cache_lock = threading.Lock()
    rate_limiter = RateLimiter(args.rpm) if not args.dry_run else None

    def process_one(row: dict) -> tuple[str, str | None, bool]:
        """Returns (filename, caption_or_none, skipped_disk)."""
        filename = row["filename"].strip()
        try:
            img_path = find_image(filename, images_dir)
            if img_path is None:
                return (filename, None, True)
            if rate_limiter:
                rate_limiter.acquire()
            img_type = row.get("image_type", "exterior").strip()
            prompt   = _build_object_prompt(row) if img_type == "object" else _build_exterior_prompt(row)
            caption  = call_gemini(client, args.model, img_path, prompt)
            return (filename, caption, False)
        except Exception as e:
            tqdm.write(f"  [FAIL ROW] {filename}: {e}")
            return (filename, None, False)

    if args.dry_run:
        for row in todo[:3]:
            filename = row["filename"].strip()
            img_type = row.get("image_type", "exterior").strip()
            prompt   = _build_object_prompt(row) if img_type == "object" else _build_exterior_prompt(row)
            print(f"{'─'*60}")
            print(f"FILE : {filename}  TYPE : {img_type}")
            print(prompt[:700])
            print()
        print("... (use --limit N to see more)")
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(process_one, row): row for row in todo}
            for fut in tqdm(as_completed(futures), total=len(futures), desc="Generating", unit="img"):
                filename, caption, was_skipped = fut.result()
                if was_skipped:
                    skipped += 1
                    tqdm.write(f"  [SKIP] not on disk: {filename}")
                    continue
                if caption:
                    with cache_lock:
                        cache[filename] = caption
                        tmp = cache_path.with_suffix(".tmp")
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(cache, f, indent=2, ensure_ascii=False)
                        tmp.replace(cache_path)  # atomic rename
                    done += 1
                else:
                    failed += 1
                    failed_ids.append(filename)

    if args.dry_run:
        print("\n[dry-run complete — no API calls made]")
        return

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  New captions   : {done}")
    print(f"  Skipped (disk) : {skipped}")
    print(f"  API failures   : {failed}")
    if failed_ids:
        print(f"  Failed IDs     : {failed_ids[:5]}{'...' if len(failed_ids)>5 else ''}")
    print(f"  Cache total    : {len(cache)}")

    # ── Build output metadata_gemini.json ─────────────────────────────────────
    _write_metadata(manifest_path, images_dir, cache, Path(args.output), rows)

    print("\nNext steps:")
    print(f"  1. Preview   : python3 scripts/batch_preview.py --metadata data/processed/metadata_gemini.json --n 20")
    print(f"  2. Activate  : cp data/processed/metadata_gemini.json data/processed/metadata_merged.json")
    print(f"  3. Rebuild   : python3 scripts/build_zip.py")


def _write_metadata(manifest_path: Path, images_dir: Path, cache: dict,
                    output_path: Path, rows: list) -> None:
    entries = []
    for row in rows:
        filename = row["filename"].strip()
        if filename not in cache:
            continue
        img_path = find_image(filename, images_dir)
        if img_path is None:
            continue

        img_type     = row.get("image_type", "exterior").strip()
        gemini_cap   = cache[filename]

        # Short metadata fallback as second caption (gives training variety)
        if img_type == "exterior":
            storeys  = row["num_storeys"].strip()
            religion = row["religion"].strip()
            mtype    = row["monument_type"].strip() or "heritage monument"
            s = f"{int(float(storeys))}-storey " if storeys and storeys not in ("0","0.0","") else ""
            r = f"{religion} " if religion and religion.lower() not in ("unspecified","") else ""
            fallback = f"A {s}{r}{mtype} in Nepal.".replace("  ", " ").capitalize()
        else:
            obj_type = row["object_type"].strip() or "object"
            material = row["object_material"].strip()
            mat_str  = material.split(",")[0].strip().lower() if material else ""
            fallback = (f"A {mat_str} {obj_type} at a Nepali heritage site.".capitalize()
                        if mat_str else f"A {obj_type} at a Nepali heritage site.".capitalize())

        entries.append({
            "image_id":       filename,
            "category":       img_path.parent.name,
            "cultural_label": row["monument_type"].strip().lower() or "heritage monument",
            "monument_name":  row["monument_name"].strip(),
            "source":         "danam_gemini",
            "image_type":     img_type,
            "captions":       [gemini_cap, fallback],
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    print(f"\nWritten  : {output_path}  ({len(entries)} entries)")


if __name__ == "__main__":
    main()
