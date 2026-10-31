"""Landmark-to-PBL Monte Carlo propagation and a prespecified review rule."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np

from week3.pbl_calculator import (
    PBLValidationError,
    SideLandmarks,
    ToothLandmarks,
    calculate_tooth_pbl,
)
from week4.constants import LANDMARK_NAMES, SEED, STAGE_BOUNDARIES
from week4.errors import EmptyPredictionError

PointMap = Mapping[str, tuple[float, float]]


def to_tooth_landmarks(points: PointMap) -> ToothLandmarks:
    missing = set(LANDMARK_NAMES) - set(points)
    if missing:
        raise EmptyPredictionError(f"Missing landmarks: {', '.join(sorted(missing))}")
    return ToothLandmarks(
        SideLandmarks(points["mesial_cej"], points["mesial_bc"]),
        SideLandmarks(points["distal_cej"], points["distal_bc"]),
        points["apex"],
    )


@dataclass(frozen=True)
class PBLInterval:
    lower: float
    upper: float
    valid_draws: int
    requested_draws: int

    @property
    def pair(self) -> tuple[float, float]:
        return self.lower, self.upper


def pbl_confidence_interval(
    points: PointMap,
    uncertainty_px: Mapping[str, float],
    *,
    draws: int = 1000,
    seed: int = SEED,
) -> PBLInterval:
    if draws < 100:
        raise ValueError("At least 100 draws are required for a stable 95% interval")
    if set(uncertainty_px) != set(LANDMARK_NAMES):
        raise EmptyPredictionError("Uncertainty is required for all five landmarks")
    values = np.asarray([points[name] for name in LANDMARK_NAMES], dtype=float)
    scales = np.asarray([uncertainty_px[name] for name in LANDMARK_NAMES], dtype=float)
    if not np.isfinite(values).all() or not np.isfinite(scales).all() or np.any(scales < 0):
        raise ValueError("Landmarks and uncertainties must be finite; uncertainty cannot be negative")
    rng = np.random.default_rng(seed)
    samples = rng.normal(values, scales[:, None], size=(draws, len(LANDMARK_NAMES), 2))
    pbl: list[float] = []
    for sample in samples:
        candidate = {name: tuple(map(float, sample[index])) for index, name in enumerate(LANDMARK_NAMES)}
        try:
            pbl.append(calculate_tooth_pbl(to_tooth_landmarks(candidate)).pbl_max_pct)
        except PBLValidationError:
            continue
    if len(pbl) < max(50, draws // 5):
        raise EmptyPredictionError(
            f"Only {len(pbl)}/{draws} uncertainty draws passed anatomical guardrails"
        )
    lower, upper = np.percentile(pbl, [2.5, 97.5])
    return PBLInterval(float(lower), float(upper), len(pbl), draws)


def needs_manual_review(
    interval: PBLInterval,
    uncertainty_px: Mapping[str, float],
    *,
    maximum_landmark_px: float = 5.0,
) -> tuple[bool, tuple[str, ...]]:
    """Flag boundary-crossing intervals or a landmark uncertainty above 5 px."""
    reasons: list[str] = []
    for boundary in STAGE_BOUNDARIES:
        if interval.lower < boundary <= interval.upper:
            reasons.append(f"PBL CI crosses the {boundary:g}% stage boundary")
    worst = max(uncertainty_px.values(), default=math.inf)
    if worst > maximum_landmark_px:
        reasons.append(
            f"maximum landmark uncertainty {worst:.2f}px exceeds {maximum_landmark_px:.2f}px"
        )
    return bool(reasons), tuple(reasons)


# Chosen on DenPAR development folds (smallest k reaching >=90% stage accuracy)
# and confirmed once on the external test; see reports/UNCERTAINTY_REJECTION.md.
MARGIN_K = 0.45


def needs_review_by_margin(
    pbl_pct: float, interval: PBLInterval, *, k: float = MARGIN_K
) -> tuple[bool, tuple[str, ...]]:
    """Flag when PBL lies closer to a stage boundary than k x the CI half-width."""
    half_width = max((interval.upper - interval.lower) / 2, 1e-9)
    boundary = min(STAGE_BOUNDARIES, key=lambda b: abs(pbl_pct - b))
    margin = abs(pbl_pct - boundary)
    if margin < k * half_width:
        return True, (
            f"PBL {pbl_pct:.1f}% is {margin:.1f} pp from the {boundary:g}% boundary, "
            f"under {k:g} x the CI half-width ({half_width:.1f} pp)",
        )
    return False, ()
