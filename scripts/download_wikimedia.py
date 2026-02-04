
import requests
import os
import csv
from pathlib import Path
from datetime import datetime
from time import sleep
from PIL import Image
from io import BytesIO
import random


class WikimediaImageScraper:
    """Scraper for downloading images from Wikimedia Commons by category."""
    
    def __init__(self, output_dir="data/raw/wikimedia"):
        self.output_dir = Path(output_dir)
        self.images_dir = self.output_dir / "images"
        self.manifest_path = self.output_dir / "manifest.csv"
        self.base_url = "https://commons.wikimedia.org/w/api.php"
        
        # Create a session to maintain cookies and connection pooling
        self.session = requests.Session()
        
        # Browser-like headers required by Wikimedia
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://commons.wikimedia.org/',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
        }
        
        # API-specific headers (simpler for API calls)
        self.api_headers = {
            'User-Agent': 'HeritageLensBot/1.0 (Cultural Heritage Research Project; contact via GitHub)',
        }
        
        # Create directories
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize manifest
        self._init_manifest()
    
    def _init_manifest(self):
        """Initialize CSV manifest if it doesn't exist."""
        if not self.manifest_path.exists():
            with open(self.manifest_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'filename', 'category', 'wikimedia_url', 'page_title',
                    'license', 'author', 'download_date', 'file_size',
                    'width', 'height'
                ])
    
    def get_category_images(self, category_name, limit=500):
        """
        Get list of images from a Wikimedia Commons category.
        
        Args:
            category_name: Category name (e.g., "Buddhist_temples_in_Nepal")
            limit: Maximum number of images to retrieve
        
        Returns:
            List of image titles
        """
        images = []
        cmcontinue = None
        
        print(f"\n📂 Fetching images from Category:{category_name}")
        
        while len(images) < limit:
            params = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": f"Category:{category_name}",
                "cmtype": "file",
                "cmlimit": min(500, limit - len(images)),
                "format": "json"
            }
            
            if cmcontinue:
                params["cmcontinue"] = cmcontinue
            
            try:
                response = self.session.get(self.base_url, params=params, headers=self.api_headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                if "query" in data and "categorymembers" in data["query"]:
                    batch = data["query"]["categorymembers"]
                    images.extend(batch)
                    print(f"   Retrieved {len(images)} images so far...")
                
                # Check for continuation
                if "continue" not in data:
                    break
                cmcontinue = data["continue"]["cmcontinue"]
                
                sleep(random.uniform(0.5, 1.0))  # Be respectful with rate limiting
                
            except Exception as e:
                print(f"   ⚠️  Error fetching category: {e}")
                break
        
        print(f"   ✅ Found {len(images)} total images")
        return images
    
    def get_image_info(self, image_title):
        """
        Get detailed information about an image.
        
        Args:
            image_title: Full image title (e.g., "File:Temple.jpg")
        
        Returns:
            Dictionary with image info (url, metadata, etc.)
        """
        params = {
            "action": "query",
            "titles": image_title,
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "format": "json"
        }
        
        try:
            response = self.session.get(self.base_url, params=params, headers=self.api_headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            pages = data["query"]["pages"]
            page_id = list(pages.keys())[0]
            
            if "imageinfo" in pages[page_id]:
                info = pages[page_id]["imageinfo"][0]
                return {
                    "url": info.get("url"),
                    "width": info.get("width"),
                    "height": info.get("height"),
                    "size": info.get("size"),
                    "mime": info.get("mime"),
                    "metadata": info.get("extmetadata", {})
                }
        except Exception as e:
            print(f"   ⚠️  Error getting image info: {e}")
        
        return None
    
    def download_image(self, url, save_path, max_retries=3):
        """
        Download an image from URL with retry logic.
        
        Args:
            url: Image URL
            save_path: Path to save the image
            max_retries: Maximum number of retry attempts
        
        Returns:
            True if successful, False otherwise
        """
        for attempt in range(max_retries):
            try:
                # Add random delay between retries
                if attempt > 0:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    sleep(wait_time)
                    print(f"   🔄 Retry {attempt + 1}/{max_retries}...")
                
                # Use session with browser-like headers
                response = self.session.get(
                    url, 
                    stream=True, 
                    headers=self.headers, 
                    timeout=30,
                    allow_redirects=True
                )
                response.raise_for_status()
                
                # Save image
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                return True
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 403:
                    if attempt < max_retries - 1:
                        print(f"   ⚠️  403 Forbidden (attempt {attempt + 1}/{max_retries})")
                        continue
                    else:
                        print(f"   ❌ 403 Forbidden - Skipping after {max_retries} attempts")
                        return False
                else:
                    print(f"   ⚠️  HTTP Error {e.response.status_code}: {e}")
                    return False
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    print(f"   ⚠️  Timeout (attempt {attempt + 1}/{max_retries})")
                    continue
                else:
                    print(f"   ❌ Timeout - Skipping after {max_retries} attempts")
                    return False
            except Exception as e:
                print(f"   ⚠️  Download failed: {e}")
                return False
        
        return False
    
    def add_to_manifest(self, image_data):
        """Add image metadata to manifest CSV."""
        with open(self.manifest_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                image_data.get('filename'),
                image_data.get('category'),
                image_data.get('wikimedia_url'),
                image_data.get('page_title'),
                image_data.get('license', 'Unknown'),
                image_data.get('author', 'Unknown'),
                image_data.get('download_date'),
                image_data.get('file_size'),
                image_data.get('width'),
                image_data.get('height')
            ])
    
    def scrape_category(self, category_name, limit=100):
        """
        Scrape all images from a category.
        
        Args:
            category_name: Wikimedia Commons category name
            limit: Maximum number of images to download
        """
        # Create category directory
        category_dir = self.images_dir / f"Category:{category_name}"
        category_dir.mkdir(exist_ok=True)
        
        # Get list of images
        images = self.get_category_images(category_name, limit)
        
        print(f"\n⬇️  Downloading {len(images)} images to {category_dir}")
        downloaded = 0
        
        for idx, image in enumerate(images[:limit], 1):
            image_title = image['title']
            
            # Get image info
            info = self.get_image_info(image_title)
            if not info or not info.get('url'):
                continue
            
            # Generate filename
            filename = image_title.replace('File:', '').replace(' ', '_')
            save_path = category_dir / filename
            
            # Skip if already exists
            if save_path.exists():
                print(f"   [{idx}/{len(images)}] ⏭️  Skipped (exists): {filename}")
                continue
            
            # Download image
            print(f"   [{idx}/{len(images)}] 📥 Downloading: {filename}")
            
            # Add small random delay to avoid rate limiting
            sleep(random.uniform(0.5, 1.5))
            
            if self.download_image(info['url'], save_path):
                # Extract metadata
                metadata = info.get('metadata', {})
                license_info = metadata.get('LicenseShortName', {}).get('value', 'Unknown')
                author = metadata.get('Artist', {}).get('value', 'Unknown')
                
                # Add to manifest
                self.add_to_manifest({
                    'filename': filename,
                    'category': category_name,
                    'wikimedia_url': info['url'],
                    'page_title': image_title,
                    'license': license_info,
                    'author': author,
                    'download_date': datetime.now().isoformat(),
                    'file_size': info.get('size'),
                    'width': info.get('width'),
                    'height': info.get('height')
                })
                
                downloaded += 1
        
        print(f"\n✅ Downloaded {downloaded} images from {category_name}")
    
    def scrape_nepal_cultural_images(self):
        """Scrape all Nepal cultural image categories."""
        categories = {
            "Temple Architecture": [
                "Buddhist_temples_in_Nepal",
                "Hindu_temples_in_Nepal",
                "Pashupatinath_Temple",
                "Swayambhunath",
                "Boudhanath"
            ],
            "Thangka Paintings": [
                "Thangka",
                "Tibetan_Buddhist_art"
            ],
            "Traditional Ornaments": [
                "Jewelry_of_Nepal",
                "Traditional_clothing_of_Nepal"
            ]
        }
        
        print("\n" + "="*60)
        print("🏛️  NEPAL CULTURAL HERITAGE IMAGE SCRAPER")
        print("="*60)
        
        for theme, cats in categories.items():
            print(f"\n\n🎨 Theme: {theme}")
            print("-" * 60)
            for category in cats:
                try:
                    self.scrape_category(category, limit=100)
                except Exception as e:
                    print(f"❌ Error scraping {category}: {e}")
                    continue
        
        print("\n" + "="*60)
        print("✅ SCRAPING COMPLETE!")
        print(f"📊 Manifest saved to: {self.manifest_path}")
        print("="*60)


def main():
    """Main execution function."""
    # Initialize scraper
    scraper = WikimediaImageScraper(output_dir="data/raw/wikimedia")
    
    # Scrape all categories
    scraper.scrape_nepal_cultural_images()


if __name__ == "__main__":
    main()
