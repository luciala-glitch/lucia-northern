"""Configurable re-training of the Week 4 heatmap detector for Week 5 experiments.

The training loop, crop geometry, split and checkpoint format are those of
``week4.train``; only the hyper-parameters named in :class:`TrainConfig`
change, so a Week 5 checkpoint loads in ``LearnedHeatmapDetector`` unchanged.

Screen one configuration on development fold 1 (never the external test):

    python -m week5.train --config strong_aug --fold 1 --output week5/weights/screen/strong_aug_raw_fold_1.pt
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import random
import time
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from week4.constants import LANDMARK_NAMES, SEED
from week4.model import build_heatmap_model, decode_heatmaps, to_input_tensor
from week4.train import DATASET, ROOT, SPLIT, _argmax_coords, device, load_crops, seed_everything
from week4.training import augment, gaussian_heatmaps

WEIGHTS = ROOT / "week5" / "weights"


@dataclass(frozen=True)
class TrainConfig:
    """Every knob varied in the Week 5 screen; defaults reproduce Week 4 exactly."""

    name: str = "week4"
    learning_rate: float = 5e-4
    epochs: int = 30
    batch_size: int = 16
    heatmap_sigma: float = 3.0
    coord_weight: float = 0.01
    rotation_degrees: float = 15.0
    scale_jitter: float = 0.08
    photometric: bool = False


BASE = TrainConfig()
CONFIGS: dict[str, TrainConfig] = {
    "week4": BASE,
    "lr_1e-3": replace(BASE, name="lr_1e-3", learning_rate=1e-3),
    "lr_2.5e-4": replace(BASE, name="lr_2.5e-4", learning_rate=2.5e-4),
    # Wider geometry plus gamma/blur/noise, aimed at tilted and low-quality films.
    "strong_aug": replace(
        BASE, name="strong_aug", rotation_degrees=25.0, scale_jitter=0.15, photometric=True
    ),
    # Week 4's dominant error is along-axis crest displacement; a stronger
    # coordinate term penalises it directly instead of only the heatmap shape.
    "coord_0.1": replace(BASE, name="coord_0.1", coord_weight=0.1),
    "sigma_2": replace(BASE, name="sigma_2", heatmap_sigma=2.0),
}


def photometric(image: Image.Image, rng: random.Random) -> Image.Image:
    """Gamma, mild blur and sensor-like noise; geometry (and labels) are untouched."""
    gamma = rng.uniform(0.7, 1.4)
    lut = [round(255 * (value / 255) ** gamma) for value in range(256)]
    working = image.point(lut)
    if rng.random() < 0.3:
        working = working.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 1.5)))
    if rng.random() < 0.3:
        noise = np.random.default_rng(rng.randrange(2**32)).normal(0.0, rng.uniform(3.0, 12.0), (working.height, working.width))
        working = Image.fromarray(np.clip(np.asarray(working, dtype=np.float32) + noise, 0, 255).astype(np.uint8))
    return working


def train_fold(
    config: TrainConfig,
    fold_number: int,
    output_path: Path,
    *,
    condition: str = "raw",
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
            sample = augment(
                crops[index].image,
                local_points[index],
                rng,
                rotation_degrees=config.rotation_degrees,
                scale_jitter=config.scale_jitter,
                clahe_probability=0.35 if condition == "raw" else 0.0,
            )
            image = photometric(sample.image, rng) if config.photometric else sample.image
            pixels = np.asarray(image, dtype=np.uint8)
            target = gaussian_heatmaps(sample.points, image.size, sigma=config.heatmap_sigma)
            target /= np.maximum(target.sum(axis=(1, 2), keepdims=True), 1e-8)
            return torch.from_numpy(pixels.copy()), torch.from_numpy(target)

    run_device = device()
    model = build_heatmap_model(pretrained=True).to(run_device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=1e-4)
    steps = config.epochs * ((len(crops) + config.batch_size - 1) // config.batch_size)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(optimizer, max_lr=config.learning_rate, total_steps=steps)
    data = Teeth()
    loader = DataLoader(
        data,
        batch_size=config.batch_size,
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
        num_workers=0,
    )
    history = []
    started = time.time()
    model.train()
    for epoch in range(config.epochs):
        data.epoch = epoch
        total = 0.0
        for pixels, target in loader:
            pixels, target = pixels.to(run_device), target.to(run_device)
            logits = model(to_input_tensor(pixels, torch))
            log_probability = torch.log_softmax(logits.flatten(2), dim=2)
            loss = -(target.flatten(2) * log_probability).sum(dim=2).mean()
            coords, _ = decode_heatmaps(logits, torch)
            loss = loss + config.coord_weight * torch.nn.functional.l1_loss(coords, _argmax_coords(target, torch))
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            scheduler.step()
            total += loss.item() * len(pixels)
        history.append(total / len(crops))
        print(f"{config.name} fold {fold_number} {condition} epoch {epoch + 1}/{config.epochs} "
              f"loss {history[-1]:.4f} ({time.time() - started:.0f}s)", flush=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "fold": fold_number,
            "seed": seed,
            "condition": condition,
            "epochs": config.epochs,
            "landmark_names": list(LANDMARK_NAMES),
            "train_teeth": len(crops),
            "split_sha256": split["dataset_sha256"],
            "config": asdict(config),
        },
        output_path,
    )
    return {"config": config.name, "fold": fold_number, "condition": condition, "loss": history,
            "seconds": time.time() - started}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--fold", type=int, required=True, choices=range(1, 6))
    parser.add_argument("--condition", choices=["raw", "clahe"], default="raw")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = CONFIGS[args.config]
    output = args.output or WEIGHTS / f"{config.name}_{args.condition}_fold_{args.fold}.pt"
    print(json.dumps(train_fold(config, args.fold, output, condition=args.condition)))


if __name__ == "__main__":
    main()
