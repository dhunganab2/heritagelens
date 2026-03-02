#!/usr/bin/env python3
"""
Convert Google Sheets CSV (from Person C) to metadata.json format.
Expected columns: image_name, cultural_label, caption_1, caption_2, caption_3
"""

import argparse
import csv
import json
from pathlib import Path


REQUIRED_COLUMNS = ["image_name", "cultural_label", "caption_1", "caption_2", "caption_3"]


def convert_csv_to_json(csv_path: Path, output_path: Path) -> list[dict]:
    """Read CSV and write metadata.json. Validates required columns."""
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
            if missing:
                raise ValueError(f"CSV missing columns: {missing}. Required: {REQUIRED_COLUMNS}")
        data = []
        for row in reader:
            entry = {
                "image_id": row["image_name"].strip(),
                "cultural_label": row["cultural_label"].strip(),
                "captions": [
                    row["caption_1"].strip(),
                    row["caption_2"].strip(),
                    row["caption_3"].strip(),
                ],
            }
            data.append(entry)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Converted {len(data)} rows to {output_path}")
    return data


def main():
    parser = argparse.ArgumentParser(description="Convert Google Sheets CSV to metadata.json")
    parser.add_argument("--input", "-i", required=True, help="Input CSV path")
    parser.add_argument("--output", "-o", default="metadata.json", help="Output JSON path")
    args = parser.parse_args()

    csv_path = Path(args.input)
    output_path = Path(args.output)
    if not csv_path.is_absolute():
        csv_path = csv_path.resolve()

    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        return
    convert_csv_to_json(csv_path, output_path)


if __name__ == "__main__":
    main()
