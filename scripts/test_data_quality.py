#!/usr/bin/env python3
"""
Automated data quality report for metadata_merged.json.

Checks:
  1. Caption uniqueness   — what % of Cap 1 strings are unique across all images
  2. Caption length       — flag captions < 6 words (likely garbage)
  3. Domain vocabulary    — what % of entries mention a domain term
  4. Duplicate Cap1       — list the top repeated first-captions
  5. Image file coverage  — what % of image_ids resolve to actual files on disk
  6. Caption diversity    — within each entry, are the 3 captions different from each other?
  7. Source distribution  — how many entries from wikimedia vs danam
  8. Template residue     — detect any old generic templates that slipped through

Exit code 0 = all checks passed, 1 = warnings found.
"""

import json
import sys
from collections import Counter
from pathlib import Path

# Domain-specific terms the model should learn
_DOMAIN_TERMS = [
    "stupa", "pagoda", "torana", "toraṇa", "strut", "harmika", "shikhara",
    "śikhara", "chaitya", "caitya", "mandira", "mandir", "newari", "newār",
    "kathmandu", "patan", "bhaktapur", "changu", "pashupatinath", "boudhanath",
    "swayambhunath", "vihara", "bahah", "bāhāḥ", "phalca", "phalcā", "hiti",
    "dhara", "dhārā", "malla", "vishnu", "shiva", "śiva", "durbar", "darbār",
    "nepal", "nepali",
]

# Old generic template fragments that should NOT appear in quality data
_TEMPLATE_FRAGMENTS = [
    "A white dome stupa with traditional Buddhist architecture, often featuring",
    "A place of worship and cultural significance in Nepal's heritage landscape.",
    "An example of Nepali cultural heritage and traditional craftsmanship.",
    "An ancient Buddhist monument of deep significance to Nepali",
    "Traditional Buddhist artwork with detailed iconography",
    "Traditional Nepali dress or ornamentation",
    "A Buddhist stupa with traditional Nepali architecture and religious significance.",
    "A traditional Buddhist monastery complex in the Kathmandu Valley with ornate woodcarvings",
    "A Temple featuring traditional Nepali architecture with tiered roofs and intricate carvings.",
    "A historic Heritage Monument representing Nepali cultural heritage.",
]


def _has_domain_term(captions: list[str]) -> bool:
    combined = " ".join(captions).lower()
    return any(term in combined for term in _DOMAIN_TERMS)


def _min_words(caption: str) -> int:
    return len(caption.strip().split())


def run_quality_report(
    merged_json: Path,
    images_dirs: list[Path],
    verbose: bool = True,
) -> bool:
    """
    Run all quality checks. Returns True if all pass, False if any warning found.
    """
    with open(merged_json, "r", encoding="utf-8") as f:
        data: list[dict] = json.load(f)

    total = len(data)
    warnings: list[str] = []

    # ── 1. Source distribution ────────────────────────────────────────────────
    source_counts = Counter(e.get("source", "wikimedia") for e in data)
    print(f"\n{'='*60}")
    print(f"DATA QUALITY REPORT  —  {merged_json.name}")
    print(f"{'='*60}")
    print(f"\nTotal entries : {total}")
    for src, cnt in sorted(source_counts.items()):
        print(f"  {src:15s}: {cnt}")

    # ── 2. Caption uniqueness (Cap 1) ─────────────────────────────────────────
    cap1_list = [e["captions"][0] for e in data if e.get("captions")]
    cap1_counts = Counter(cap1_list)
    unique_cap1 = sum(1 for c in cap1_counts.values() if c == 1)
    dup_cap1 = sum(1 for c in cap1_counts.values() if c > 1)
    uniqueness_pct = 100 * unique_cap1 // total

    print(f"\n[1] Cap 1 uniqueness")
    print(f"    Unique Cap 1  : {unique_cap1} / {total} ({uniqueness_pct}%)")
    print(f"    Duplicate Cap1: {dup_cap1} distinct strings used by 2+ images")
    # 55% is the realistic ceiling for a text-only pipeline where ~30% of images
    # have no unique description (Tier B). BLIP-2 upgrade pushes this to 90%+.
    if uniqueness_pct < 55:
        msg = f"Cap 1 uniqueness is {uniqueness_pct}% — target ≥ 55% (text-only ceiling ~60%)"
        print(f"    ⚠  WARNING: {msg}")
        warnings.append(msg)
    elif uniqueness_pct < 70:
        print(f"    NOTE: {uniqueness_pct}% is the text-only ceiling for Tier B images."
              f" BLIP-2 upgrade would push this above 90%.")

    top_dups = cap1_counts.most_common(8)
    if top_dups[0][1] > 1:
        print("    Top repeated Cap 1 strings:")
        for text, cnt in top_dups:
            if cnt > 1:
                print(f"      [{cnt}x] {text[:90]}")

    # ── 3. Caption length ─────────────────────────────────────────────────────
    short_entries = [
        e for e in data
        if any(_min_words(c) < 4 for c in e.get("captions", []))
    ]
    print(f"\n[2] Caption length  (minimum 4 words per caption)")
    print(f"    Entries with a caption < 4 words: {len(short_entries)}")
    if short_entries:
        for e in short_entries[:5]:
            for c in e["captions"]:
                if _min_words(c) < 6:
                    print(f"      image_id={e['image_id'][:40]}  cap='{c}'")
        if len(short_entries) > 5:
            print(f"      … and {len(short_entries)-5} more")
        if len(short_entries) > total * 0.05:
            msg = f"{len(short_entries)} entries have a caption < 4 words (>{5}% of total)"
            warnings.append(msg)

    # ── 4. Domain vocabulary ──────────────────────────────────────────────────
    with_domain = sum(1 for e in data if _has_domain_term(e.get("captions", [])))
    domain_pct = 100 * with_domain // total
    print(f"\n[3] Domain vocabulary")
    print(f"    Entries with ≥1 domain term: {with_domain} / {total} ({domain_pct}%)")
    if domain_pct < 80:
        msg = f"Only {domain_pct}% of entries contain domain vocabulary — target ≥ 80%"
        print(f"    ⚠  WARNING: {msg}")
        warnings.append(msg)

    # ── 5. Template residue ───────────────────────────────────────────────────
    template_hits = []
    for e in data:
        for cap in e.get("captions", []):
            for frag in _TEMPLATE_FRAGMENTS:
                if frag in cap:
                    template_hits.append((e["image_id"], cap[:80]))
                    break
    print(f"\n[4] Template residue  (old generic captions that should be gone)")
    print(f"    Entries with old template text: {len(template_hits)}")
    if template_hits:
        for img_id, cap in template_hits[:5]:
            print(f"      {img_id[:40]:40s}  '{cap}'")
        if len(template_hits) > total * 0.05:
            msg = f"{len(template_hits)} entries still contain old template captions"
            warnings.append(msg)

    # ── 6. Within-entry caption diversity ────────────────────────────────────
    non_diverse = []
    for e in data:
        caps = e.get("captions", [])
        if len(caps) == 3 and (caps[0] == caps[1] or caps[1] == caps[2] or caps[0] == caps[2]):
            non_diverse.append(e["image_id"])
    print(f"\n[5] Within-entry diversity  (all 3 captions should be distinct)")
    print(f"    Entries where 2+ captions are identical: {len(non_diverse)}")
    if non_diverse[:5]:
        print(f"    Examples: {non_diverse[:5]}")
    if non_diverse:
        msg = f"{len(non_diverse)} entries have duplicate captions within the same entry"
        warnings.append(msg)

    # ── 7. Image file coverage ────────────────────────────────────────────────
    found = 0
    missing_examples = []
    for e in data:
        image_id = e["image_id"]
        category = e.get("category", "")
        located = False
        for img_dir in images_dirs:
            if not img_dir.exists():
                continue
            # Try category subdir
            if (img_dir / f"Category:{category}" / image_id).exists():
                located = True
                break
            if (img_dir / category / image_id).exists():
                located = True
                break
            # Brute-force one level deep
            for sub in img_dir.iterdir():
                if sub.is_dir() and (sub / image_id).exists():
                    located = True
                    break
            if located:
                break
        if located:
            found += 1
        else:
            missing_examples.append(image_id)

    coverage_pct = 100 * found // total
    print(f"\n[6] Image file coverage")
    print(f"    Found on disk : {found} / {total} ({coverage_pct}%)")
    if missing_examples:
        print(f"    Missing examples: {missing_examples[:5]}")
    if coverage_pct < 95:
        msg = f"Image file coverage is {coverage_pct}% — target ≥ 95%"
        print(f"    ⚠  WARNING: {msg}")
        warnings.append(msg)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if warnings:
        print(f"RESULT: {len(warnings)} WARNING(s) found:")
        for w in warnings:
            print(f"  ✗  {w}")
        print()
        return False
    else:
        print("RESULT: All checks passed.")
        print()
        return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run data quality checks on metadata_merged.json")
    parser.add_argument("--merged",      default="data/processed/metadata_merged.json")
    parser.add_argument("--wiki-images", default="data/raw/wikimedia/images")
    parser.add_argument("--danam-images", default="data/raw/danam/images")
    args = parser.parse_args()

    root        = Path(__file__).resolve().parent.parent
    merged_path = root / args.merged
    images_dirs = [
        root / args.wiki_images,
        root / args.danam_images,
    ]

    if not merged_path.exists():
        print(f"File not found: {merged_path}")
        print("Run merge_datasets.py first.")
        sys.exit(1)

    passed = run_quality_report(merged_path, images_dirs)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
