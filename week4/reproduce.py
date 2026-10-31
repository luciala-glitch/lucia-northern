"""Regenerate data inventory, consolidated annotations, and safe split metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from week4.dataset import consolidate_rounds, write_dataset
from week4.errors import DatasetValidationError
from week4.split import make_group_folds, save_split

ROOT = Path(__file__).resolve().parents[1]
WEEK4 = ROOT / "week4"


def _demo_inventory(partition: str) -> tuple[int, int]:
    root = WEEK4 / "demo_denpar" / partition
    files = sorted((root / "images").glob("*.jpg"))
    teeth = 0
    for image in files:
        annotation = root / "official_annotations" / "keypoints" / f"{image.stem}.json"
        teeth += len(json.loads(annotation.read_text())["bboxes"])
    return len(files), teeth


def _review_records() -> tuple[list[dict[str, object]], int]:
    """Return latest complete manual round-pairs and the incomplete-pair count."""
    path = WEEK4 / "data" / "corrections.json"
    if not path.is_file():
        return [], 0
    bundles = json.loads(path.read_text())
    latest: dict[tuple[object, ...], dict[str, object]] = {}
    for bundle in bundles:
        record = bundle["corrected_result"]
        key = (
            record["image_id"],
            record["tooth_id"],
            record["condition"],
            record["round"],
        )
        latest[key] = record
    pairs: dict[tuple[object, ...], dict[int, dict[str, object]]] = {}
    for record in latest.values():
        key = (record["image_id"], record["tooth_id"], record["condition"])
        pairs.setdefault(key, {})[int(record["round"])] = record
    complete = [
        rounds[number]
        for rounds in pairs.values()
        if set(rounds) == {1, 2}
        for number in (1, 2)
    ]
    incomplete = sum(set(rounds) != {1, 2} for rounds in pairs.values())
    return complete, incomplete


def _denpar_status() -> dict[str, object]:
    path = WEEK4 / "data" / "denpar_landmarks.json"
    split = WEEK4 / "data" / "denpar_split_5fold.json"
    if not path.is_file():
        return {"status": "not built; run `make data`"}
    info = json.loads(path.read_text())["info"]
    return {
        "teeth_kept": info["teeth_kept"],
        "tooth_masks": info["tooth_masks"],
        "excluded_by_reason": info["excluded_by_reason"],
        "split_saved": split.is_file(),
    }


def reproduce(*, strict: bool = False) -> dict[str, object]:
    source = ROOT / "week3" / "reports" / "collected_study" / "exports" / "measurements.json"
    records = json.loads(source.read_text())
    reviewed, incomplete_reviews = _review_records()
    development = [
        record
        for record in reviewed
        if str(record["image_id"]).startswith("denpar_development_")
    ]
    external = [
        record
        for record in reviewed
        if str(record["image_id"]).startswith("denpar_external_test_")
    ]
    dataset = consolidate_rounds([*records, *development])
    output = WEEK4 / "data" / "week3_round_means.json"
    write_dataset(dataset, output)
    development_images, development_teeth = _demo_inventory("development")
    test_images, test_teeth = _demo_inventory("external_test")
    split_status: str
    try:
        if int(dataset["info"]["unique_physical_teeth"]) < 60:
            raise DatasetValidationError(
                "At least 60 distinct teeth are required before model evaluation; "
                f"found {dataset['info']['unique_physical_teeth']}"
            )
        split = make_group_folds(dataset)
        save_split(split, WEEK4 / "data" / "split_5fold.json")
        split_status = "created"
    except DatasetValidationError as exc:
        split_status = f"blocked safely: {exc}"
        if strict:
            raise
    status: dict[str, object] = {
        "week3_source_records": len(records),
        "round_mean_annotation_instances": dataset["info"]["annotation_instances"],
        "unique_manually_measured_teeth": dataset["info"]["unique_physical_teeth"],
        "unique_image_groups": len({i["group_id"] for i in dataset["images"]}),
        "complete_saved_review_records": len(reviewed),
        "incomplete_saved_review_pairs": incomplete_reviews,
        "complete_development_review_records": len(development),
        "complete_external_test_review_records": len(external),
        "denpar_development_images": development_images,
        "denpar_development_tooth_boxes": development_teeth,
        "denpar_external_test_images": test_images,
        "denpar_external_test_tooth_boxes": test_teeth,
        # This gate concerns my own two-round readings (15 teeth, one image).
        # Model folds are built from DenPAR instead; see week4/denpar_split.py.
        "five_fold_split": split_status,
        "denpar_ground_truth": _denpar_status(),
        "learned_metrics_released": (WEEK4 / "reports" / "results" / "metrics.json").is_file(),
        "reason": (
            "Own readings stay a 15-tooth, one-image repeatability reference. The detector is "
            "trained and evaluated on DenPAR's official annotations with radiograph-level folds."
        ),
    }
    (WEEK4 / "reports").mkdir(parents=True, exist_ok=True)
    (WEEK4 / "reports" / "data_readiness.json").write_text(
        json.dumps(status, indent=2) + "\n"
    )
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail until a valid five-fold split is possible",
    )
    args = parser.parse_args()
    print(json.dumps(reproduce(strict=args.strict), indent=2))


if __name__ == "__main__":
    main()
