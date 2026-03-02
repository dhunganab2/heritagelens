"""
Wikimedia Commons scraper for Nepal heritage images.

Key improvements over v1:
  - Batch image-info API calls (50 titles per request) → 50x fewer API calls
  - HTTP 429 rate-limit handling: sleep 60 s and retry instead of skipping
  - Thumbnail downloads (iiurlwidth=800) → fast, small files suitable for 224×224 training
  - Non-English description filtering (Dutch/German/French archive boilerplate)
  - 12 heritage categories covering temples, stupas, Durbar Squares, Thangka, clothing
"""

import csv
import html
import random
import re
import time
from datetime import datetime
from pathlib import Path

import requests


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# How long to sleep (seconds) after a 429 response before retrying
RATE_LIMIT_SLEEP = 15

# Non-English archive keywords that appear in Wikimedia boilerplate descriptions
_NON_ENGLISH_MARKERS = [
    # Dutch
    "Collectie", "Archief", "Bestanddeelnr", "Beschrijving", "Trefwoorden",
    "Fotograaf", "Auteursrechthebbende", "Inventarisnummer", "Reportage",
    "bekijk toegang",
    # German
    "Beschreibung", "Quelle", "Urheber", "Genehmigung", "Lizenz", "Stoffweste",
    "Nerzbisam", "Verbrämung",
    # French
    "femme rana tharu", "sud ouest", "allant à la pêche",
    # Generic boilerplate
    "Bestand", "Datum :",
]


def _clean_description(raw: str) -> str:
    """Strip HTML and extract English text from a Wikimedia ImageDescription."""
    if not raw:
        return ""
    # Prefer the English <span lang="en"> if present
    en = re.search(r'<span[^>]*\blang=["\']en["\'][^>]*>(.*?)</span>', raw,
                   re.DOTALL | re.IGNORECASE)
    text = en.group(1) if en else raw
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_good_english(text: str, min_len: int = 25) -> bool:
    """Return True only if text is usable English of sufficient length."""
    if not text or len(text) < min_len:
        return False
    if text.startswith(("http://", "https://")):
        return False
    non_ascii = sum(1 for c in text if ord(c) > 127)
    if non_ascii / len(text) > 0.15:
        return False
    for marker in _NON_ENGLISH_MARKERS:
        if marker in text:
            return False
    return True


# ── All Nepal heritage categories to scrape ──────────────────────────────────
#
# Format: (wikimedia_category_name, cultural_label_hint, limit)
#   cultural_label_hint is used only for directory naming; the converter script
#   does the actual label mapping.
#
NEPAL_CATEGORIES = [
    # ── Temples & Stupas ─────────────────────────────────────────────────────
    ("Buddhist_temples_in_Nepal",               "Buddhist Temple",        150),
    ("Hindu_temples_in_Nepal",                  "Hindu Temple",           150),
    ("Pashupatinath",                           "Hindu Temple",           150),
    ("Swayambhunath",                           "Stupa",                  150),
    ("Boudhanath",                              "Stupa",                  150),
    # ── Durbar Squares ───────────────────────────────────────────────────────
    ("Durbar_Square_temples_(Kathmandu)",        "Newari Pagoda",          150),
    ("Patan_Durbar_Square",                     "Newari Pagoda",          150),
    ("Bhaktapur_Durbar_Square",                 "Newari Pagoda",          150),
    ("Changu_Narayan_Temple",                   "Hindu Temple",           100),
    # ── Buddhist Art & Paintings ─────────────────────────────────────────────
    ("Thangka",                                 "Thangka Painting",       150),
    ("Tibetan_Buddhist_art",                    "Tibetan Art",            100),
    # ── People & Clothing ────────────────────────────────────────────────────
    ("Traditional_clothing_of_Nepal",           "Traditional Clothing",   150),
]


class WikimediaImageScraper:
    """Scrape images + captions from Wikimedia Commons for Nepal heritage training."""

    def __init__(self, output_dir: str = "data/raw/wikimedia"):
        self.output_dir = Path(output_dir)
        self.images_dir = self.output_dir / "images"
        self.manifest_path = self.output_dir / "manifest.csv"
        self.base_url = "https://commons.wikimedia.org/w/api.php"

        self.session = requests.Session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Referer": "https://commons.wikimedia.org/",
        }
        self.api_headers = {
            "User-Agent": "HeritageLensBot/1.0 (NKU Senior Project; Nepal Heritage Captioning)",
        }

        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._init_manifest()

    # ── Manifest ──────────────────────────────────────────────────────────────

    def _init_manifest(self):
        if not self.manifest_path.exists():
            with open(self.manifest_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    "filename", "category", "wikimedia_url", "page_title",
                    "license", "author", "description",
                    "download_date", "file_size", "width", "height",
                ])

    def _append_manifest(self, row: dict):
        with open(self.manifest_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                row.get("filename"),
                row.get("category"),
                row.get("wikimedia_url"),
                row.get("page_title"),
                row.get("license", "Unknown"),
                row.get("author", "Unknown"),
                row.get("description", ""),
                row.get("download_date"),
                row.get("file_size"),
                row.get("width"),
                row.get("height"),
            ])

    # ── Category member listing ───────────────────────────────────────────────

    def get_category_files(self, category: str, limit: int) -> list[str]:
        """Return up to `limit` file titles from a Wikimedia category."""
        titles: list[str] = []
        cmcontinue = None

        while len(titles) < limit:
            params = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": f"Category:{category}",
                "cmtype": "file",
                "cmlimit": min(500, limit - len(titles)),
                "format": "json",
            }
            if cmcontinue:
                params["cmcontinue"] = cmcontinue

            try:
                r = self.session.get(self.base_url, params=params,
                                     headers=self.api_headers, timeout=15)
                r.raise_for_status()
                data = r.json()
                batch = [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
                titles.extend(batch)
                if "continue" not in data:
                    break
                cmcontinue = data["continue"]["cmcontinue"]
                time.sleep(0.5)
            except Exception as e:
                print(f"   [list error] {e}")
                break

        # Filter to supported raster formats only
        titles = [t for t in titles if Path(t).suffix.lower() in SUPPORTED_EXTENSIONS]
        print(f"   {len(titles)} supported-format files found in Category:{category}")
        return titles[:limit]

    # ── Batch image-info API ──────────────────────────────────────────────────

    def get_image_info_batch(self, titles: list[str]) -> dict[str, dict]:
        """Fetch thumbnail URL + metadata for up to 50 titles in one API call.

        Returns a dict keyed by title (e.g. "File:Foo.jpg") with info dicts.
        """
        results: dict[str, dict] = {}
        params = {
            "action": "query",
            "titles": "|".join(titles),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata|thumburl",
            "iiurlwidth": 800,
            "iiextmetadatalanguage": "en",
            "format": "json",
        }

        for attempt in range(4):
            try:
                r = self.session.get(self.base_url, params=params,
                                     headers=self.api_headers, timeout=20)
                if r.status_code == 429:
                    wait = RATE_LIMIT_SLEEP * (attempt + 1)
                    print(f"   [API 429] sleeping {wait}s ...")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                data = r.json()
                for page in data.get("query", {}).get("pages", {}).values():
                    title = page.get("title", "")
                    if "imageinfo" not in page:
                        continue
                    info = page["imageinfo"][0]
                    meta = info.get("extmetadata", {})

                    raw_desc = meta.get("ImageDescription", {}).get("value", "")
                    desc = _clean_description(raw_desc)
                    if not _is_good_english(desc):
                        desc = ""

                    results[title] = {
                        "url": info.get("thumburl") or info.get("url"),
                        "original_url": info.get("url"),
                        "width": info.get("width"),
                        "height": info.get("height"),
                        "size": info.get("size"),
                        "mime": info.get("mime", ""),
                        "license": meta.get("LicenseShortName", {}).get("value", "Unknown"),
                        "author": _clean_description(
                            meta.get("Artist", {}).get("value", "")
                        ),
                        "description": desc,
                    }
                return results
            except Exception as e:
                print(f"   [batch API error attempt {attempt+1}] {e}")
                time.sleep(5)

        return results

    # ── Image download ────────────────────────────────────────────────────────

    def download_image(self, url: str, save_path: Path, max_retries: int = 4) -> bool:
        """Download one image. On 429, sleeps and retries (does NOT skip)."""
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait = min(2 ** attempt + random.uniform(0, 1), 30)
                    time.sleep(wait)

                r = self.session.get(url, stream=True, headers=self.headers,
                                     timeout=60, allow_redirects=True)

                if r.status_code == 429:
                    wait = RATE_LIMIT_SLEEP * (attempt + 1)
                    print(f"      [429] sleeping {wait}s ...")
                    time.sleep(wait)
                    continue

                r.raise_for_status()

                with open(save_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        if chunk:
                            f.write(chunk)
                return True

            except requests.exceptions.HTTPError as e:
                if e.response.status_code in (403, 404):
                    return False
                print(f"      [HTTP {e.response.status_code}] {e}")
                time.sleep(5)
            except requests.exceptions.Timeout:
                print(f"      [timeout attempt {attempt+1}]")
            except Exception as e:
                print(f"      [error] {e}")
                return False

        print(f"      [FAILED after {max_retries} attempts] {save_path.name}")
        return False

    # ── Category scraper ──────────────────────────────────────────────────────

    def scrape_category(self, category: str, limit: int):
        """Scrape one Wikimedia Commons category."""
        category_dir = self.images_dir / f"Category:{category}"
        category_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"Category: {category}  (limit={limit})")

        # Count already-downloaded to support resume
        existing = {p.name for p in category_dir.iterdir() if p.is_file()}
        print(f"  Already downloaded: {len(existing)}")

        all_titles = self.get_category_files(category, limit)
        if not all_titles:
            print("  No files found.")
            return

        # Filter titles whose files we already have
        pending = [t for t in all_titles
                   if t.replace("File:", "").replace(" ", "_") not in existing]
        print(f"  Pending download: {len(pending)}")

        # Batch-fetch image info (50 at a time)
        info_map: dict[str, dict] = {}
        BATCH = 50
        for i in range(0, len(pending), BATCH):
            chunk = pending[i:i + BATCH]
            print(f"  Fetching info batch {i//BATCH + 1}/{(len(pending)+BATCH-1)//BATCH} ...")
            info_map.update(self.get_image_info_batch(chunk))
            time.sleep(1.0)  # polite pause between info batches

        downloaded = 0
        for idx, title in enumerate(pending, 1):
            info = info_map.get(title)
            if not info or not info.get("url"):
                print(f"  [{idx}/{len(pending)}] No info — skip: {title[:60]}")
                continue

            filename = title.replace("File:", "").replace(" ", "_")
            save_path = category_dir / filename

            if save_path.exists():
                print(f"  [{idx}/{len(pending)}] Already exists: {filename[:60]}")
                continue

            desc_preview = f' | "{info["description"][:60]}"' if info["description"] else ""
            print(f"  [{idx}/{len(pending)}] {filename[:55]}{desc_preview}")

            # Polite delay between downloads: 1–2 s
            time.sleep(random.uniform(1.0, 2.0))

            if self.download_image(info["url"], save_path):
                self._append_manifest({
                    "filename": filename,
                    "category": category,
                    "wikimedia_url": info.get("original_url") or info["url"],
                    "page_title": title,
                    "license": info.get("license", "Unknown"),
                    "author": info.get("author", "Unknown"),
                    "description": info.get("description", ""),
                    "download_date": datetime.now().isoformat(),
                    "file_size": info.get("size"),
                    "width": info.get("width"),
                    "height": info.get("height"),
                })
                downloaded += 1

        total_now = len(existing) + downloaded
        print(f"\n  Finished {category}: +{downloaded} new  ({total_now} total in dir)")

    # ── Main entry ────────────────────────────────────────────────────────────

    def scrape_all(self):
        print("\n" + "=" * 60)
        print("NEPAL CULTURAL HERITAGE IMAGE SCRAPER")
        print(f"Target categories: {len(NEPAL_CATEGORIES)}")
        print("=" * 60)

        for category, _, limit in NEPAL_CATEGORIES:
            try:
                self.scrape_category(category, limit)
            except KeyboardInterrupt:
                print("\nInterrupted — partial data saved to manifest.csv")
                break
            except Exception as e:
                print(f"\n[ERROR] Category {category}: {e}")
                continue

        total = sum(
            len(list(d.iterdir()))
            for d in self.images_dir.iterdir()
            if d.is_dir()
        )
        print("\n" + "=" * 60)
        print("SCRAPING COMPLETE")
        print(f"Total images on disk : {total}")
        print(f"Manifest             : {self.manifest_path}")
        print("=" * 60)


def main():
    scraper = WikimediaImageScraper(output_dir="data/raw/wikimedia")
    scraper.scrape_all()


if __name__ == "__main__":
    main()
