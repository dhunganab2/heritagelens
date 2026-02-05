"""
PyTorch Dataset for Heritage Lens: loads images and captions from metadata.json.
"""

import json
import random
from pathlib import Path

import torch
from torch.utils.data import Dataset
from PIL import Image


def _find_image_path(images_dir: Path, image_id: str, category: str | None = None) -> Path | None:
    """Resolve image path. If category given, use it; else search Category:* subdirs."""
    if category:
        path = images_dir / f"Category:{category}" / image_id
        if path.exists():
            return path
    for subdir in images_dir.iterdir():
        if subdir.is_dir() and subdir.name.startswith("Category:"):
            path = subdir / image_id
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
    Returns (image_tensor, caption_string). Caption is randomly chosen from the 3 per image.
    """

    def __init__(
        self,
        json_path: str | Path,
        images_dir: str | Path,
        transform=None,
    ):
        json_path = Path(json_path)
        images_dir = Path(images_dir)
        with open(json_path, "r", encoding="utf-8") as f:
            self.metadata = json.load(f)
        self.images_dir = images_dir
        self.transform = transform if transform is not None else default_transform()
        # Resolve paths once; drop entries with missing images
        self.valid_entries = []
        for i, entry in enumerate(self.metadata):
            image_id = entry["image_id"]
            category = entry.get("category")
            path = _find_image_path(images_dir, image_id, category)
            if path is not None:
                self.valid_entries.append((i, path))
            # else skip this entry

    def __len__(self) -> int:
        return len(self.valid_entries)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, str]:
        meta_idx, image_path = self.valid_entries[idx]
        entry = self.metadata[meta_idx]
        captions = entry["captions"]
        caption = random.choice(captions) if captions else ""

        image = Image.open(image_path).convert("RGB")
        if self.transform:
            image = self.transform(image)
        return image, caption
