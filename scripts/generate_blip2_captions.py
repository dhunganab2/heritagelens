#!/usr/bin/env python3
"""
Generate BLIP-2 visual captions for heritage images.

Run this script on Colab T4 (or any machine with a GPU) AFTER running
filter_images.py, convert_to_training_json.py, convert_danam_to_json.py,
and merge_datasets.py.

What it does:
  - Loads Salesforce/blip2-opt-2.7b (free, no token needed)
  - Processes every image referenced in metadata_merged.json
  - Generates two captions per image:
      unconditional  — "a photo of ..."       (pure visual description)
      prompted       — "a heritage monument..." (domain-guided)
  - Saves data/processed/blip2_captions.json: { image_id: [uncond, prompted] }

Why only for images that lack a unique Wikimedia description (Tier B & C)?
  Tier A Wikimedia images already have high-quality human-written captions.
  Running BLIP-2 over 1,500 images takes ~30 minutes on T4.
  If you want BLIP-2 captions for ALL images, pass --all.

Usage (Colab):
  !python3 scripts/generate_blip2_captions.py \\
      --merged    data/processed/metadata_merged.json \\
      --wiki-img  data/raw/wikimedia/images \\
      --danam-img data/raw/danam/images \\
      --output    data/processed/blip2_captions.json

Then run assemble_captions.py to fold these back into metadata_merged.json.
"""

import argparse
import json
import sys
from pathlib import Path

import torch
from PIL import Image
from tqdm import tqdm
from transformers import Blip2ForConditionalGeneration, Blip2Processor


# ── Tier detection heuristic ─────────────────────────────────────────────────
# We flag an entry as Tier B/C (needs BLIP-2) if Cap 1 is the same as the
# category architectural sentence (meaning there was no unique human description).
# Tier A entries have a unique, specific Cap 1 that is NOT one of these templates.
_TIER_B_PREFIXES = (
    "A whitewashed Buddhist stupa with the painted",
    "A massive hemispherical stupa",
    "A multi-tiered Hindu temple with a gilded copper",
    "A traditional Newari pagoda-style temple with layered brick",
    "A historic temple or palace structure with traditional brick",
    "A Newari pagoda-style temple with multi-tiered roofs",
    "A two-tiered Newari pagoda with detailed stone",
    "A traditional Hindu temple with tiered roofs",
    "A Buddhist shrine or monastery with traditional Nepali",
    "A traditional heritage structure with Nepali architectural",
)


def _needs_blip2(entry: dict) -> bool:
    """Return True if Cap 1 is a category-level template (not image-specific)."""
    cap1 = entry.get("captions", [""])[0]
    return any(cap1.startswith(prefix) for prefix in _TIER_B_PREFIXES)


def _find_image(image_id: str, category: str, images_dirs: list[Path]) -> Path | None:
    import unicodedata

    def nfc(s: str) -> str:
        return unicodedata.normalize("NFC", s)

    image_id_n = nfc(image_id)
    for img_dir in images_dirs:
        if not img_dir.exists():
            continue
        for subdir_name in [f"Category:{nfc(category)}", nfc(category)]:
            p = img_dir / subdir_name / image_id_n
            if p.exists():
                return p
        for sub in img_dir.iterdir():
            if sub.is_dir():
                p = sub / image_id_n
                if p.exists():
                    return p
    return None


def generate_blip2_captions(
    merged_json: Path,
    images_dirs: list[Path],
    output_path: Path,
    process_all: bool = False,
    batch_size: int = 8,
) -> None:
    print("Loading BLIP-2 model (Salesforce/blip2-opt-2.7b)…")
    print("This will download ~5 GB on first run.")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype  = torch.float16 if device == "cuda" else torch.float32
    print(f"Device: {device}  |  dtype: {dtype}")

    processor = Blip2Processor.from_pretrained("Salesforce/blip2-opt-2.7b")
    model = Blip2ForConditionalGeneration.from_pretrained(
        "Salesforce/blip2-opt-2.7b",
        torch_dtype=dtype,
        device_map="auto",
    )
    model.eval()
    print("Model loaded.\n")

    with open(merged_json, "r", encoding="utf-8") as f:
        data: list[dict] = json.load(f)

    if not process_all:
        targets = [e for e in data if _needs_blip2(e)]
        print(f"Tier B/C images (no unique human description): {len(targets)} / {len(data)}")
    else:
        targets = data
        print(f"Processing ALL {len(data)} images.")

    # Load any existing output to allow resume
    results: dict[str, list[str]] = {}
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            results = json.load(f)
        print(f"Resuming — {len(results)} already done.")

    skipped = 0
    prompt = "a heritage monument in Nepal:"

    for i in tqdm(range(0, len(targets), batch_size), desc="BLIP-2 captioning"):
        batch = targets[i : i + batch_size]

        images_batch = []
        valid_batch  = []
        for entry in batch:
            if entry["image_id"] in results:
                continue
            img_path = _find_image(entry["image_id"], entry.get("category", ""), images_dirs)
            if img_path is None:
                skipped += 1
                continue
            try:
                img = Image.open(img_path).convert("RGB")
                images_batch.append(img)
                valid_batch.append(entry)
            except Exception:
                skipped += 1

        if not images_batch:
            continue

        with torch.no_grad():
            # ── Unconditional captions ────────────────────────────────────────
            inputs_uncond = processor(
                images=images_batch,
                return_tensors="pt",
            ).to(device, dtype)

            out_uncond = model.generate(
                **inputs_uncond,
                max_new_tokens=40,
                num_beams=4,
                repetition_penalty=1.3,
            )
            caps_uncond = processor.batch_decode(out_uncond, skip_special_tokens=True)

            # ── Prompted captions ─────────────────────────────────────────────
            inputs_prompted = processor(
                images=images_batch,
                text=[prompt] * len(images_batch),
                return_tensors="pt",
            ).to(device, dtype)

            out_prompted = model.generate(
                **inputs_prompted,
                max_new_tokens=40,
                num_beams=4,
                repetition_penalty=1.3,
            )
            caps_prompted = processor.batch_decode(out_prompted, skip_special_tokens=True)

        for entry, uncond, prompted in zip(valid_batch, caps_uncond, caps_prompted):
            results[entry["image_id"]] = [
                uncond.strip(),
                prompted.strip().removeprefix(prompt).strip(),
            ]

        # Save checkpoint every batch
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(results)} captions saved to {output_path}")
    print(f"Skipped (file not found or unreadable): {skipped}")
    print("\nNext step: run scripts/assemble_captions.py to fold BLIP-2 into metadata_merged.json")


def main():
    parser = argparse.ArgumentParser(
        description="Generate BLIP-2 captions for heritage images (run on Colab T4)"
    )
    parser.add_argument("--merged",      default="data/processed/metadata_merged.json")
    parser.add_argument("--wiki-img",    default="data/raw/wikimedia/images")
    parser.add_argument("--danam-img",   default="data/raw/danam/images")
    parser.add_argument("--output",      default="data/processed/blip2_captions.json")
    parser.add_argument("--batch-size",  type=int, default=8)
    parser.add_argument(
        "--all", dest="process_all", action="store_true",
        help="Process ALL images, not just Tier B/C (takes longer)",
    )
    args = parser.parse_args()

    root        = Path(__file__).resolve().parent.parent
    merged_path = root / args.merged
    output_path = root / args.output
    images_dirs = [root / args.wiki_img, root / args.danam_img]

    if not merged_path.exists():
        print(f"File not found: {merged_path}")
        print("Run merge_datasets.py first.")
        sys.exit(1)

    generate_blip2_captions(merged_path, images_dirs, output_path, args.process_all, args.batch_size)


if __name__ == "__main__":
    main()
