#!/usr/bin/env python3
"""
Generate an HTML gallery showing images with their captions.
Opens automatically in the browser.

Usage:
  python scripts/show_captions.py              # 30 random images
  python scripts/show_captions.py --n 60       # 60 random images
  python scripts/show_captions.py --type exterior
  python scripts/show_captions.py --type object
  python scripts/show_captions.py --seed 7
"""

import argparse
import base64
import json
import os
import random
import unicodedata
import webbrowser
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "data/raw/danam/images"
META_PATH  = ROOT / "data/processed/metadata_merged.json"
OUT_HTML   = ROOT / "data/processed/gallery.html"


def nfc(s):
    return unicodedata.normalize("NFC", s)


def build_lookup():
    lookup = {}
    for monument_dir in IMAGES_DIR.iterdir():
        if not monument_dir.is_dir():
            continue
        for img_file in monument_dir.iterdir():
            if img_file.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                lookup[nfc(img_file.name)] = img_file
    return lookup


def img_to_b64(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
            "webp": "webp", "gif": "gif"}.get(ext, "jpeg")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/{mime};base64,{data}"


def build_html(entries: list[dict], lookup: dict) -> str:
    cards = []
    for e in entries:
        fn   = nfc(e["image_id"])
        path = lookup.get(fn)
        if not path:
            continue

        src    = img_to_b64(path)
        itype  = e["image_type"]
        name   = e["monument_name"]
        label  = e["cultural_label"]
        cap1   = e["captions"][0]
        cap2   = e["captions"][1]
        badge_color = "#2563eb" if itype == "exterior" else "#7c3aed"

        cards.append(f"""
        <div class="card">
          <div class="img-wrap">
            <img src="{src}" alt="{name}" loading="lazy">
            <span class="badge" style="background:{badge_color}">{itype.upper()}</span>
          </div>
          <div class="info">
            <div class="monument-name">{name}</div>
            <div class="label">{label}</div>
            <div class="cap"><span class="cap-num">Cap 1</span>{cap1}</div>
            <div class="cap"><span class="cap-num">Cap 2</span>{cap2}</div>
          </div>
        </div>""")

    cards_html = "\n".join(cards)
    n_shown    = len(cards)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HeritageLens — Caption Gallery ({n_shown} images)</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f172a; color: #e2e8f0; min-height: 100vh;
  }}
  header {{
    padding: 24px 32px 16px;
    border-bottom: 1px solid #1e293b;
    display: flex; align-items: center; gap: 16px;
  }}
  header h1 {{ font-size: 1.5rem; font-weight: 700; color: #f8fafc; }}
  header p  {{ font-size: 0.85rem; color: #94a3b8; margin-top: 4px; }}
  .dot-ext {{ width:10px;height:10px;border-radius:50%;background:#2563eb;display:inline-block;margin-right:4px; }}
  .dot-obj {{ width:10px;height:10px;border-radius:50%;background:#7c3aed;display:inline-block;margin-right:4px; }}
  .legend  {{ margin-left:auto; display:flex; gap:16px; font-size:0.8rem; color:#94a3b8; align-items:center; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 20px;
    padding: 24px 32px;
  }}
  .card {{
    background: #1e293b;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #334155;
    transition: transform .15s, box-shadow .15s;
  }}
  .card:hover {{
    transform: translateY(-3px);
    box-shadow: 0 8px 24px rgba(0,0,0,.4);
  }}
  .img-wrap {{
    position: relative;
    width: 100%;
    height: 220px;
    background: #0f172a;
    overflow: hidden;
  }}
  .img-wrap img {{
    width:100%; height:100%; object-fit:cover;
    transition: transform .3s;
  }}
  .card:hover .img-wrap img {{ transform: scale(1.04); }}
  .badge {{
    position: absolute; top: 10px; left: 10px;
    font-size: 0.68rem; font-weight: 700; letter-spacing: .06em;
    padding: 3px 8px; border-radius: 4px; color: #fff;
  }}
  .info {{ padding: 14px 16px 16px; }}
  .monument-name {{
    font-size: 0.92rem; font-weight: 600; color: #f1f5f9;
    margin-bottom: 3px; line-height: 1.3;
  }}
  .label {{
    font-size: 0.72rem; color: #64748b; text-transform: uppercase;
    letter-spacing: .05em; margin-bottom: 10px;
  }}
  .cap {{
    font-size: 0.8rem; color: #cbd5e1; line-height: 1.5;
    margin-top: 7px; padding: 8px 10px;
    background: #0f172a; border-radius: 6px;
    border-left: 3px solid #334155;
  }}
  .cap-num {{
    display: inline-block;
    font-size: 0.65rem; font-weight: 700; letter-spacing: .06em;
    color: #38bdf8; margin-right: 6px; text-transform: uppercase;
  }}
</style>
</head>
<body>
<header>
  <div>
    <h1>HeritageLens — Caption Gallery</h1>
    <p>Showing {n_shown} images from 227 Nepali heritage monuments</p>
  </div>
  <div class="legend">
    <span><span class="dot-ext"></span>Exterior</span>
    <span><span class="dot-obj"></span>Object</span>
  </div>
</header>
<div class="grid">
{cards_html}
</div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Caption gallery viewer")
    parser.add_argument("--n",        type=int, default=30)
    parser.add_argument("--type",     choices=["exterior", "object", "all"], default="all")
    parser.add_argument("--seed",     type=int, default=42)
    parser.add_argument("--metadata", default=str(META_PATH),
                        help="Path to metadata JSON (default: metadata_merged.json)")
    args = parser.parse_args()

    meta_path = Path(args.metadata)
    with open(meta_path) as f:
        data = json.load(f)

    if args.type != "all":
        data = [e for e in data if e["image_type"] == args.type]

    random.seed(args.seed)
    sample = random.sample(data, min(args.n, len(data)))
    # Sort: exteriors first, then objects
    sample.sort(key=lambda e: (0 if e["image_type"] == "exterior" else 1))

    lookup = build_lookup()

    print(f"Building gallery for {len(sample)} images from {meta_path.name}...")
    html = build_html(sample, lookup)

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Saved: {OUT_HTML}")
    abs_path = OUT_HTML.resolve()
    webbrowser.open(f"file://{abs_path}")
    print("Opened in browser.")


if __name__ == "__main__":
    main()
