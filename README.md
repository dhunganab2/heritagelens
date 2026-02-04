# Heritage Lens

Cultural image dataset and analysis project for Nepalese heritage.

## Project Structure

```
heritagelens/                  ← PROJECT ROOT (git repo)
│
├── data/
│   ├── raw/
│   │   └── wikimedia/
│   │       ├── images/         ← DOWNLOADED IMAGES GO HERE
│   │       │   ├── Category:Pashupatinath_Temple/
│   │       │   ├── Category:Swayambhunath/
│   │       │   ├── Category:Buddhist_temples_in_Nepal/
│   │       │   ├── Category:Thangka/
│   │       │   └── ...
│   │       │
│   │       └── manifest.csv    ← METADATA FOR ALL IMAGES
│   │
│   └── processed/              ← CLEANED / RESIZED / SPLIT LATER
│       ├── train/
│       ├── val/
│       └── test/
│
├── scripts/
│   └── download_wikimedia.py   ← IMAGE SCRAPING SCRIPT
│
├── src/                        ← MODELS, DATASETS, TRAINING CODE
│   ├── data/
│   ├── models/
│   ├── train/
│   └── eval/
│
├── outputs/
│   ├── baselines/              ← Baseline model results
│   ├── checkpoints/            ← Saved model checkpoints
│   └── figures/                ← Generated visualizations
│
├── requirements.txt            ← Python dependencies
└── README.md                  ← This file
```

## Getting Started

### 1. Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Download Images

Run the Wikimedia scraper to download cultural images:

```bash
python scripts/download_wikimedia.py
```

This will:
- Download images from Nepal-related Wikimedia Commons categories
- Organize them by category in `data/raw/wikimedia/images/`
- Save metadata to `data/raw/wikimedia/manifest.csv`

**Categories scraped:**
- **Temple Architecture**: Buddhist temples, Hindu temples, Pashupatinath, Swayambhunath, Boudhanath
- **Thangka Paintings**: Traditional Buddhist paintings
- **Traditional Ornaments**: Jewelry and traditional clothing

### 3. Process Data

After downloading, process and split the dataset:

```bash
# Coming soon: data processing scripts
python src/data/preprocess.py
```

## Categories

- Temple Architecture
- Thangka Paintings
- Traditional Ornaments

## Data Sources

Images collected from Wikipedia using the MediaWiki API.
