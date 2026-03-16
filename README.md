# HeritageLens — Nepal

**Domain-specific image captioning for Nepali cultural heritage monuments.**

A fine-tuned vision-language model that takes a photo of a Nepali temple, stupa, monastery, water architecture, or historic object and generates a culturally accurate English caption.

Built as a Senior Project at Northern Kentucky University (Spring 2026).

---

## Results

| Model | BLEU-1 | BLEU-2 | BLEU-3 | BLEU-4 | METEOR | CLIPScore |
|---|---|---|---|---|---|---|
| Zero-shot BLIP (baseline) | — | — | — | — | — | — |
| **Fine-tuned BLIP (ours)** | **0.3288** | **0.1713** | **0.0917** | **0.0526** | **0.2679** | **32.93** |

> Evaluated on 182 held-out test images (8% split, never seen during training).
> References: Cap 1 (Gemini) only, monument names anonymized for fair scoring.
> CLIPScore range ~20–35 — 32.93 indicates strong image↔caption semantic alignment.
> Zero-shot baseline numbers to be added after Cell 7 evaluation.

---

## Architecture

```
Image (PIL)
    │
    ▼
BlipProcessor (resize → 384×384, normalize)
    │
    ▼
Vision Transformer ViT-B/16  ← FROZEN (pre-trained weights preserved)
    │
    ▼
BERT-based Text Decoder      ← FINE-TUNED on Nepali heritage captions
    │
    ▼
Generated English Caption
```

| Component | Details |
|---|---|
| Base model | `Salesforce/blip-image-captioning-base` (pre-trained on 129M pairs) |
| Vision encoder | ViT-B/16 — all layers frozen during fine-tuning |
| Text decoder | BERT-based — fully fine-tuned |
| Optimizer | AdamW (lr = 2e-5, weight_decay = 0.01) |
| Scheduler | Linear warmup (2 epochs) + CosineAnnealingLR |
| Batch size | 32 (AMP float16) |
| Epochs | 16 (early stopping at epoch 16, best checkpoint at epoch 10) |
| Best val loss | 2.0033 |
| GPU | Tesla T4 (Google Colab) |
| Training time | ~1.75 hours |

---

## Dataset

All data sourced exclusively from **DANAM** (Digital Archive of Nepalese Arts and Monuments, University of Heidelberg).

| Stat | Value |
|---|---|
| Total images | 2,285 |
| Unique monuments | 811 |
| Exterior images | ~1,000 |
| Object / detail images | ~1,285 |
| Captions per image | 1 (Cap 1: Gemini Vision — rich, culturally accurate) |
| Caption source | Gemini Vision API (image + DANAM metadata) |
| Monument types covered | Tiered temple, bāhāḥ, phalcā, stupa, śikhara, water architecture, shrine, and more |

**Per image, the model is trained on the Gemini Vision caption (Cap 1) only**, grounded in both the actual photo and DANAM's scholarly metadata:
- **Gemini caption** — Visually-grounded + culturally accurate: `"A two-storey Buddhist tiered temple with a gilt copper roof and elaborately carved wooden struts, viewed from the southern corner of the courtyard. The toraṇa above the gilded doorway depicts Vajrayoginī flanked by attendant deities in traditional Newari metalwork style."`

---

## Project Structure

```
heritagelens/
├── data/
│   ├── raw/
│   │   └── danam/
│   │       ├── images/               ← <MonumentName>_<id8>/ subdirs (2,285+ images)
│   │       ├── manifest.csv          ← raw scraped metadata
│   │       └── manifest_filtered.csv ← filtered (2 ext + 3 obj per monument)
│   └── processed/
│       ├── metadata_gemini.json      ← Gemini Vision captions (2,285 entries)
│       ├── metadata_merged.json      ← training JSON (copy of metadata_gemini)
│       └── captions_cache.json       ← Gemini API cache (gitignored)
│
├── notebooks/
│   └── Heritage-2.ipynb              ← Colab training + evaluation notebook (9 cells)
│
├── scripts/
│   ├── download_danam.py             ← scrape DANAM REST API (v3, multi-image)
│   ├── filter_manifest.py            ← cap images per monument (max ext/obj)
│   ├── generate_captions_gemini.py   ← Gemini Vision caption generation (resumable)
│   ├── build_zip.py                  ← pack metadata + images into Colab zip
│   ├── batch_preview.py              ← CLI caption quality review + statistics
│   ├── show_captions.py              ← generate HTML gallery of images + captions
│   └── legacy/                       ← archived scripts (template-based captions)
│
├── reports/
│   ├── Heritage_Lens_Milestone2.docx ← Milestone 2 written report
│   └── generate_milestone2.py        ← script to regenerate the report
│
├── heritagelens-data.zip             ← dataset archive for Colab (upload to Google Drive)
└── requirements.txt
```

---

## Reproducing the Full Pipeline

### 1. Scrape data from DANAM

```bash
# Fetch all monument UUIDs (uses /search/resources endpoint — 1,947 monuments in DANAM)
# Then scrape images (2 exterior + 3 objects per monument)
python3 scripts/download_danam.py --max-monuments 600 --max-ext 2 --max-obj 3
```

### 2. Filter manifest to controlled subset

```bash
# Cap to 2 exterior + 3 object images per monument (reduces redundancy)
python3 scripts/filter_manifest.py --max-ext 2 --max-obj 3
# → data/raw/danam/manifest_filtered.csv  (2,318 rows, all images on disk)
```

### 3. Generate captions with Gemini Vision  ← key step

```bash
export GEMINI_API_KEY="your_key_here"   # Or set in script — never commit the key

# Dry-run first (no API calls) to verify prompts:
python3 scripts/generate_captions_gemini.py --dry-run --limit 5

# Full run — generates one high-quality caption per image:
# Uses gemini-3.1-flash-lite-preview (8 workers, 2000 RPM default)
python3 scripts/generate_captions_gemini.py

# Safe to Ctrl-C and resume — results cached in data/processed/captions_cache.json
# Activate when complete:
cp data/processed/metadata_gemini.json data/processed/metadata_merged.json
```

### 4. Review caption quality

```bash
python3 scripts/batch_preview.py --metadata data/processed/metadata_gemini.json --stats
python3 scripts/show_captions.py
open data/processed/gallery.html
```

### 5. Build the Colab zip

```bash
python3 scripts/build_zip.py
# → heritagelens-data.zip (~2.5 GB) — upload to Google Drive, then use in Colab
```

### 6. Train on Google Colab

1. Upload `heritagelens-data.zip` to Google Drive → MyDrive
2. Open `notebooks/Heritage-2.ipynb` in Colab
3. Set runtime: **T4 GPU** (Runtime → Change runtime type)
4. Run cells in order:

| Cell | Purpose |
|---|---|
| 0 | Mount Drive, unzip dataset, verify paths |
| 1 | Dataset preview (2,285 images, monument grid) |
| 2 | Install libraries, load `BlipProcessor` |
| 3 | `HeritageDataset`, DataLoaders, augmentation |
| 4 | Load BLIP, freeze ViT encoder, set optimizer + scheduler |
| 5 | Training loop (20 epochs max, early stopping, BLEU every 3 epochs) |
| 6 | Evaluate fine-tuned BLIP: BLEU-1/2/3/4 + METEOR + CLIPScore (held-out test set) |
| 7 | Zero-shot BLIP baseline: same metrics, side-by-side comparison table |
| 8 | Qualitative comparison: 4-image grid GT / fine-tuned / zero-shot |

Expected training time: **~90–120 min** on T4.

---

## Caption Examples

| Image | Ground Truth (Gemini, anonymized) | Fine-tuned BLIP |
|---|---|---|
| Buddhist stupa exterior | "this monument is a three-tiered Buddhist stupa with a gilt copper finial..." | "a nepali heritage monument with a large bell-shaped dome and a decorated spire..." |
| Temple carved detail (object) | "this monument features an elaborately carved wooden toraṇa depicting..." | "a nepali heritage monument with intricate carved wooden decorations..." |

---

## Evaluation (Milestone 3)

All models evaluated on the **same 182 held-out test images** with identical references (Cap 1, monument names anonymized).

| Model | BLEU-4 | METEOR | CLIPScore | Notes |
|---|---|---|---|---|
| Zero-shot BLIP | — | — | — | Unconditional generation, no domain prefix |
| **Fine-tuned BLIP (ours)** | **0.0526** | **0.2679** | **32.93** | Conditional prefix: "a nepali heritage monument" |

**Key finding:** CLIPScore of 32.93 (near top of 20–35 range) indicates strong image↔caption semantic alignment despite low BLEU-4, which is expected when comparing against a single long Gemini reference caption. The model correctly describes architectural features, materials, and religious iconography but generates captions in a narrow stylistic range — a known limitation of small-dataset (2,285 image) fine-tuning.

---

## Security

**Never commit your Gemini API key.** Use `export GEMINI_API_KEY="..."` or a `.env` file (gitignored). The repo excludes `.env`, `*.key`, and `*_api_key*` patterns.

---

## Data Sources & Licenses

- **DANAM** — Digital Archive of Nepalese Arts and Monuments, Kathmandu Valley Preservation Trust / University of Heidelberg. Images accessed via public REST API. Images marked "no reuse" are excluded during scraping.
- **BLIP model** — `Salesforce/blip-image-captioning-base`, Apache 2.0 License.

---

## References

1. Li, J., Li, D., Xiong, C., & Hoi, S. (2022). BLIP: Bootstrapping Language-Image Pre-training. *ICML 2022*.
2. Dosovitskiy, A., et al. (2021). An Image is Worth 16×16 Words. *ICLR 2021*.
3. Papineni, K., et al. (2002). BLEU: A Method for Automatic Evaluation of MT. *ACL 2002*.
