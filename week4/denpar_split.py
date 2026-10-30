"""Save the fixed-seed radiograph-level 5-fold split of DenPAR development data.

Development is DenPAR Training + Validation. DenPAR Testing is held out as an
external test set and never enters a fold, model selection, or threshold choice.
"""

from __future__ import annotations

import json
from typing import Any

from week4.split import make_group_folds, save_split
from week4.train import DATASET, SPLIT

DEVELOPMENT = ("Training", "Validation")


def development_subset(dataset: dict[str, Any]) -> dict[str, Any]:
    with_teeth = {int(a["image_id"]) for a in dataset["annotations"]}
    images = [
        i for i in dataset["images"]
        if i["partition"] in DEVELOPMENT and int(i["id"]) in with_teeth
    ]
    ids = {int(i["id"]) for i in images}
    return {
        **dataset,
        "images": images,
        "annotations": [a for a in dataset["annotations"] if int(a["image_id"]) in ids],
    }


def main() -> None:
    dataset = json.loads(DATASET.read_text())
    split = make_group_folds(development_subset(dataset))
    teeth_per_image: dict[int, int] = {}
    for annotation in dataset["annotations"]:
        teeth_per_image[int(annotation["image_id"])] = teeth_per_image.get(int(annotation["image_id"]), 0) + 1
    for fold in split["folds"]:
        fold["test_teeth"] = sum(teeth_per_image[i] for i in fold["test_image_ids"])
    split["development_partitions"] = list(DEVELOPMENT)
    split["external_test_partition"] = "Testing"
    save_split(split, SPLIT)
    print(json.dumps([{k: f[k] for k in ("fold", "test_teeth")} for f in split["folds"]]))


if __name__ == "__main__":
    main()
