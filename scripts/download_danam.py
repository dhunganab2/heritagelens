#!/usr/bin/env python3
"""
DANAM API scraper v3 — multi-image mode.

Per monument downloads up to MAX_EXT exterior + MAX_OBJ object images,
giving 3–6× more training data from the same 500 monuments.

Existing images on disk are reused; only new ones are downloaded.
Run with --reset-processed to re-scan all monuments for additional images.

API structure:
  Listing : GET /resources/?format=json&paging-filter=N
  Detail  : GET /resources/<uuid>?format=json
  Images  : GET /files/<file_id>
  Monument graph_id: f35cc1ca-9322-11e9-a5cc-0242ac120006
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

BASE_URL      = "https://danam.cats.uni-heidelberg.de"
MONUMENT_GRAPH_ID = "f35cc1ca-9322-11e9-a5cc-0242ac120006"

HEADERS = {
    "User-Agent": "HeritageLensBot/3.0 (NKU Senior Project; Nepal Heritage Captioning)",
    "Accept":     "application/json",
}

MANIFEST_COLUMNS = [
    "filename", "monument_id", "monument_name", "image_caption",
    "image_type",           # "exterior" or "object"
    "monument_description",
    # Typology
    "monument_type", "religion", "deity",
    # Architecture
    "roof_type", "num_struts", "strut_iconography", "brick_type",
    "num_doors", "num_storeys", "num_windows", "door_peculiarities",
    "monument_shape",
    # Object (only for image_type=object)
    "object_id", "object_type", "object_material", "object_position",
    # Geo
    "latitude", "longitude",
    "download_date", "source_url",
]

# Object types ranked by visual interest (lower index = higher priority)
_OBJECT_PRIORITY = [
    "Toraṇa (tympanum)", "Torana", "Statue", "Sculpture", "Relief",
    "Shrine", "Caitya", "Stūpa", "Bell", "Pillar", "Column",
    "Liṅga", "Foundation", "Ritual object", "Platform",
    "Aniconic stone", "(Sacred) object",
]


# ── Text helpers ───────────────────────────────────────────────────────────────

def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_caption(raw_caption: str) -> str:
    text = _clean_html(raw_caption)
    text = re.sub(r";\s*photo\s+by\s+.*$",   "", text, flags=re.IGNORECASE)
    text = re.sub(r";\s*courtesy\s+of\s+.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r";\s*source\s*:.*$",        "", text, flags=re.IGNORECASE)
    text = re.sub(r";\s*free\s+access.*$",     "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(";, ")


def _is_reusable(caption: str | None) -> bool:
    if not caption:
        return True
    return "no reuse" not in caption.lower()


def _extract_monument_name(displayname: str) -> str:
    parts = displayname.split("||")
    name  = parts[0].strip()
    return re.sub(r"\s*\|\*\|\s*\w+\s*$", "", name).strip()


def _safe_dirname(name: str, max_len: int = 50) -> str:
    safe = re.sub(r"[^\w\s-]", "", name)[:max_len].strip()
    return safe.replace(" ", "_") or "unknown"


def _first_sentence(text: str, max_len: int = 300) -> str:
    if not text:
        return ""
    m        = re.match(r"([^.!?]+[.!?])", text.strip())
    sentence = m.group(1).strip() if m else text.strip()
    if len(sentence) > max_len:
        sentence = sentence[:max_len].rsplit(" ", 1)[0] + "."
    return sentence


# ── Structured data extraction ─────────────────────────────────────────────────

def _extract_typology(resource: dict) -> dict:
    res = resource.get("resource") or {}
    typ = res.get("Typology", {})
    return {
        "monument_type": typ.get("Monument type", ""),
        "religion":      typ.get("monument type religion", ""),
        "deity":         typ.get("monument main diety", ""),
    }


def _extract_architecture(resource: dict) -> dict:
    res   = resource.get("resource") or {}
    arch  = res.get("Architectural details", {})
    roof  = arch.get("Monument roof", {})
    walls = arch.get("Monument walls", {})
    basic = arch.get("monument architecture basic ", {})
    wins  = arch.get("monument windows doors", {})
    return {
        "roof_type":         roof.get("Type of roof", ""),
        "num_struts":        roof.get("Number of struts", ""),
        "strut_iconography": roof.get("Iconography of struts", ""),
        "brick_type":        walls.get("Type of bricks", ""),
        "num_doors":         wins.get("number of doors", ""),
        "num_storeys":       basic.get("Number of storeys", ""),
        "num_windows":       wins.get("number of wood carved w", ""),
        "door_peculiarities":wins.get("Peculiarities of doors and windows", ""),
        "monument_shape":    basic.get("Monument Shape", ""),
    }


def _extract_description(resource: dict) -> str:
    res          = resource.get("resource") or {}
    desc_section = res.get("Monument description", {})
    for key in ("Detailed description", "Short Description", "Architectural description"):
        raw = desc_section.get(key, "")
        if raw:
            cleaned = _clean_html(raw)
            if len(cleaned) >= 20:
                return _first_sentence(cleaned)
    return ""


def _extract_geo(resource: dict) -> tuple[str, str]:
    res     = resource.get("resource") or {}
    geo_raw = res.get("Spatial Coordinates Geometry", "")
    if not geo_raw:
        return "", ""
    try:
        if isinstance(geo_raw, str):
            geo = json.loads(geo_raw.replace("'", '"'))
        else:
            geo = geo_raw
        coords = geo.get("coordinates", [])
        if coords and len(coords) >= 2:
            return str(coords[1]), str(coords[0])
    except Exception:
        pass
    return "", ""


# ── Image extraction — multi-image ────────────────────────────────────────────

def _extract_top_exteriors(resource: dict, max_n: int = 3) -> list[dict]:
    """Return up to max_n exterior images, preferring post-2015."""
    res        = resource.get("resource") or {}
    candidates = []

    for entry in res.get("Imagesafter2015", []):
        img_data = entry.get("imageafter2015", {})
        if isinstance(img_data, str):
            continue
        path    = img_data.get("@value", "")
        caption = img_data.get("imageafter2015caption", "")
        if path and _is_reusable(caption):
            candidates.append({"path": path, "caption": caption, "era": "new"})

    for entry in res.get("Imagesbefore2015", []):
        img_data = entry.get("Imagebefore2015", {})
        if isinstance(img_data, str):
            continue
        path    = img_data.get("@value", "")
        caption = img_data.get("imagebefore2015caption", "")
        if path and _is_reusable(caption):
            candidates.append({"path": path, "caption": caption, "era": "old"})

    if not candidates:
        return []

    # New-era first, then old-era; deduplicate by path
    seen = set()
    ordered = []
    for era in ("new", "old"):
        for c in candidates:
            if c["era"] == era and c["path"] not in seen:
                seen.add(c["path"])
                ordered.append(c)

    return ordered[:max_n]


def _object_priority_score(obj_type: str) -> int:
    obj_lower = obj_type.lower()
    for i, ptype in enumerate(_OBJECT_PRIORITY):
        if ptype.lower() in obj_lower or obj_lower in ptype.lower():
            return i
    return len(_OBJECT_PRIORITY)


def _extract_top_objects(resource: dict, max_n: int = 3) -> list[dict]:
    """Return up to max_n objects, prioritised by visual interest.
    Picks diverse object types when possible."""
    res     = resource.get("resource") or {}
    objects = res.get("Objects", [])
    if not objects:
        return []

    scored = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        basic    = obj.get("Object basic data ", {})
        if not isinstance(basic, dict):
            basic = {}
        typology = obj.get("object typology", {})
        if not isinstance(typology, dict):
            typology = {}

        obj_type = typology.get("object type", "")
        material = typology.get("object material", "")
        position = typology.get("object relative position", "")
        obj_id   = basic.get("Object identification number", "")
        caption  = _clean_caption(basic.get("Object image caption", ""))
        img_path = basic.get("Object image", "")

        if not img_path or not _is_reusable(caption):
            continue

        score = _object_priority_score(obj_type)
        scored.append({
            "path":        img_path,
            "caption":     caption,
            "object_id":   obj_id,
            "object_type": obj_type,
            "material":    material,
            "position":    position,
            "score":       score,
        })

    scored.sort(key=lambda x: x["score"])

    # Pick max_n with diverse types (avoid duplicating the same type)
    chosen    = []
    used_types = []
    # First pass: best of each unique type
    for item in scored:
        t = item["object_type"].lower()
        if t not in used_types:
            used_types.append(t)
            chosen.append(item)
        if len(chosen) >= max_n:
            break

    # Second pass: fill up if we still need more
    if len(chosen) < max_n:
        for item in scored:
            if item not in chosen:
                chosen.append(item)
            if len(chosen) >= max_n:
                break

    return chosen


# ── Main scraper ───────────────────────────────────────────────────────────────

class DANAMScraper:
    def __init__(self, output_dir: str = "data/raw/danam",
                 max_ext: int = 3, max_obj: int = 3):
        self.output_dir           = Path(output_dir)
        self.images_dir           = self.output_dir / "images"
        self.manifest_path        = self.output_dir / "manifest.csv"
        self.cache_dir            = self.output_dir / ".cache"
        self.uuid_cache_path      = self.cache_dir / "all_uuids.json"
        self.processed_cache_path = self.cache_dir / "processed_uuids.json"
        self.max_ext              = max_ext
        self.max_obj              = max_obj

        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._init_manifest()

    def _init_manifest(self):
        if not self.manifest_path.exists():
            with open(self.manifest_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(MANIFEST_COLUMNS)

    def _load_manifest_filenames(self) -> set[str]:
        """Return set of filenames already in manifest (for dedup)."""
        if not self.manifest_path.exists():
            return set()
        with open(self.manifest_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return {row["filename"] for row in reader}

    def _append_manifest(self, row: dict):
        with open(self.manifest_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([row.get(col, "") for col in MANIFEST_COLUMNS])

    def _load_processed(self) -> set[str]:
        if self.processed_cache_path.exists():
            with open(self.processed_cache_path) as f:
                return set(json.load(f))
        return set()

    def _save_processed(self, processed: set[str]):
        with open(self.processed_cache_path, "w") as f:
            json.dump(sorted(processed), f)

    def get_uuids(self, max_pages: int = 20) -> list[str]:
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

    def fetch_resource(self, uuid: str) -> dict | None:
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

    def download_image(self, img_path: str, save_path: Path) -> bool:
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

    def scrape(self, max_monuments: int = 800):
        print("\n" + "=" * 65)
        print("DANAM HERITAGE MONUMENT SCRAPER v3  (multi-image)")
        print(f"  Max exterior per monument : {self.max_ext}")
        print(f"  Max objects  per monument : {self.max_obj}")
        print(f"  Target monuments          : {max_monuments}")
        print("=" * 65)

        uuids     = self.get_uuids()
        processed = self._load_processed()
        existing_files = self._load_manifest_filenames()

        pending = [u for u in uuids if u not in processed]
        print(f"  UUIDs to check    : {len(pending)} (of {len(uuids)} total)")
        print(f"  Already processed : {len(processed)}")
        print(f"  Existing files    : {len(existing_files)}")

        monuments_found    = 0
        images_downloaded  = 0
        images_reused      = 0
        no_images          = 0

        try:
            for idx, uuid in enumerate(pending, 1):
                if monuments_found >= max_monuments:
                    print(f"\n  Reached target of {max_monuments} monuments.")
                    break

                if idx % 50 == 0:
                    print(f"\n  --- checked {idx}/{len(pending)}, "
                          f"{monuments_found} monuments, {images_downloaded} new imgs ---")
                    self._save_processed(processed)

                time.sleep(random.uniform(0.3, 0.7))

                resource = self.fetch_resource(uuid)
                if not resource:
                    processed.add(uuid)
                    continue

                if resource.get("graph_id") != MONUMENT_GRAPH_ID:
                    processed.add(uuid)
                    continue

                name         = _extract_monument_name(resource.get("displayname", ""))
                description  = _extract_description(resource)
                monument_id  = resource.get("resourceinstanceid", uuid)
                typology     = _extract_typology(resource)
                architecture = _extract_architecture(resource)
                lat, lon     = _extract_geo(resource)

                exteriors = _extract_top_exteriors(resource, self.max_ext)
                objects   = _extract_top_objects(resource, self.max_obj)

                if not exteriors and not objects:
                    no_images += 1
                    processed.add(uuid)
                    continue

                monuments_found += 1
                safe_name    = _safe_dirname(name)
                monument_dir = self.images_dir / f"{safe_name}_{monument_id[:8]}"
                monument_dir.mkdir(parents=True, exist_ok=True)

                print(f"\n  [{monuments_found}] {name[:55]}")
                print(f"       ext={len(exteriors)}  obj={len(objects)}  "
                      f"type={typology['monument_type'][:30]}  "
                      f"roof={architecture['roof_type'][:15]}")

                base_row = {
                    "monument_id":          monument_id,
                    "monument_name":        name,
                    "monument_description": description,
                    "latitude":             lat,
                    "longitude":            lon,
                    "download_date":        datetime.now().isoformat(),
                    "source_url":           f"{BASE_URL}/resources/{uuid}",
                    **typology,
                    **architecture,
                }

                # ── Exterior images ──────────────────────────────────────
                for i, ext_img in enumerate(exteriors, 1):
                    caption = _clean_caption(ext_img["caption"])
                    suffix  = Path(ext_img["path"]).suffix.lower()
                    if suffix not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                        suffix = ".jpg"
                    # e.g. Jogesvara_exterior_1.jpg, _2.jpg, _3.jpg
                    filename  = f"{safe_name}_exterior_{i}{suffix}"
                    save_path = monument_dir / filename

                    if filename in existing_files:
                        images_reused += 1
                        print(f"    ext[{i}] reused: {caption[:60]}")
                        continue

                    time.sleep(random.uniform(0.3, 0.8))
                    ok = save_path.exists() or self.download_image(ext_img["path"], save_path)
                    if ok:
                        self._append_manifest({
                            **base_row,
                            "filename":        filename,
                            "image_caption":   caption,
                            "image_type":      "exterior",
                            "object_id":       "",
                            "object_type":     "",
                            "object_material": "",
                            "object_position": "",
                        })
                        existing_files.add(filename)
                        images_downloaded += 1
                        print(f"    ext[{i}] NEW:   {caption[:65]}")

                # ── Object images ────────────────────────────────────────
                for i, obj in enumerate(objects, 1):
                    caption  = _clean_caption(obj["caption"])
                    suffix   = Path(obj["path"]).suffix.lower()
                    if suffix not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                        suffix = ".jpg"
                    obj_tag  = obj["object_type"][:18].replace(" ", "_").replace("/", "-")
                    filename = f"{safe_name}_obj_{obj_tag}_{i}{suffix}"
                    save_path = monument_dir / filename

                    if filename in existing_files:
                        images_reused += 1
                        print(f"    obj[{i}] reused [{obj['object_type'][:18]}]: {caption[:50]}")
                        continue

                    time.sleep(random.uniform(0.3, 0.8))
                    ok = save_path.exists() or self.download_image(obj["path"], save_path)
                    if ok:
                        self._append_manifest({
                            **base_row,
                            "filename":        filename,
                            "image_caption":   caption,
                            "image_type":      "object",
                            "object_id":       obj["object_id"],
                            "object_type":     obj["object_type"],
                            "object_material": obj["material"],
                            "object_position": obj["position"],
                        })
                        existing_files.add(filename)
                        images_downloaded += 1
                        print(f"    obj[{i}] NEW  [{obj['object_type'][:18]}]: {caption[:50]}")

                processed.add(uuid)

        except KeyboardInterrupt:
            print("\n\nInterrupted — saving progress...")

        self._save_processed(processed)

        print("\n" + "=" * 65)
        print("DANAM SCRAPING COMPLETE")
        print(f"  Monuments found     : {monuments_found}")
        print(f"  New images saved    : {images_downloaded}")
        print(f"  Images reused       : {images_reused}")
        print(f"  Monuments w/o imgs  : {no_images}")
        print(f"  Manifest            : {self.manifest_path}")
        print("=" * 65)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Scrape DANAM v3 — multi-image per monument"
    )
    parser.add_argument("--max-monuments",    type=int, default=800)
    parser.add_argument("--max-pages",        type=int, default=20,
                        help="UUID listing pages (default 20)")
    parser.add_argument("--max-ext",          type=int, default=3,
                        help="Max exterior images per monument (default 3)")
    parser.add_argument("--max-obj",          type=int, default=3,
                        help="Max object images per monument (default 3)")
    parser.add_argument("--reset-processed",  action="store_true",
                        help="Clear processed-UUIDs cache to re-scan all monuments")
    args = parser.parse_args()

    scraper = DANAMScraper(
        output_dir="data/raw/danam",
        max_ext=args.max_ext,
        max_obj=args.max_obj,
    )

    if args.reset_processed:
        cache = scraper.processed_cache_path
        if cache.exists():
            cache.unlink()
            print(f"  Cleared processed cache: {cache}")

    scraper.scrape(max_monuments=args.max_monuments)


if __name__ == "__main__":
    main()
