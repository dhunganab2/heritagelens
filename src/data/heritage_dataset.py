"""
PyTorch Dataset for Heritage Lens: loads images and captions from metadata.json.

Supports images from multiple sources (Wikimedia, DANAM) with different
directory layouts. Pass multiple image directories to cover both.
"""

import json
import unicodedata
from pathlib import Path

import torch
from torch.utils.data import Dataset
from PIL import Image


def _find_image_path(
    images_dirs: list[Path],
    image_id: str,
    category: str | None = None,
) -> Path | None:
    """Resolve image path across multiple image directories.

    Searches Category:* subdirs (Wikimedia) and all other subdirs (DANAM).
    """
    image_id_nfc = unicodedata.normalize("NFC", image_id)
    for images_dir in images_dirs:
        if not images_dir.exists():
            continue
        if category:
            for candidate in (
                images_dir / f"Category:{category}" / image_id_nfc,
                images_dir / category / image_id_nfc,
            ):
                if candidate.exists():
                    return candidate
        for subdir in images_dir.iterdir():
            if subdir.is_dir():
                path = subdir / image_id_nfc
                if path.exists():
                    return path
    return None


def default_transform():
    """Default transform: resize to 224x224 and normalize for ImageNet-style models."""
    from torchvision import transforms

    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        ),
    ])


class HeritageDataset(Dataset):
    """
    Dataset that loads images and captions from metadata.json.
    Returns (image_tensor, caption_string). Always uses Cap 1 (Gemini caption).
    """

    def __init__(
        self,
        json_path: str | Path,
        images_dir: str | Path | list[str | Path],
        transform=None,
    ):
        json_path = Path(json_path)
        if isinstance(images_dir, (str, Path)):
            self.images_dirs = [Path(images_dir)]
        else:
            self.images_dirs = [Path(d) for d in images_dir]
        with open(json_path, "r", encoding="utf-8") as f:
            self.metadata = json.load(f)
        self.transform = transform if transform is not None else default_transform()
        self.valid_entries = []
        for i, entry in enumerate(self.metadata):
            image_id = entry["image_id"]
            category = entry.get("category")
            path = _find_image_path(self.images_dirs, image_id, category)
            if path is not None:
                self.valid_entries.append((i, path))

    def __len__(self) -> int:
        return len(self.valid_entries)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, str]:
        meta_idx, image_path = self.valid_entries[idx]
        entry = self.metadata[meta_idx]
        captions = entry["captions"]
        caption = captions[0] if captions else ""

        image = Image.open(image_path).convert("RGB")
        if self.transform:
            image = self.transform(image)
        return image, caption
