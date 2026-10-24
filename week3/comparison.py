"""Analyze genuinely re-annotated, matched three-condition measurement records."""

from __future__ import annotations
from collections import defaultdict
from typing import Any
import numpy as np
from week3.exports import validate_record
from week3.image_processing import coordinate_rmsd


def coordinates(record: dict[str, Any]) -> np.ndarray:
    lm = record["landmarks"]
    return np.asarray(
        [
            lm["mesial"]["cej"],
            lm["mesial"]["bc"],
            lm["distal"]["cej"],
            lm["distal"]["bc"],
            lm["apex"],
        ],
        dtype=float,
    )


def compare_conditions(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple, dict] = defaultdict(dict)
    for record in records:
        validate_record(record)
        key = (record["image_id"], record["tooth_id"], record["round"])
        condition = record["condition"]
        if condition in groups[key]:
            raise ValueError(f"Duplicate identity {key}, {condition}")
        groups[key][condition] = record
    complete = {
        key: row for key, row in groups.items() if set(row) == {"raw", "he", "clahe"}
    }
    output: dict[str, Any] = {
        "matched_triplets": len(complete),
        "incomplete_triplets": len(groups) - len(complete),
        "conditions": {},
    }
    reference = [coordinates(row["raw"]) for row in complete.values()]
    for condition in ("raw", "he", "clahe"):
        candidate = [coordinates(row[condition]) for row in complete.values()]
        # Repeats use matched triplets only, so every condition has the same teeth.
        by_tooth: dict[tuple, dict] = defaultdict(dict)
        for (image, tooth, rnd), row in complete.items():
            by_tooth[(image, tooth)][rnd] = coordinates(row[condition])
        repeats = [
            rounds for rounds in by_tooth.values() if 1 in rounds and 2 in rounds
        ]
        delta = np.concatenate([r[2] - r[1] for r in repeats]) if repeats else None
        # Average across landmarks of the summed x/y sample variances of two rounds.
        # For two repeats: s_x²+s_y² = (dx²+dy²)/2, units px².
        variance = (
            float(np.square(delta).sum(axis=1).mean() / 2)
            if delta is not None
            else None
        )
        output["conditions"][condition] = {
            # Raw is the reference; its self-RMSD is trivially 0, so report N/A.
            "coordinate_rmsd_vs_raw_px": (
                coordinate_rmsd(np.concatenate(reference), np.concatenate(candidate))
                if reference and condition != "raw"
                else None
            ),
            "repeat_tooth_pairs": len(repeats),
            "round_coordinate_rmsd_px": (
                float(np.sqrt(np.square(delta).sum(axis=1).mean()))
                if delta is not None
                else None
            ),
            "mean_within_landmark_coordinate_variance_px2": variance,
        }
    return output
