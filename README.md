# HeritageLens

**Automatic English caption generation for images of Nepali heritage monuments.**

Built as a Senior Project at Northern Kentucky University. The model takes a photo of a Nepali temple, stupa, monastery, or historic structure and generates a descriptive English caption.

---

## Architecture

```
Image → ResNet-50 (frozen) → spatial features [B, 49, 2048]
                                    ↓ mean pool + linear projection
                            visual context [B, 768]
                                    ↓ added to word embeddings
                            GPT-2 decoder → caption tokens
```

| Component | Details |
|---|---|
| Vision Encoder | ResNet-50 pretrained on ImageNet, all layers frozen |
| Bridge | Linear layer 2048 → 768 (visual context injected into GPT-2 embeddings) |
| Language Decoder | GPT-2 (117M params, fine-tuned) |
| Training | Mixed-precision (FP16), AdamW, 20 epochs on Colab T4 GPU |

---

## Dataset

Two sources scraped and merged:

| Source | Images | Caption type |
|---|---|---|
| **Wikimedia Commons** | 1,128 | Human-written MediaWiki `ImageDescription` (72%) + template fallback |
| **DANAM** (Digital Archive of Nepalese Arts and Monuments) | 663 | Scholar-written per-image captions + monument descriptions |
| **Total** | **1,791** | 3 captions per image |

Categories covered: Buddhist Temples, Hindu Temples, Stupas (Swayambhunath, Boudhanath), Durbar Squares (Kathmandu, Patan, Bhaktapur), Pashupatinath, Buddhist Monasteries (Bāhāḥ), Water Fountains (Hiti), Shrines, Thangka Paintings, Traditional Clothing.

---

## Project Structure

```
heritagelens/
├── data/
│   ├── raw/
│   │   ├── wikimedia/
│   │   │   ├── images/           ← Category:*/  image subdirs
│   │   │   └── manifest.csv      ← per-image metadata
│   │   └── danam/
│   │       ├── images/           ← <MonumentName>_<id8>/  subdirs
│   │       └── manifest.csv
│   └── processed/
│       ├── metadata.json         ← Wikimedia training JSON
│       ├── metadata_danam.json   ← DANAM training JSON
│       └── metadata_merged.json  ← combined (used for training)
│
├── notebooks/
│   └── Heritage-2.ipynb          ← main Colab training notebook
│
├── scripts/
│   ├── download_wikimedia.py     ← scrape Wikimedia Commons
│   ├── download_danam.py         ← scrape DANAM API
│   ├── convert_to_training_json.py
│   ├── convert_danam_to_json.py
│   └── merge_datasets.py
│
├── src/
│   └── data/
│       └── heritage_dataset.py   ← PyTorch Dataset class
│
├── outputs/
│   ├── checkpoints/              ← saved .pt model weights
│   └── figures/                  ← training curves, sample captions
│
└── requirements.txt
```

---

## Quickstart (Local)

```bash
git clone https://github.com/<your-username>/heritagelens.git
cd heritagelens
pip install -r requirements.txt
```

### Re-scrape data (optional — data already in `data/`)

```bash
# Wikimedia Commons (1,128 images, ~312 MB)
python scripts/download_wikimedia.py

# DANAM monuments (663 images, ~786 MB)
python scripts/download_danam.py --max-monuments 250

# Rebuild training JSONs
python scripts/convert_to_training_json.py
python scripts/convert_danam_to_json.py
python scripts/merge_datasets.py
```

---

## Training on Google Colab (T4 GPU)

1. Zip the project:
   ```bash
   zip -r heritagelens.zip data/ src/ scripts/ notebooks/ requirements.txt -x "*.DS_Store"
   ```
2. Upload `heritagelens.zip` to Google Drive.
3. Open `notebooks/Heritage-2.ipynb` in Colab (Runtime → Change runtime type → **T4 GPU**).
4. Run all cells in order:
   - **Cell 0** — mount Drive, unzip project
   - **Cell 1** — install deps, set device, init tokenizer
   - **Cell 2** — load dataset, build DataLoaders, instantiate model
   - **Cell 3** — model architecture (HeritageEncoder + HeritageAttention + HeritageLens)
   - **Cell 4** — training loop (20 epochs, saves `outputs/checkpoints/best_model.pt`)
   - **Cell 5** — generate captions on sample images

Expected training time: **~60–120 min** on T4.

---

## Inference

```python
from src.data.heritage_dataset import HeritageDataset
# (after training)
caption = generate_caption("path/to/temple.jpg", model, tokenizer)
print(caption)
# e.g. "A multi-tiered pagoda temple with traditional Nepali architecture"
```

---

## Data Sources & Licenses

- **Wikimedia Commons** — images under Creative Commons licenses (CC-BY, CC-BY-SA). See `data/raw/wikimedia/manifest.csv` for per-image license info.
- **DANAM** — Digital Archive of Nepalese Arts and Monuments, University of Heidelberg. Images accessed via public REST API. Per-image reuse restrictions respected (images marked "no reuse" are excluded).
