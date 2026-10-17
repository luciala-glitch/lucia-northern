"""CSV persistence and repeatability summaries for PBL measurements."""

from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


POINT_NAMES = (
    "mesial_cej",
    "mesial_bone_crest",
    "mesial_root_tip",
    "distal_cej",
    "distal_bone_crest",
    "distal_root_tip",
)

CSV_FIELDS = [
    "timestamp_utc",
    "observer",
    "round",
    "image_id",
    "image_width",
    "image_height",
    "tooth_id",
    "clahe_enabled",
    "app_version",
    "supersedes_timestamp_utc",
]
for point_name in POINT_NAMES:
    CSV_FIELDS.extend((f"{point_name}_x", f"{point_name}_y"))
CSV_FIELDS.extend(
    ("mesial_pbl", "distal_pbl", "worst_side", "worst_pbl", "stage")
)


def make_measurement_row(
    *, observer: str, round_name: str, image_id: str, tooth_id: str,
    image_size: tuple[int, int],
    points: Mapping[str, tuple[float, float]], mesial_pbl: float,
    distal_pbl: float, worst_side: str, worst_pbl: float, stage: str,
    clahe_enabled: bool = False, app_version: str = "unknown",
) -> dict[str, str]:
    """Build one CSV row. Points should be in original image pixels."""
    missing = [name for name in POINT_NAMES if name not in points]
    if missing:
        raise ValueError(f"Missing measurement points: {', '.join(missing)}")
    if not observer.strip():
        raise ValueError("Reader name is required")
    if not tooth_id.strip():
        raise ValueError("Tooth ID is required")

    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "observer": observer.strip(),
        "round": round_name,
        "image_id": image_id,
        "image_width": str(image_size[0]),
        "image_height": str(image_size[1]),
        "tooth_id": tooth_id.strip(),
        "clahe_enabled": str(bool(clahe_enabled)).lower(),
        "app_version": app_version,
        "supersedes_timestamp_utc": "",
        "mesial_pbl": f"{mesial_pbl:.3f}",
        "distal_pbl": f"{distal_pbl:.3f}",
        "worst_side": worst_side,
        "worst_pbl": f"{worst_pbl:.3f}",
        "stage": stage,
    }
    for point_name in POINT_NAMES:
        x, y = points[point_name]
        row[f"{point_name}_x"] = str(round(x))
        row[f"{point_name}_y"] = str(round(y))
    return row


def read_measurements(path: Path) -> list[dict[str, str]]:
    """Read saved measurements, returning an empty list for a missing file."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def save_measurement(path: Path, row: Mapping[str, str]) -> None:
    """Append a measurement while preserving any earlier version.

    Reader, round, image, and tooth identify a record. Re-measuring the same
    item records the timestamp of the most recent matching row so the audit
    trail remains explicit. Summaries use the latest version of each reading.
    """
    rows = read_measurements(path)
    identity_fields = ("observer", "round", "image_id", "tooth_id")
    identity = tuple(row[field] for field in identity_fields)
    prior_versions = [
        existing for existing in rows
        if tuple(existing.get(field, "") for field in identity_fields) == identity
    ]
    new_row = {field: str(row.get(field, "")) for field in CSV_FIELDS}
    if prior_versions:
        new_row["supersedes_timestamp_utc"] = prior_versions[-1].get(
            "timestamp_utc", ""
        )
    rows.append(new_row)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)


def _point_shift(first: Mapping[str, str], second: Mapping[str, str],
                 name: str) -> float | None:
    try:
        x1, y1 = float(first[f"{name}_x"]), float(first[f"{name}_y"])
        x2, y2 = float(second[f"{name}_x"]), float(second[f"{name}_y"])
    except (KeyError, ValueError):
        return None
    return math.hypot(x2 - x1, y2 - y1)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sample_standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def summarize_repeatability(
    rows: Iterable[Mapping[str, str]],
) -> dict[str, object]:
    """Compare Round 1 with Round 2 for each observer/image/tooth."""
    grouped: dict[tuple[str, str, str], dict[str, Mapping[str, str]]] = {}
    for row in rows:
        key = (row["observer"], row["image_id"], row["tooth_id"])
        grouped.setdefault(key, {})[row["round"]] = row

    pairs = []
    for key, rounds in sorted(grouped.items()):
        if "Round 1" not in rounds or "Round 2" not in rounds:
            continue
        first, second = rounds["Round 1"], rounds["Round 2"]
        pair = {
            "observer": key[0],
            "image_id": key[1],
            "tooth_id": key[2],
        }
        for col in ("mesial_pbl", "distal_pbl", "worst_pbl"):
            pair[f"{col}_r1"] = float(first[col])
            pair[f"{col}_r2"] = float(second[col])
            pair[f"{col}_change"] = float(second[col]) - float(first[col])
        pair["worst_side_r1"] = first["worst_side"]
        pair["worst_side_r2"] = second["worst_side"]
        pair["stage_r1"] = first["stage"]
        pair["stage_r2"] = second["stage"]
        pair["stage_changed"] = first["stage"] != second["stage"]
        for name in POINT_NAMES:
            pair[f"{name}_shift_px"] = _point_shift(first, second, name)
        pairs.append(pair)

    def abs_changes(col: str) -> list[float]:
        return [abs(p[f"{col}_change"]) for p in pairs]

    worst_changes = abs_changes("worst_pbl")
    signed_worst_changes = [p["worst_pbl_change"] for p in pairs]
    mean_bias = _mean(signed_worst_changes)
    difference_sd = _sample_standard_deviation(signed_worst_changes)
    within_subject_sd = (
        math.sqrt(
            sum(change ** 2 for change in signed_worst_changes)
            / (2 * len(signed_worst_changes))
        )
        if signed_worst_changes else 0.0
    )
    stage_changes = sum(p["stage_changed"] for p in pairs)

    landmark_shift = {}
    for name in POINT_NAMES:
        shifts = [p[f"{name}_shift_px"] for p in pairs
                  if p[f"{name}_shift_px"] is not None]
        landmark_shift[name] = _mean(shifts)

    return {
        "pair_count": len(pairs),
        "mean_absolute_pbl_change": _mean(worst_changes),
        "max_absolute_pbl_change": max(worst_changes, default=0.0),
        "mean_absolute_mesial_change": _mean(abs_changes("mesial_pbl")),
        "mean_absolute_distal_change": _mean(abs_changes("distal_pbl")),
        "mean_signed_pbl_change": mean_bias,
        "pbl_difference_sd": difference_sd,
        "loa_lower": mean_bias - 1.96 * difference_sd,
        "loa_upper": mean_bias + 1.96 * difference_sd,
        "within_subject_sd": within_subject_sd,
        "repeatability_coefficient": 2.77 * within_subject_sd,
        "stage_change_count": stage_changes,
        "stage_agreement_percent": (
            (len(pairs) - stage_changes) / len(pairs) * 100 if pairs else 0.0
        ),
        "worst_side_change_count": sum(
            p["worst_side_r1"] != p["worst_side_r2"] for p in pairs
        ),
        "mean_landmark_shift_px": landmark_shift,
        "pairs": pairs,
    }
