"""Landmark, axial, downstream agreement, calibration, and coverage metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import numpy as np
from numpy.typing import ArrayLike

from week3.pbl_calculator import PBLValidationError, calculate_tooth_pbl
from week3.statistics import agreement
from week4.constants import LANDMARK_NAMES
from week4.uncertainty import to_tooth_landmarks


@dataclass(frozen=True)
class LandmarkMetrics:
    landmark: str
    n: int
    mre_px: float
    sdr_2px: float
    sdr_5px: float
    sdr_10px: float
    along_axis_mae_px: float
    perpendicular_mae_px: float


def _arrays(manual: ArrayLike, predicted: ArrayLike, axes: ArrayLike) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    truth = np.asarray(manual, dtype=float)
    estimate = np.asarray(predicted, dtype=float)
    unit = np.asarray(axes, dtype=float)
    if truth.shape != estimate.shape or truth.ndim != 3 or truth.shape[1:] != (5, 2):
        raise ValueError("manual and predicted must both have shape (N, 5, 2)")
    if unit.shape != (len(truth), 2):
        raise ValueError("axes must have shape (N, 2)")
    length = np.linalg.norm(unit, axis=1)
    if not np.isfinite(truth).all() or not np.isfinite(estimate).all() or np.any(length <= 0):
        raise ValueError("Coordinates and non-zero axes must be finite")
    return truth, estimate, unit / length[:, None]


def landmark_metrics(manual: ArrayLike, predicted: ArrayLike, axes: ArrayLike) -> list[LandmarkMetrics]:
    truth, estimate, unit = _arrays(manual, predicted, axes)
    error = estimate - truth
    radial = np.linalg.norm(error, axis=2)
    along = np.abs(np.einsum("nki,ni->nk", error, unit))
    perpendicular_unit = np.column_stack((-unit[:, 1], unit[:, 0]))
    perpendicular = np.abs(np.einsum("nki,ni->nk", error, perpendicular_unit))
    rows: list[LandmarkMetrics] = []
    for index, name in enumerate(LANDMARK_NAMES):
        rows.append(
            LandmarkMetrics(
                name,
                len(truth),
                float(radial[:, index].mean()),
                float((radial[:, index] <= 2).mean()),
                float((radial[:, index] <= 5).mean()),
                float((radial[:, index] <= 10).mean()),
                float(along[:, index].mean()),
                float(perpendicular[:, index].mean()),
            )
        )
    return rows


def metric_dicts(rows: Iterable[LandmarkMetrics]) -> list[dict[str, object]]:
    return [asdict(row) for row in rows]


STAGE_CODE = {"I": 0, "II": 1, "III/IV": 2}


def downstream_agreement(
    manual: Sequence[dict[str, tuple[float, float]]],
    predicted: Sequence[dict[str, tuple[float, float]]],
) -> dict[str, object]:
    if len(manual) != len(predicted) or len(manual) < 2:
        raise ValueError("At least two aligned manual/predicted cases are required")
    manual_results, predicted_results = [], []
    invalid: list[int] = []
    for index, (truth, estimate) in enumerate(zip(manual, predicted)):
        try:
            manual_results.append(calculate_tooth_pbl(to_tooth_landmarks(truth)))
            predicted_results.append(calculate_tooth_pbl(to_tooth_landmarks(estimate)))
        except PBLValidationError:
            invalid.append(index)
    if len(manual_results) < 2:
        raise ValueError("Fewer than two anatomically valid prediction pairs remain")
    truth_pbl = np.asarray([r.pbl_max_pct for r in manual_results])
    predicted_pbl = np.asarray([r.pbl_max_pct for r in predicted_results])
    truth_stage = np.asarray([STAGE_CODE[r.stage] for r in manual_results])
    predicted_stage = np.asarray([STAGE_CODE[r.stage] for r in predicted_results])
    stats = agreement(truth_pbl, predicted_pbl, truth_stage, predicted_stage)
    confusion = np.zeros((3, 3), dtype=int)
    for expected, observed in zip(truth_stage, predicted_stage):
        confusion[expected, observed] += 1
    severe = truth_stage == 2
    severe_undercall = int(np.sum(severe & (predicted_stage < 2)))
    return {
        "n": stats.n,
        "icc_2_1": stats.icc_2_1,
        "quadratic_weighted_kappa": stats.weighted_kappa,
        "bias_pct_points": stats.bias,
        "loa_lower": stats.loa_lower,
        "loa_upper": stats.loa_upper,
        "confusion_rows_manual_cols_predicted": confusion.tolist(),
        "invalid_prediction_indices": invalid,
        "invalid_prediction_rate": len(invalid) / len(manual),
        "severe_cases": int(severe.sum()),
        "severe_undercalls": severe_undercall,
        "severe_undercall_rate": (severe_undercall / int(severe.sum())) if severe.any() else None,
    }


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(len(values), dtype=float)
    return ranks


def uncertainty_error_correlation(uncertainty: ArrayLike, error: ArrayLike) -> dict[str, float | None]:
    u, e = np.asarray(uncertainty, dtype=float), np.asarray(error, dtype=float)
    if u.ndim != 1 or e.shape != u.shape or len(u) < 3 or not np.isfinite(np.column_stack((u, e))).all():
        raise ValueError("At least three aligned finite uncertainty/error values are required")
    pearson = float(np.corrcoef(u, e)[0, 1]) if u.std() > 0 and e.std() > 0 else None
    ur, er = _rank(u), _rank(e)
    spearman = float(np.corrcoef(ur, er)[0, 1]) if ur.std() > 0 and er.std() > 0 else None
    return {"pearson_r": pearson, "spearman_rho": spearman}


def risk_coverage(
    uncertainty: ArrayLike,
    absolute_pbl_error: ArrayLike,
    stage_correct: ArrayLike,
) -> dict[str, object]:
    u = np.asarray(uncertainty, dtype=float)
    error = np.asarray(absolute_pbl_error, dtype=float)
    correct = np.asarray(stage_correct, dtype=bool)
    if u.ndim != 1 or error.shape != u.shape or correct.shape != u.shape or len(u) == 0:
        raise ValueError("Risk-coverage inputs must be aligned one-dimensional arrays")
    order = np.argsort(u, kind="stable")
    cumulative_error = np.cumsum(error[order]) / np.arange(1, len(u) + 1)
    cumulative_accuracy = np.cumsum(correct[order]) / np.arange(1, len(u) + 1)
    coverage = np.arange(1, len(u) + 1) / len(u)
    eligible = np.flatnonzero(cumulative_accuracy >= 0.90)
    return {
        "coverage": coverage.tolist(),
        "accepted_mae_pct_points": cumulative_error.tolist(),
        "accepted_stage_accuracy": cumulative_accuracy.tolist(),
        "maximum_coverage_at_90pct_stage_accuracy": (
            float(coverage[eligible[-1]]) if eligible.size else None
        ),
    }
