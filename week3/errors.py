"""Descriptive displacement decomposition in each tooth's baseline axis frame."""

from __future__ import annotations
import numpy as np
from week3.pbl_calculator import ToothLandmarks, calculate_tooth_pbl
from week3.sensitivity import LANDMARK_NAMES


def decompose_displacements(
    pairs: list[tuple[ToothLandmarks, ToothLandmarks]],
) -> list[dict]:
    if not pairs:
        raise ValueError("At least one aligned tooth pair is required")
    rows = []
    for name in LANDMARK_NAMES:
        deltas = []
        for first, second in pairs:
            axis = np.asarray(calculate_tooth_pbl(first).long_axis_vector)
            normal = np.array([-axis[1], axis[0]])

            def get(lm: ToothLandmarks) -> np.ndarray:
                if name == "apex":
                    return np.asarray(lm.apex)
                side, landmark = name.split(".")
                return np.asarray(getattr(getattr(lm, side), landmark))

            shift = get(second) - get(first)
            deltas.append([np.dot(shift, axis), np.dot(shift, normal)])
        values = np.asarray(deltas)
        mean = values.mean(axis=0)
        mean_square = float(np.square(values).sum(axis=1).mean())
        drift_square = float(np.square(mean).sum())
        residual_square = float(np.square(values - mean).sum(axis=1).mean())
        rows.append(
            {
                "landmark": name,
                "pairs": len(pairs),
                "mean_parallel_shift_px": float(mean[0]),
                "mean_normal_shift_px": float(mean[1]),
                "rms_displacement_px": float(np.sqrt(mean_square)),
                "mean_drift_magnitude_px": float(np.sqrt(drift_square)),
                "centered_residual_rms_px": float(np.sqrt(residual_square)),
                "drift_fraction_of_mean_square": (
                    drift_square / mean_square if mean_square > 0 else None
                ),
            }
        )
    return rows
