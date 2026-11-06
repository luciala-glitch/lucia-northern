"""Monte Carlo stage probabilities and the Week 5 stage-aware review policy.

Week 4 asked only whether the 95% PBL interval crossed a stage boundary. That
treats a 3% chance and a 45% chance of a different stage alike and ignores the
direction of the error. Week 5 keeps the same landmark sampling (so the 95%
interval is identical to ``week4.uncertainty.pbl_confidence_interval``) and
also reports the share of draws that land in each stage. The review policy
then asks two clinical questions, with thresholds frozen on development data:

1. Is the automatic stage itself uncertain? (``P(auto stage) < min_stage_probability``)
2. Could this be a missed Stage III/IV? (auto I/II but ``P(III/IV) >= severe_guard``)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Mapping, Sequence

import numpy as np

from week3.pbl_calculator import PBLValidationError, calculate_tooth_pbl
from week4.constants import LANDMARK_NAMES, SEED
from week4.errors import EmptyPredictionError
from week4.uncertainty import PBLInterval, PointMap, to_tooth_landmarks

STAGES = ("I", "II", "III/IV")


def widen_interval(interval: PBLInterval, point: float, factor: float) -> PBLInterval:
    """Stretch each side of the Monte Carlo interval about the point estimate.

    ``factor`` is a split-conformal multiplier fitted on development data so the
    reported 95% PBL interval really covers 95%; stage probabilities are left
    untouched because they are already calibrated.
    """
    if factor <= 0 or not math.isfinite(factor):
        raise ValueError("Interval factor must be positive and finite")
    lower = point - factor * max(point - interval.lower, 0.0)
    upper = point + factor * max(interval.upper - point, 0.0)
    return PBLInterval(max(0.0, lower), min(100.0, upper), interval.valid_draws, interval.requested_draws)


def conformal_factor(rows: Sequence[tuple[float, float, float, float]], coverage: float = 0.95) -> float:
    """Smallest stretch giving ``coverage`` on (point, lower, upper, truth) rows (split conformal)."""
    scores = []
    for point, lower, upper, truth in rows:
        if truth < point:
            scores.append((point - truth) / max(point - lower, 1e-6))
        else:
            scores.append((truth - point) / max(upper - point, 1e-6))
    n = len(scores)
    level = min(1.0, math.ceil((n + 1) * coverage) / n)
    return float(max(1.0, np.quantile(scores, level, method="higher")))


@dataclass(frozen=True)
class StageAnalysis:
    interval: PBLInterval
    probabilities: dict[str, float]

    def probability(self, stage: str) -> float:
        return self.probabilities[stage]


def stage_analysis(
    points: PointMap,
    uncertainty_px: Mapping[str, float],
    *,
    draws: int = 1000,
    seed: int = SEED,
) -> StageAnalysis:
    """95% PBL interval plus stage probabilities from the same landmark draws.

    The sampling order matches Week 4 exactly, so the interval is unchanged for
    a given seed; only valid (guardrail-passing) draws enter the probabilities.
    """
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
    stages: list[str] = []
    for sample in samples:
        candidate = {name: tuple(map(float, sample[index])) for index, name in enumerate(LANDMARK_NAMES)}
        try:
            result = calculate_tooth_pbl(to_tooth_landmarks(candidate))
        except PBLValidationError:
            continue
        pbl.append(result.pbl_max_pct)
        stages.append(result.stage)
    if len(pbl) < max(50, draws // 5):
        raise EmptyPredictionError(
            f"Only {len(pbl)}/{draws} uncertainty draws passed anatomical guardrails"
        )
    lower, upper = np.percentile(pbl, [2.5, 97.5])
    probabilities = {stage: stages.count(stage) / len(stages) for stage in STAGES}
    return StageAnalysis(PBLInterval(float(lower), float(upper), len(pbl), draws), probabilities)


@dataclass(frozen=True)
class ReviewPolicy:
    """Stage-aware referral rule; every threshold is fitted on development OOF only."""

    min_stage_probability: float = 0.9
    severe_guard: float | None = 0.1
    max_sigma_px: float | None = None

    def review(
        self,
        auto_stage: str,
        analysis: StageAnalysis,
        uncertainty_px: Mapping[str, float],
    ) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        own = analysis.probability(auto_stage)
        if own < self.min_stage_probability:
            reasons.append(
                f"stage {auto_stage} has only {own:.0%} Monte Carlo support "
                f"(threshold {self.min_stage_probability:.0%})"
            )
        severe = analysis.probability("III/IV")
        if self.severe_guard is not None and auto_stage != "III/IV" and severe >= self.severe_guard:
            reasons.append(
                f"possible missed Stage III/IV: P(III/IV) = {severe:.0%} "
                f"(guard {self.severe_guard:.0%})"
            )
        worst = max(uncertainty_px.values(), default=math.inf)
        if self.max_sigma_px is not None and worst > self.max_sigma_px:
            reasons.append(f"maximum landmark uncertainty {worst:.1f}px exceeds {self.max_sigma_px:.1f}px")
        return bool(reasons), tuple(reasons)

    def to_json(self) -> dict[str, float | None]:
        return asdict(self)

    @classmethod
    def from_json(cls, saved: Mapping[str, float | None]) -> "ReviewPolicy":
        return cls(
            min_stage_probability=float(saved["min_stage_probability"]),  # type: ignore[arg-type]
            severe_guard=None if saved.get("severe_guard") is None else float(saved["severe_guard"]),  # type: ignore[arg-type]
            max_sigma_px=None if saved.get("max_sigma_px") is None else float(saved["max_sigma_px"]),  # type: ignore[arg-type]
        )
