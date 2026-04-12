# HeritageLens

Automatic English caption generation for Nepali heritage monuments.

Give it a photo of a temple, stupa, water fountain, or carved artifact — it returns a culturally grounded description covering the architecture, materials, and religious context.

Built as a Senior Project at Northern Kentucky University (Spring 2026).

---

## Results

Evaluated on 182 held-out test images never seen during training.

| Model | BLEU-1 | BLEU-2 | BLEU-3 | BLEU-4 | METEOR | CLIPScore | Cultural Accuracy |
|---|---|---|---|---|---|---|---|
| Zero-shot BLIP (no training) | 0.0018 | 0.0005 | 0.0002 | 0.0002 | 0.0415 | 27.95 | 0.80 / 3 |
| **Fine-tuned BLIP (ours)** | **0.3187** | **0.1590** | **0.0823** | **0.0464** | **0.2558** | **33.15** | **3.00 / 3** |

- BLEU-4 improved by **23,100%** over zero-shot
- METEOR improved by **516%** over zero-shot
- CLIPScore improved by **+18.6%** (27.95 → 33.15)
- Cultural accuracy: **3.00 / 3** (perfect score on all 10 judged images), matching the Gemini Vision oracle

> BLEU scores are low in absolute terms because the reference captions average 62.9 words while the model outputs 15–25 words. CLIPScore and cultural accuracy are more meaningful metrics for this task.

---

## How It Works

```
Photo (any resolution)
      │
      ▼
ViT-B/16 vision encoder   ← frozen, extracts visual features at 384×384
      │
      ▼
BERT-based text decoder   ← fine-tuned on 1,829 heritage images
      │
      ▼
English caption
```

| Setting | Value |
|---|---|
| Base model | `Salesforce/blip-image-captioning-base` |
| Vision encoder | ViT-B/16 — frozen (86.1M params) |
| Text decoder | BERT-based — fine-tuned (161.4M params) |
| Optimizer | AdamW, lr=2e-5, weight_decay=0.01 |
| Scheduler | Linear warmup 2 epochs → CosineAnnealing |
| Batch size | 32, AMP FP16 |
| Max epochs | 20 (early stopping, patience=6) |
| GPU | Tesla T4, Google Colab |

---

## Dataset

Images and raw captions were scraped from two public archives:

- **Wikimedia Commons** (~1,128 images) — CC-BY / CC-BY-SA licensed, scraped via the Wikimedia API
- **DANAM** — Digital Archive of Nepalese Arts and Monuments, Universität Heidelberg (~663 images)

The raw captions from both sources were noisy (license text, catalogue IDs, stub descriptions). They were passed through Gemini Vision to remove the noise and restructure them into consistent descriptions. Every caption was then manually validated for architectural and cultural accuracy before use as a training target.

| Stat | Value |
|---|---|
| Total images | 2,285 |
| Unique monuments | 811 |
| Exterior images | 981 |
| Object / artifact images | 1,304 |
| Avg caption length | 62.9 words |
| Train / Val / Test | 1,829 / 274 / 182 |

---

## Project Structure

```
heritagelens/
├── data/
│   ├── raw/danam/
│   │   ├── images/               ← scraped images
│   │   ├── manifest.csv          ← raw scrape metadata
│   │   └── manifest_filtered.csv ← filtered (2 ext + 3 obj per monument)
│   └── processed/
│       ├── metadata_gemini.json  ← structured captions
│       └── metadata_merged.json  ← training file
│
├── notebooks/
│   └── Heritage-2.ipynb          ← Colab notebook (train + evaluate)
│
├── scripts/
│   ├── download_danam.py         ← scrape DANAM API
│   ├── filter_manifest.py        ← cap images per monument
│   ├── generate_captions_gemini.py ← caption structuring via Gemini
│   ├── build_zip.py              ← pack dataset for Colab
│   ├── batch_preview.py          ← caption review + stats
│   └── show_captions.py          ← HTML gallery
│
└── heritagelens-data.zip         ← dataset archive (upload to Google Drive)
```

---

## Reproducing the Pipeline

### 1. Scrape images and captions

```bash
python3 scripts/download_danam.py --max-monuments 600 --max-ext 2 --max-obj 3
python3 scripts/filter_manifest.py --max-ext 2 --max-obj 3
```

### 2. Structure captions with Gemini

```bash
export GEMINI_API_KEY="your_key_here"   # never commit this
python3 scripts/generate_captions_gemini.py --dry-run --limit 5   # test first
python3 scripts/generate_captions_gemini.py                        # full run
cp data/processed/metadata_gemini.json data/processed/metadata_merged.json
```

Safe to stop and resume — progress is cached in `data/processed/captions_cache.json`.

### 3. Review captions

```bash
python3 scripts/batch_preview.py --stats
python3 scripts/show_captions.py && open data/processed/gallery.html
```

### 4. Build Colab zip

```bash
python3 scripts/build_zip.py
# → heritagelens-data.zip (~2.5 GB)
```

### 5. Train on Colab

1. Upload `heritagelens-data.zip` to Google Drive → MyDrive
2. Open `notebooks/Heritage-2.ipynb` in Colab
3. Set runtime to **T4 GPU**
4. Run cells in order:

| Cell | What it does |
|---|---|
| 0 | Mount Drive, unzip dataset |
| 1 | Dataset preview |
| 2 | Install libraries |
| 3 | Build dataset and dataloaders |
| 4 | Load BLIP, freeze encoder, set optimizer |
| 5 | Fine-tune (saves best checkpoint to Drive) |
| 6 | Evaluate fine-tuned model on test set |
| 7 | Zero-shot BLIP baseline comparison |
| 8 | Qualitative caption comparison grid |
| 9 | Upload your own image and get a caption |
| 10 | Multi-model evaluation with Gemini-as-judge |

Expected training time: ~90–120 min on T4.

---

## Data Sources

- **Wikimedia Commons** — https://commons.wikimedia.org (CC-BY / CC-BY-SA)
- **DANAM** — https://danam.cats.uni-heidelberg.de (Universität Heidelberg)
- **BLIP** — `Salesforce/blip-image-captioning-base`, Apache 2.0

---

## References

1. Li et al. (2022). BLIP: Bootstrapping Language-Image Pre-training. *ICML 2022.*
2. Dosovitskiy et al. (2021). An Image is Worth 16×16 Words. *ICLR 2021.*
3. Papineni et al. (2002). BLEU: A Method for Automatic Evaluation of MT. *ACL 2002.*
4. Hessel et al. (2021). CLIPScore: A Reference-free Evaluation Metric for Image Captioning. *EMNLP 2021.*
