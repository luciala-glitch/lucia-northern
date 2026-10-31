"""Fixed-seed group k-fold splitting at patient/image level."""

from __future__ import annotations

import json
from pathlib import Path
import random
from typing import Any

from week4.constants import SEED
from week4.dataset import dataset_digest, validate_split
from week4.errors import DatasetValidationError


def make_group_folds(
    dataset: dict[str, Any], k: int = 5, seed: int = SEED
) -> dict[str, Any]:
    if k < 2:
        raise DatasetValidationError("k must be at least 2")
    grouped: dict[str, list[int]] = {}
    for image in dataset.get("images", []):
        group = str(image.get("patient_id") or image.get("group_id") or "")
        if not group:
            raise DatasetValidationError("Every image needs patient_id or group_id")
        grouped.setdefault(group, []).append(int(image["id"]))
    if len(grouped) < k:
        raise DatasetValidationError(
            f"Leakage-free {k}-fold CV needs at least {k} image/patient groups; found {len(grouped)}"
        )
    groups = sorted(grouped)
    random.Random(seed).shuffle(groups)
    buckets: list[list[str]] = [[] for _ in range(k)]
    loads = [0] * k
    for group in sorted(groups, key=lambda g: (-len(grouped[g]), groups.index(g))):
        target = min(range(k), key=lambda index: (loads[index], index))
        buckets[target].append(group)
        loads[target] += len(grouped[group])
    all_images = {int(i["id"]) for i in dataset["images"]}
    folds = []
    for index, test_groups in enumerate(buckets, start=1):
        test_ids = sorted(i for g in test_groups for i in grouped[g])
        folds.append(
            {
                "fold": index,
                "train_image_ids": sorted(all_images - set(test_ids)),
                "test_image_ids": test_ids,
                "test_groups": sorted(test_groups),
            }
        )
    validate_split(dataset, folds)
    return {"seed": seed, "k": k, "dataset_sha256": dataset_digest(dataset), "folds": folds}


def save_split(split: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(split, indent=2) + "\n")
