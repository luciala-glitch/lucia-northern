"""Build a COCO-style five-keypoint dataset without hiding repeatability noise."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from week4.constants import LANDMARK_NAMES
from week4.errors import DatasetValidationError, LeakageError


def _points(record: dict[str, Any]) -> dict[str, tuple[float, float]]:
    lm = record["landmarks"]
    return {
        "mesial_cej": tuple(map(float, lm["mesial"]["cej"])),
        "distal_cej": tuple(map(float, lm["distal"]["cej"])),
        "mesial_bc": tuple(map(float, lm["mesial"]["bc"])),
        "distal_bc": tuple(map(float, lm["distal"]["bc"])),
        "apex": tuple(map(float, lm["apex"])),
    }


def consolidate_rounds(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Average exactly two rounds per image/tooth/condition and retain disagreement.

    ``noise_px`` is the full Euclidean round-1-vs-round-2 difference, not a
    standard error. The physical image id remains ``group_id`` so preprocessing
    variants can never leak across folds.
    """
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        try:
            key = (record["image_id"], int(record["tooth_id"]), record["condition"])
            grouped[key].append(record)
        except (KeyError, TypeError, ValueError) as exc:
            raise DatasetValidationError(f"Malformed measurement record: {exc}") from exc
    if not grouped:
        raise DatasetValidationError("No measurement records were supplied")

    image_lookup: dict[tuple[str, str], int] = {}
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for annotation_id, (key, pair) in enumerate(sorted(grouped.items()), start=1):
        image_id, tooth_id, condition = key
        rounds = {int(r["round"]): r for r in pair}
        if set(rounds) != {1, 2} or len(pair) != 2:
            raise DatasetValidationError(
                f"{key!r} needs exactly rounds 1 and 2; found {sorted(rounds)}"
            )
        image_key = (image_id, condition)
        if image_key not in image_lookup:
            image_lookup[image_key] = len(images) + 1
            images.append(
                {
                    "id": image_lookup[image_key],
                    "file_name": image_id,
                    "condition": condition,
                    "group_id": image_id,
                }
            )
        first, second = _points(rounds[1]), _points(rounds[2])
        mean = {
            name: [(first[name][i] + second[name][i]) / 2 for i in (0, 1)]
            for name in LANDMARK_NAMES
        }
        noise = {
            name: math.dist(first[name], second[name]) for name in LANDMARK_NAMES
        }
        flat = [coordinate for name in LANDMARK_NAMES for coordinate in mean[name]]
        annotations.append(
            {
                "id": annotation_id,
                "image_id": image_lookup[image_key],
                "tooth_id": tooth_id,
                "category_id": 1,
                "num_keypoints": 5,
                "keypoints": flat,
                "keypoint_names": list(LANDMARK_NAMES),
                "mean": mean,
                "rounds": {"1": first, "2": second},
                "noise_px": noise,
            }
        )
    unique_teeth = {(a["tooth_id"], next(i["group_id"] for i in images if i["id"] == a["image_id"])) for a in annotations}
    return {
        "info": {
            "description": "Two-round PBL landmark means with observed inter-round differences",
            "ground_truth": "coordinate-wise mean of rounds 1 and 2",
            "noise": "Euclidean round-1-vs-round-2 distance in original pixels",
            "unique_physical_teeth": len(unique_teeth),
            "annotation_instances": len(annotations),
        },
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 1, "name": "tooth", "keypoints": list(LANDMARK_NAMES)}],
    }


def dataset_digest(dataset: dict[str, Any]) -> str:
    canonical = json.dumps(dataset, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def write_dataset(dataset: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dataset, indent=2, allow_nan=False) + "\n")


def validate_split(dataset: dict[str, Any], folds: list[dict[str, Any]]) -> None:
    """Reject missing examples and any group shared by train and test."""
    image_group = {int(i["id"]): str(i.get("patient_id") or i["group_id"]) for i in dataset["images"]}
    all_ids = {int(i["id"]) for i in dataset["images"]}
    test_counts = {image_id: 0 for image_id in all_ids}
    for fold in folds:
        train, test = set(fold["train_image_ids"]), set(fold["test_image_ids"])
        if train & test:
            raise LeakageError(f"Fold {fold['fold']} repeats image ids in train and test")
        if {image_group[i] for i in train} & {image_group[i] for i in test}:
            raise LeakageError(f"Fold {fold['fold']} leaks an image/patient group")
        for image_id in test:
            if image_id not in test_counts:
                raise DatasetValidationError(f"Split refers to unknown image id {image_id}")
            test_counts[image_id] += 1
    if any(count != 1 for count in test_counts.values()):
        raise DatasetValidationError("Every image variant must appear in exactly one test fold")
