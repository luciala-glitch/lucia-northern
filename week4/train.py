"""Train the pretrained five-heatmap detector on one leakage-safe DenPAR fold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import time
from typing import Any

import numpy as np
from PIL import Image

from week3.image_processing import preprocess
from week4.constants import LANDMARK_NAMES, SEED
from week4.model import build_heatmap_model, decode_heatmaps, to_input_tensor
from week4.training import augment, canonical_crop, gaussian_heatmaps

ROOT = Path(__file__).resolve().parents[1]
DENPAR = ROOT / "week4" / "data" / "denpar_full"
DATASET = ROOT / "week4" / "data" / "denpar_landmarks.json"
SPLIT = ROOT / "week4" / "data" / "denpar_split_5fold.json"


def seed_everything(seed: int) -> Any:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    return torch


def device() -> Any:
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_crops(
    dataset: dict[str, Any], annotation_ids: set[int], condition: str
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Canonical tooth-box crops; each radiograph is decoded and preprocessed once."""
    images = {int(i["id"]): i for i in dataset["images"]}
    chosen = [a for a in dataset["annotations"] if int(a["id"]) in annotation_ids]
    chosen.sort(key=lambda a: (int(a["image_id"]), int(a["tooth_id"])))
    crops: list[Any] = []
    cached: tuple[int, Image.Image] | None = None
    for annotation in chosen:
        image_id = int(annotation["image_id"])
        if cached is None or cached[0] != image_id:
            source = Image.open(DENPAR / images[image_id]["file_name"])
            cached = (image_id, preprocess(source, condition))
        crops.append(
            canonical_crop(
                cached[1],
                tuple(annotation["bbox"]),
                apex_at_bottom=bool(annotation["apex_at_bottom"]),
                mesial_on_left=bool(annotation["mesial_on_left"]),
            )
        )
    return chosen, crops


def train_fold(
    fold_number: int,
    output_path: Path,
    *,
    condition: str = "raw",
    epochs: int = 30,
    batch_size: int = 16,
    seed: int = SEED,
) -> dict[str, Any]:
    torch = seed_everything(seed)
    from torch.utils.data import DataLoader, Dataset

    dataset = json.loads(DATASET.read_text())
    split = json.loads(SPLIT.read_text())
    fold = next(item for item in split["folds"] if int(item["fold"]) == fold_number)
    train_images = set(map(int, fold["train_image_ids"]))
    ids = {int(a["id"]) for a in dataset["annotations"] if int(a["image_id"]) in train_images}
    annotations, crops = load_crops(dataset, ids, condition)
    local_points = [
        {name: crop.to_local(tuple(a["mean"][name])) for name in LANDMARK_NAMES}
        for a, crop in zip(annotations, crops)
    ]

    class Teeth(Dataset):
        def __init__(self) -> None:
            self.epoch = 0

        def __len__(self) -> int:
            return len(crops)

        def __getitem__(self, index: int) -> tuple[Any, Any]:
            rng = random.Random(seed + self.epoch * 100_003 + index)
            # Random CLAHE is an augmentation for Raw models; CLAHE models already see it.
            sample = augment(
                crops[index].image,
                local_points[index],
                rng,
                clahe_probability=0.35 if condition == "raw" else 0.0,
            )
            pixels = np.asarray(sample.image, dtype=np.uint8)
            target = gaussian_heatmaps(sample.points, sample.image.size, sigma=3.0)
            target /= np.maximum(target.sum(axis=(1, 2), keepdims=True), 1e-8)
            return torch.from_numpy(pixels.copy()), torch.from_numpy(target)

    run_device = device()
    model = build_heatmap_model(pretrained=True).to(run_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=1e-4)
    steps = epochs * ((len(crops) + batch_size - 1) // batch_size)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(optimizer, max_lr=5e-4, total_steps=steps)
    data = Teeth()
    loader = DataLoader(
        data,
        batch_size=batch_size,
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
        num_workers=0,
    )
    history = []
    started = time.time()
    model.train()
    for epoch in range(epochs):
        data.epoch = epoch
        total = 0.0
        for pixels, target in loader:
            pixels, target = pixels.to(run_device), target.to(run_device)
            logits = model(to_input_tensor(pixels, torch))
            log_probability = torch.log_softmax(logits.flatten(2), dim=2)
            # Cross-entropy to a normalized Gaussian keeps the softmax heatmap,
            # and therefore its spread, meaningful at inference time.
            loss = -(target.flatten(2) * log_probability).sum(dim=2).mean()
            coords, _ = decode_heatmaps(logits, torch)
            loss = loss + 0.01 * torch.nn.functional.l1_loss(
                coords, _argmax_coords(target, torch)
            )
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            scheduler.step()
            total += loss.item() * len(pixels)
        history.append(total / len(crops))
        print(f"fold {fold_number} {condition} epoch {epoch + 1}/{epochs} loss {history[-1]:.4f} "
              f"({time.time() - started:.0f}s)", flush=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "fold": fold_number,
            "seed": seed,
            "condition": condition,
            "epochs": epochs,
            "landmark_names": list(LANDMARK_NAMES),
            "train_teeth": len(crops),
            "split_sha256": split["dataset_sha256"],
        },
        output_path,
    )
    return {"fold": fold_number, "condition": condition, "loss": history, "seconds": time.time() - started}


def _argmax_coords(target: Any, torch: Any) -> Any:
    """Expected coordinates of the (already normalized) Gaussian targets."""
    coords, _ = decode_heatmaps(torch.log(target.clamp_min(1e-12)), torch)
    return coords


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fold", type=int, required=True, choices=range(1, 6))
    parser.add_argument("--condition", choices=["raw", "clahe"], default="raw")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "week4" / "weights" / f"{args.condition}_fold_{args.fold}.pt"
    print(json.dumps(train_fold(args.fold, output, condition=args.condition, epochs=args.epochs)))


if __name__ == "__main__":
    main()
