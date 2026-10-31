from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from week4.dataset import consolidate_rounds, dataset_digest, validate_split
from week4.errors import DatasetValidationError, LeakageError
from week4.split import make_group_folds, save_split


SOURCE = Path("week3/reports/collected_study/exports/measurements.json")


def records():
    return json.loads(SOURCE.read_text())


def test_consolidates_round_means_and_noise():
    dataset = consolidate_rounds(records())
    assert dataset["info"]["unique_physical_teeth"] == 15
    assert dataset["info"]["annotation_instances"] == 45
    annotation = dataset["annotations"][0]
    name = "mesial_cej"
    first, second = annotation["rounds"]["1"][name], annotation["rounds"]["2"][name]
    assert annotation["mean"][name] == pytest.approx(
        [(first[0] + second[0]) / 2, (first[1] + second[1]) / 2]
    )
    assert annotation["noise_px"][name] >= 0
    assert len(dataset_digest(dataset)) == 64


def test_consolidation_rejects_empty_malformed_and_missing_round():
    with pytest.raises(DatasetValidationError, match="No measurement"):
        consolidate_rounds([])
    with pytest.raises(DatasetValidationError, match="Malformed"):
        consolidate_rounds([{}])
    one = records()[:1]
    with pytest.raises(DatasetValidationError, match="exactly rounds"):
        consolidate_rounds(one)


def grouped_dataset(group_count=5):
    images = []
    for group in range(group_count):
        for condition in range(2):
            images.append(
                {
                    "id": len(images) + 1,
                    "group_id": f"patient-{group}",
                    "condition": str(condition),
                }
            )
    return {"images": images, "annotations": []}


def test_group_folds_are_deterministic_balanced_and_leak_free(tmp_path):
    dataset = grouped_dataset()
    first = make_group_folds(dataset, seed=7)
    second = make_group_folds(dataset, seed=7)
    assert first == second
    assert [len(f["test_image_ids"]) for f in first["folds"]] == [2] * 5
    target = tmp_path / "split.json"
    save_split(first, target)
    assert json.loads(target.read_text()) == first


def test_split_rejects_too_few_groups_or_missing_group():
    with pytest.raises(DatasetValidationError, match="at least 5"):
        make_group_folds(grouped_dataset(4))
    bad = grouped_dataset()
    bad["images"][0].pop("group_id")
    with pytest.raises(DatasetValidationError, match="patient_id or group_id"):
        make_group_folds(bad)
    with pytest.raises(DatasetValidationError, match="at least 2"):
        make_group_folds(grouped_dataset(), k=1)


def test_validate_split_detects_image_and_group_leakage_and_duplicate_test():
    dataset = grouped_dataset(2)
    with pytest.raises(LeakageError, match="repeats image"):
        validate_split(
            dataset,
            [{"fold": 1, "train_image_ids": [1], "test_image_ids": [1]}],
        )
    with pytest.raises(LeakageError, match="leaks"):
        validate_split(
            dataset,
            [{"fold": 1, "train_image_ids": [1], "test_image_ids": [2]}],
        )
    folds = make_group_folds(dataset, k=2)["folds"]
    duplicate = copy.deepcopy(folds)
    duplicate[1]["test_image_ids"].append(duplicate[0]["test_image_ids"][0])
    with pytest.raises(DatasetValidationError):
        validate_split(dataset, duplicate)
