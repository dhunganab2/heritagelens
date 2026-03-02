#!/usr/bin/env python3
"""
DANAM API scraper for Nepali heritage monument images.

Fetches monument data from the Digital Archive of Nepalese Arts and Monuments
(DANAM, https://danam.cats.uni-heidelberg.de) via its Arches REST API.

Downloads images with captions into data/raw/danam/, stored separately from
the Wikimedia dataset so both can be merged later for model training.

API structure:
  - Listing:  GET /resources/?format=json  →  list of resource UUIDs
  - Detail:   GET /resources/<uuid>?format=json  →  full monument JSON
  - Images:   GET /files/uploadedfiles/<name>.jpg  →  image bytes
  - Monument graph_id: f35cc1ca-9322-11e9-a5cc-0242ac120006
"""

import csv
import html
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://danam.cats.uni-heidelberg.de"
MONUMENT_GRAPH_ID = "f35cc1ca-9322-11e9-a5cc-0242ac120006"

HEADERS = {
    "User-Agent": "HeritageLensBot/1.0 (NKU Senior Project; Nepal Heritage Captioning)",
    "Accept": "application/json",
}


# ── Text cleaning helpers ─────────────────────────────────────────────────────

def _clean_html(raw: str) -> str:
    """Strip HTML tags, decode entities, normalise whitespace."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clean_caption(raw_caption: str) -> str:
    """Clean a DANAM image caption — keep the descriptive part, drop credits."""
    text = _clean_html(raw_caption)
    text = re.sub(r";\s*photo\s+by\s+.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r";\s*courtesy\s+of\s+.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r";\s*source\s*:.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r";\s*free\s+access.*$", "", text, flags=re.IGNORECASE)
    text = text.strip().rstrip(";, ")
    return text


def _is_reusable(caption: str | None) -> bool:
    """Return False if the image has a 'no reuse' restriction."""
    if not caption:
        return True
    return "no reuse" not in caption.lower()


def _extract_monument_name(displayname: str) -> str:
    """Extract the English name from displayname.
    Format: 'English Name (date info) || नेपाली || CODE'
    """
    parts = displayname.split("||")
    name = parts[0].strip()
    name = re.sub(r"\s*\|\*\|\s*\w+\s*$", "", name).strip()
    return name


def _safe_dirname(name: str, max_len: int = 50) -> str:
    """Create a filesystem-safe directory name from monument name."""
    safe = re.sub(r"[^\w\s-]", "", name)[:max_len].strip()
    return safe.replace(" ", "_") or "unknown"


# ── Smart image selection ─────────────────────────────────────────────────────

# Keywords that indicate a photo shows something distinct (detail, interior, etc.)
# rather than just another angle of the same exterior.
_DETAIL_KEYWORDS = [
    "detail", "close", "door", "entrance", "toraṇa", "torana", "strut",
    "window", "carving", "statue", "sculpture", "image", "interior",
    "sanctum", "pinnacle", "roof", "plinth", "column", "capital",
    "inscription", "painting", "fresco", "niche", "lintel",
]


def _caption_signature(caption: str) -> str:
    """Reduce a caption to a rough 'type' so we can detect near-duplicates."""
    lower = _clean_html(caption).lower()
    for kw in _DETAIL_KEYWORDS:
        if kw in lower:
            return kw
    direction = re.search(r"view from (\w+)", lower)
    if direction:
        return f"view-{direction.group(1)}"
    return "generic"


def _pick_diverse(images: list[dict], n: int) -> list[dict]:
    """Choose up to n images that show different aspects of the monument.

    Picking strategy:
      1. One overall exterior view (prefer post-2015)
      2. One architectural detail / close-up
      3. One more unique shot (different feature or era)
    """
    by_sig: dict[str, list[dict]] = {}
    for img in images:
        sig = _caption_signature(img["raw_caption"])
        by_sig.setdefault(sig, []).append(img)

    picked: list[dict] = []
    used_sigs: set[str] = set()

    # First: pick one overall view
    for sig, group in by_sig.items():
        if sig.startswith("view-") or sig == "generic":
            new_era = [g for g in group if g["era"] == "new"]
            picked.append(new_era[0] if new_era else group[0])
            used_sigs.add(sig)
            break

    # Second: pick detail shots from different categories
    for sig, group in by_sig.items():
        if len(picked) >= n:
            break
        if sig in used_sigs:
            continue
        new_era = [g for g in group if g["era"] == "new"]
        picked.append(new_era[0] if new_era else group[0])
        used_sigs.add(sig)

    # Fill remaining slots from unused images
    if len(picked) < n:
        for img in images:
            if len(picked) >= n:
                break
            if img not in picked:
                picked.append(img)

    return picked[:n]


# ── Main scraper class ────────────────────────────────────────────────────────

class DANAMScraper:
    """Scrape monument images + captions from the DANAM Arches API."""

    def __init__(self, output_dir: str = "data/raw/danam"):
        self.output_dir = Path(output_dir)
        self.images_dir = self.output_dir / "images"
        self.manifest_path = self.output_dir / "manifest.csv"
        self.cache_dir = self.output_dir / ".cache"
        self.uuid_cache_path = self.cache_dir / "all_uuids.json"
        self.processed_cache_path = self.cache_dir / "processed_uuids.json"

        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._init_manifest()

    # ── Manifest I/O ──────────────────────────────────────────────────────────

    def _init_manifest(self):
        if not self.manifest_path.exists():
            with open(self.manifest_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    "filename", "monument_id", "monument_name",
                    "image_caption", "monument_description",
                    "latitude", "longitude",
                    "download_date", "source_url",
                ])

    def _append_manifest(self, row: dict):
        with open(self.manifest_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                row.get("filename"),
                row.get("monument_id"),
                row.get("monument_name"),
                row.get("image_caption"),
                row.get("monument_description"),
                row.get("latitude", ""),
                row.get("longitude", ""),
                row.get("download_date"),
                row.get("source_url"),
            ])

    # ── Resume cache ──────────────────────────────────────────────────────────

    def _load_processed(self) -> set[str]:
        if self.processed_cache_path.exists():
            with open(self.processed_cache_path) as f:
                return set(json.load(f))
        return set()

    def _save_processed(self, processed: set[str]):
        with open(self.processed_cache_path, "w") as f:
            json.dump(sorted(processed), f)

    # ── UUID listing ──────────────────────────────────────────────────────────

    def get_uuids(self, max_pages: int = 6) -> list[str]:
        """Fetch resource UUIDs from the DANAM listing endpoint (cached).

        Only fetches `max_pages` pages (500 UUIDs each). The full archive has
        45K+ resources but most are inscriptions; 3000 UUIDs is plenty to find
        250+ monuments.
        """
        if self.uuid_cache_path.exists():
            with open(self.uuid_cache_path) as f:
                uuids = json.load(f)
            print(f"  Loaded {len(uuids)} cached UUIDs")
            return uuids

        print(f"  Fetching resource listing ({max_pages} pages)...")
        all_uuids: list[str] = []

        for page in range(1, max_pages + 1):
            url = f"{BASE_URL}/resources/?format=json&paging-filter={page}"
            try:
                r = self.session.get(url, timeout=120)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                print(f"  [ERROR] page {page}: {e}")
                break

            raw_urls = data.get("ldp:contains", [])
            if not raw_urls:
                break

            for u in raw_urls:
                uid = u.rstrip("/").split("/")[-1]
                if len(uid) == 36 and "-" in uid:
                    all_uuids.append(uid)

            print(f"    Page {page}: +{len(raw_urls)}  (total: {len(all_uuids)})")
            time.sleep(1)

        all_uuids = list(dict.fromkeys(all_uuids))
        with open(self.uuid_cache_path, "w") as f:
            json.dump(all_uuids, f)

        print(f"  {len(all_uuids)} unique UUIDs ready")
        return all_uuids

    # ── Resource fetch ────────────────────────────────────────────────────────

    def fetch_resource(self, uuid: str) -> dict | None:
        """Fetch a single resource JSON. Returns None on permanent failure."""
        url = f"{BASE_URL}/resources/{uuid}?format=json"
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code == 429:
                    wait = 15 * (attempt + 1)
                    print(f"    [429] sleeping {wait}s ...")
                    time.sleep(wait)
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                time.sleep(5)
            except Exception as e:
                if attempt == 2:
                    print(f"    [ERROR] {uuid[:12]}...: {e}")
                time.sleep(3)
        return None

    # ── Image extraction from monument JSON ───────────────────────────────────

    def _extract_images(self, resource: dict, max_per_monument: int = 3) -> list[dict]:
        """Pick up to `max_per_monument` diverse images from a monument.

        Strategy: prefer images whose captions mention different features
        (e.g. "façade", "detail", "door", "statue") over many near-identical
        "view from N / NE / NW" shots.  Prioritise post-2015 photos.
        """
        res = resource.get("resource") or {}
        all_imgs: list[dict] = []

        for entry in res.get("Imagesafter2015", []):
            img_data = entry.get("imageafter2015", {})
            if isinstance(img_data, str):
                continue
            path = img_data.get("@value", "")
            caption = img_data.get("imageafter2015caption", "")
            if path and _is_reusable(caption):
                all_imgs.append({"path": path, "raw_caption": caption, "era": "new"})

        for entry in res.get("Imagesbefore2015", []):
            img_data = entry.get("Imagebefore2015", {})
            if isinstance(img_data, str):
                continue
            path = img_data.get("@value", "")
            caption = img_data.get("imagebefore2015caption", "")
            if path and _is_reusable(caption):
                all_imgs.append({"path": path, "raw_caption": caption, "era": "old"})

        if len(all_imgs) <= max_per_monument:
            return all_imgs

        return _pick_diverse(all_imgs, max_per_monument)

    def _extract_geo(self, resource: dict) -> tuple[str, str]:
        """Extract (latitude, longitude) from the resource's geocoordinate."""
        res = resource.get("resource") or {}
        geo_str = ""
        for key in ("Monument Geocoordinate", "Inscription geocoordinate"):
            geo_str = res.get(key, "")
            if geo_str:
                break
        if not geo_str:
            return "", ""
        try:
            if isinstance(geo_str, str):
                geo = json.loads(geo_str.replace("'", '"'))
            else:
                geo = geo_str
            coords = geo["features"][0]["geometry"]["coordinates"]
            return str(coords[1]), str(coords[0])
        except Exception:
            return "", ""

    # ── Image download ────────────────────────────────────────────────────────

    def download_image(self, img_path: str, save_path: Path) -> bool:
        """Download a single image from DANAM. Returns True on success."""
        url = BASE_URL + img_path
        for attempt in range(3):
            try:
                r = self.session.get(url, stream=True, timeout=60)
                if r.status_code == 429:
                    time.sleep(15 * (attempt + 1))
                    continue
                if r.status_code in (403, 404):
                    return False
                r.raise_for_status()
                ct = r.headers.get("content-type", "")
                if "image" not in ct:
                    return False
                with open(save_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        if chunk:
                            f.write(chunk)
                return True
            except Exception as e:
                if attempt == 2:
                    print(f"      [download error] {e}")
                time.sleep(3)
        return False

    # ── Main entry ────────────────────────────────────────────────────────────

    def scrape_all(self, max_monuments: int = 250):
        """Scrape monuments until we have `max_monuments` with images.

        With 3 images per monument, 250 monuments → ~750 DANAM images.
        Combined with ~600 Wikimedia images = ~1350 total for training.
        """
        print("\n" + "=" * 60)
        print("DANAM HERITAGE MONUMENT IMAGE SCRAPER")
        print(f"  Target: {max_monuments} monuments × 3 imgs = ~{max_monuments * 3} images")
        print("=" * 60)

        uuids = self.get_uuids()
        if not uuids:
            print("No UUIDs found. Exiting.")
            return

        processed = self._load_processed()
        pending = [u for u in uuids if u not in processed]

        print(f"  UUIDs to check    : {len(pending)} (of {len(uuids)} total)")
        print(f"  Already processed : {len(processed)}")

        monuments_found = 0
        images_downloaded = 0
        skipped_other = 0

        try:
            for idx, uuid in enumerate(pending, 1):
                if monuments_found >= max_monuments:
                    print(f"\n  Reached target of {max_monuments} monuments — stopping.")
                    break

                if idx % 50 == 0:
                    print(f"\n  --- Progress: checked {idx}/{len(pending)}, "
                          f"{monuments_found} monuments, {images_downloaded} imgs ---")
                    self._save_processed(processed)

                time.sleep(random.uniform(0.3, 0.8))

                resource = self.fetch_resource(uuid)
                if not resource:
                    processed.add(uuid)
                    continue

                if resource.get("graph_id") != MONUMENT_GRAPH_ID:
                    skipped_other += 1
                    processed.add(uuid)
                    continue

                monuments_found += 1
                name = _extract_monument_name(resource.get("displayname", ""))
                description = _clean_html(resource.get("displaydescription", ""))
                monument_id = resource.get("resourceinstanceid", uuid)
                lat, lon = self._extract_geo(resource)
                images = self._extract_images(resource)

                if not images:
                    processed.add(uuid)
                    continue

                safe_name = _safe_dirname(name)
                monument_dir = self.images_dir / f"{safe_name}_{monument_id[:8]}"
                monument_dir.mkdir(parents=True, exist_ok=True)

                print(f"\n  [{idx}/{len(pending)}] {name[:55]}  "
                      f"(picking {len(images)} of available)")

                for img_idx, img in enumerate(images, 1):
                    caption = _clean_caption(img["raw_caption"])
                    ext = Path(img["path"]).suffix.lower() or ".jpg"
                    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                        ext = ".jpg"
                    filename = f"{safe_name}_{img_idx:03d}{ext}"
                    save_path = monument_dir / filename

                    if save_path.exists():
                        continue

                    time.sleep(random.uniform(0.3, 1.0))

                    if self.download_image(img["path"], save_path):
                        self._append_manifest({
                            "filename": filename,
                            "monument_id": monument_id,
                            "monument_name": name,
                            "image_caption": caption,
                            "monument_description": description[:500],
                            "latitude": lat,
                            "longitude": lon,
                            "download_date": datetime.now().isoformat(),
                            "source_url": f"{BASE_URL}/resources/{uuid}",
                        })
                        images_downloaded += 1
                        print(f"    {img_idx}. {caption[:75]}")

                processed.add(uuid)

        except KeyboardInterrupt:
            print("\n\nInterrupted — saving progress...")

        self._save_processed(processed)

        total_on_disk = sum(
            1 for d in self.images_dir.rglob("*") if d.is_file()
        )
        print("\n" + "=" * 60)
        print("DANAM SCRAPING COMPLETE")
        print(f"  Monuments found    : {monuments_found}")
        print(f"  Images downloaded  : {images_downloaded}")
        print(f"  Images on disk     : {total_on_disk}")
        print(f"  Non-monuments skip : {skipped_other}")
        print(f"  Manifest           : {self.manifest_path}")
        print("=" * 60)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scrape DANAM monument images")
    parser.add_argument("--max-monuments", type=int, default=250,
                        help="Stop after this many monuments (default 250)")
    parser.add_argument("--max-pages", type=int, default=6,
                        help="UUID listing pages to fetch (500 each, default 6)")
    args = parser.parse_args()

    scraper = DANAMScraper(output_dir="data/raw/danam")
    scraper.scrape_all(max_monuments=args.max_monuments)


if __name__ == "__main__":
    main()
