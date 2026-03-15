#!/usr/bin/env python3
"""
Batch caption preview for HeritageLens.

Prints N random entries from the metadata JSON, grouped by type,
so you can review caption quality before training.

Usage:
  python scripts/batch_preview.py              # 20 random entries
  python scripts/batch_preview.py --n 40       # 40 random entries
  python scripts/batch_preview.py --type exterior   # only exterior
  python scripts/batch_preview.py --type object     # only object
  python scripts/batch_preview.py --problems        # show flagged entries only
  python scripts/batch_preview.py --stats           # summary statistics
"""

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_data(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def flag_issues(entry: dict) -> list[str]:
    issues = []
    for i, cap in enumerate(entry["captions"][:2], 1):
        if "Unspecified" in cap:
            issues.append(f"cap{i}: contains 'Unspecified'")
        if "0.0" in cap:
            issues.append(f"cap{i}: contains '0.0'")
        if "A object at" in cap:
            issues.append(f"cap{i}: placeholder")
        if len(cap.split()) < 4:
                issues.append(f"cap{i}: too short ({len(cap.split())} words)")
        if cap.count(",") > 6:
            issues.append(f"cap{i}: too many commas")
    return issues


def print_entry(entry: dict, idx: int, show_cap3: bool = False):
    issues = flag_issues(entry)
    flag   = " ⚠️  ISSUES" if issues else ""
    itype  = entry["image_type"].upper()
    print(f"\n{'─'*70}")
    print(f"[{idx}] [{itype}]{flag}  {entry['monument_name'][:55]}")
    print(f"      file : {entry['image_id']}")
    print(f"      label: {entry['cultural_label'][:50]}")
    for i, cap in enumerate(entry["captions"][:2], 1):
        mark = "▶" if i <= 2 else " "
        print(f"  {mark} Cap {i}: {cap}")
    if show_cap3 and len(entry["captions"]) > 2:
        print(f"    Cap 3: {entry['captions'][2]}")
    if issues:
        for issue in issues:
            print(f"    ⚠️  {issue}")


def print_stats(data: list[dict]):
    total  = len(data)
    ext_n  = sum(1 for e in data if e["image_type"] == "exterior")
    obj_n  = sum(1 for e in data if e["image_type"] == "object")

    cap1s  = [e["captions"][0] for e in data]
    cap2s  = [e["captions"][1] for e in data]

    import statistics
    c1_lens = [len(c.split()) for c in cap1s]
    c2_lens = [len(c.split()) for c in cap2s]

    # Problem counts
    n_unspec  = sum(1 for c in cap1s if "Unspecified" in c)
    n_zero    = sum(1 for c in cap1s if "0.0" in c)
    n_ph      = sum(1 for e in data if "A object at" in e["captions"][1])
    n_short1  = sum(1 for c in cap1s if len(c.split()) < 6)
    n_dup_c1  = total - len(set(cap1s))

    # Monument diversity
    monuments = Counter(e["monument_name"] for e in data)
    types     = Counter(e["cultural_label"] for e in data)

    print("\n" + "═" * 70)
    print("DATASET STATISTICS")
    print("═" * 70)
    print(f"  Total entries     : {total}")
    print(f"  Exterior images   : {ext_n}  ({100*ext_n//total}%)")
    print(f"  Object images     : {obj_n}  ({100*obj_n//total}%)")
    print(f"  Unique monuments  : {len(monuments)}")
    print()
    print(f"  Cap 1 lengths     : min={min(c1_lens)} avg={statistics.mean(c1_lens):.1f} max={max(c1_lens)}")
    print(f"  Cap 2 lengths     : min={min(c2_lens)} avg={statistics.mean(c2_lens):.1f} max={max(c2_lens)}")
    print(f"  Cap 1 unique      : {len(set(cap1s))}/{total} ({100*len(set(cap1s))//total}%)")
    print(f"  Cap 1 duplicates  : {n_dup_c1}")
    print()
    print(f"  ── ISSUES ──────────────────────────────────────────────────")
    print(f"  'Unspecified' in cap1  : {n_unspec}")
    print(f"  '0.0' values in cap1   : {n_zero}")
    print(f"  Placeholder cap2       : {n_ph}")
    print(f"  Cap 1 < 6 words        : {n_short1}")
    print()
    print(f"  ── TOP MONUMENT TYPES ───────────────────────────────────────")
    for mtype, cnt in types.most_common(8):
        print(f"    {cnt:4d}  {mtype[:55]}")
    print()

    # Avg images per monument
    imgs_per_mon = Counter(e["monument_name"] for e in data)
    avg = sum(imgs_per_mon.values()) / len(imgs_per_mon)
    print(f"  Avg images/monument : {avg:.1f}")
    cnt_3plus = sum(1 for v in imgs_per_mon.values() if v >= 3)
    cnt_1     = sum(1 for v in imgs_per_mon.values() if v == 1)
    print(f"  Monuments with ≥3 imgs : {cnt_3plus}")
    print(f"  Monuments with only 1  : {cnt_1}")
    print("═" * 70)


def main():
    parser = argparse.ArgumentParser(description="Caption batch preview")
    parser.add_argument("--metadata",  default="data/processed/metadata_merged.json")
    parser.add_argument("--n",         type=int, default=20,    help="Entries to show")
    parser.add_argument("--type",      choices=["exterior", "object", "all"], default="all")
    parser.add_argument("--problems",  action="store_true",     help="Show only flagged entries")
    parser.add_argument("--stats",     action="store_true",     help="Show statistics only")
    parser.add_argument("--cap3",      action="store_true",     help="Also show Cap 3")
    parser.add_argument("--seed",      type=int, default=42,    help="Random seed")
    args = parser.parse_args()

    meta_path = ROOT / args.metadata
    if not meta_path.exists():
        print(f"[ERROR] Not found: {meta_path}")
        return

    data = load_data(meta_path)

    if args.stats:
        print_stats(data)
        return

    # Filter by type
    if args.type != "all":
        data = [e for e in data if e["image_type"] == args.type]

    # Filter by problems
    if args.problems:
        data = [e for e in data if flag_issues(e)]
        if not data:
            print("No entries with issues found!")
            return
        print(f"Found {len(data)} entries with issues.")

    random.seed(args.seed)
    sample = random.sample(data, min(args.n, len(data)))

    # Group by type for cleaner display
    ext_sample = [e for e in sample if e["image_type"] == "exterior"]
    obj_sample = [e for e in sample if e["image_type"] == "object"]

    print(f"\n{'═'*70}")
    print(f"CAPTION BATCH PREVIEW  ({len(sample)} entries, seed={args.seed})")
    print(f"  ▶ = training captions (Cap 1 & 2 only)")
    print(f"{'═'*70}")

    if ext_sample:
        print(f"\n{'━'*70}")
        print(f"  EXTERIOR IMAGES ({len(ext_sample)})")
        print(f"{'━'*70}")
        for i, e in enumerate(ext_sample, 1):
            print_entry(e, i, show_cap3=args.cap3)

    if obj_sample:
        print(f"\n{'━'*70}")
        print(f"  OBJECT IMAGES ({len(obj_sample)})")
        print(f"{'━'*70}")
        for i, e in enumerate(obj_sample, 1):
            print_entry(e, len(ext_sample) + i, show_cap3=args.cap3)

    print(f"\n{'═'*70}")
    all_issues = [e for e in sample if flag_issues(e)]
    print(f"  Entries with issues: {len(all_issues)}/{len(sample)}")
    print(f"{'═'*70}")


if __name__ == "__main__":
    main()
