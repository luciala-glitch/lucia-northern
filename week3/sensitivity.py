"""One-landmark-at-a-time stress tests; recompute the axis after each shift."""

from __future__ import annotations
from dataclasses import replace
from week3.pbl_calculator import (
    ToothLandmarks,
    calculate_tooth_pbl,
    long_axis,
    PBLValidationError,
)

LANDMARK_NAMES = ("mesial.cej", "mesial.bc", "distal.cej", "distal.bc", "apex")


def perturb(
    landmarks: ToothLandmarks, name: str, delta: tuple[float, float]
) -> ToothLandmarks:
    if name == "apex":
        original = landmarks.apex
        return replace(landmarks, apex=(original[0] + delta[0], original[1] + delta[1]))
    side_name, point_name = name.split(".")
    side = getattr(landmarks, side_name)
    original = getattr(side, point_name)
    return replace(
        landmarks,
        **{
            side_name: replace(
                side, **{point_name: (original[0] + delta[0], original[1] + delta[1])}
            )
        },
    )


def sensitivity(landmarks: ToothLandmarks) -> list[dict[str, object]]:
    baseline = calculate_tooth_pbl(landmarks)
    axis = long_axis(landmarks)
    rows = []
    for name in LANDMARK_NAMES:
        for direction, vector in [("parallel", axis), ("normal", (-axis[1], axis[0]))]:
            for size in (2, 5, 10):
                for sign in (-1, 1):
                    row: dict[str, object] = {
                        "landmark": name,
                        "direction": direction,
                        "shift_px": size * sign,
                    }
                    try:
                        result = calculate_tooth_pbl(
                            perturb(
                                landmarks,
                                name,
                                (vector[0] * size * sign, vector[1] * size * sign),
                            )
                        )
                        row.update(
                            status="valid",
                            mesial_change_pp=result.mesial.pbl_pct
                            - baseline.mesial.pbl_pct,
                            distal_change_pp=result.distal.pbl_pct
                            - baseline.distal.pbl_pct,
                            max_change_pp=result.pbl_max_pct - baseline.pbl_max_pct,
                            stage_changed=result.stage != baseline.stage,
                        )
                    except PBLValidationError as exc:
                        row.update(
                            status=type(exc).__name__,
                            mesial_change_pp=None,
                            distal_change_pp=None,
                            max_change_pp=None,
                            stage_changed=None,
                        )
                    rows.append(row)
    return rows
