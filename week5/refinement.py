"""Week 5 refined detector: Raw/CLAHE ensemble, test-time augmentation, an
orientation self-check, calibrated uncertainty and a stage-aware review policy.

Every parameter in ``reports/calibration.json`` is fitted on development
out-of-fold predictions only (``python -m week5.evaluate``). For a held-out
development fold, parameters come from the other four folds. The external
test labels are never used for fitting.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from week3.image_processing import preprocess
from week3.pbl_calculator import calculate_tooth_pbl
from week4.constants import LANDMARK_NAMES, SEED
from week4.errors import ModelNotReadyError
from week4.predict import BBox, Point
from week4.training import canonical_crop
from week4.uncertainty import PBLInterval, to_tooth_landmarks
from week5.uncertainty import ReviewPolicy, stage_analysis, widen_interval

ROOT = Path(__file__).resolve().parents[1]
# PBL_REFINED_CALIBRATION overrides it (tests point it at a temporary file).
DEFAULT_CALIBRATION = ROOT / "week5" / "reports" / "calibration.json"
Prediction = tuple[dict[str, Point], dict[str, float]]


def fit_blend_weights(
    teeth: Sequence[dict[str, Any]],
    raw: Mapping[int, dict[str, Any]],
    clahe: Mapping[int, dict[str, Any]],
) -> dict[str, float]:
    """Least-squares convex Raw weight per landmark (CLAHE weight is 1-w)."""
    weights: dict[str, float] = {}
    for name in LANDMARK_NAMES:
        delta = np.concatenate(
            [np.asarray(raw[int(t["id"])]["points"][name], dtype=float) - np.asarray(clahe[int(t["id"])]["points"][name], dtype=float) for t in teeth]
        )
        target = np.concatenate(
            [np.asarray(t["truth"][name], dtype=float) - np.asarray(clahe[int(t["id"])]["points"][name], dtype=float) for t in teeth]
        )
        # Explicit sums avoid platform-specific BLAS overflow warnings observed
        # with NumPy 2 on otherwise small finite vectors.
        denominator = float(np.sum(delta * delta, dtype=np.float64))
        numerator = float(np.sum(delta * target, dtype=np.float64))
        weight = 0.5 if denominator < 1e-12 else numerator / denominator
        weights[name] = float(np.clip(weight, 0.0, 1.0))
    return weights


def blend_prediction(
    raw: Mapping[str, Any],
    clahe: Mapping[str, Any],
    weights: Mapping[str, float],
    sigma_scale: Mapping[str, float] | None = None,
) -> tuple[dict[str, Point], dict[str, float], dict[str, float]]:
    """Blend coordinates and combine heatmap spread with model disagreement."""
    points: dict[str, Point] = {}
    sigma: dict[str, float] = {}
    disagreement: dict[str, float] = {}
    scales = sigma_scale or {name: 1.0 for name in LANDMARK_NAMES}
    for index, name in enumerate(LANDMARK_NAMES):
        w = float(weights[name])
        a = np.asarray(raw["points"][name], dtype=float)
        b = np.asarray(clahe["points"][name], dtype=float)
        point = w * a + (1.0 - w) * b
        gap = float(np.linalg.norm(a - b))
        raw_sigma = float(raw["sigma"][index] if isinstance(raw["sigma"], list) else raw["sigma"][name])
        clahe_sigma = float(clahe["sigma"][index] if isinstance(clahe["sigma"], list) else clahe["sigma"][name])
        base = np.sqrt(w * raw_sigma**2 + (1.0 - w) * clahe_sigma**2 + w * (1.0 - w) * gap**2 / 2.0)
        points[name] = tuple(map(float, point))
        sigma[name] = float(base * float(scales.get(name, 1.0)))
        disagreement[name] = gap
    return points, sigma, disagreement


# sqrt of the chi-square(2) 95% quantile: a 2-D isotropic Gaussian's 95% radius in SDs.
RADIUS_95 = 2.447746830680816


def fit_sigma_scales(
    teeth: Sequence[dict[str, Any]],
    predictions: Sequence[Prediction],
) -> dict[str, float]:
    """Scale 1-SD radii so the nominal 95% radius has empirical 95% radial coverage."""
    ratios: dict[str, list[float]] = {name: [] for name in LANDMARK_NAMES}
    for tooth, (points, sigma) in zip(teeth, predictions):
        for name in LANDMARK_NAMES:
            error = float(np.linalg.norm(np.asarray(points[name]) - np.asarray(tooth["truth"][name])))
            ratios[name].append(error / max(sigma[name], 1e-6))
    return {
        name: float(np.clip(np.quantile(values, 0.95) / RADIUS_95, 0.25, 4.0))
        for name, values in ratios.items()
    }


def combine_views(views: Sequence[Prediction]) -> Prediction:
    """Average test-time views; their spread is added to the mean heatmap variance."""
    points = {name: tuple(np.mean([v[0][name] for v in views], axis=0).tolist()) for name in LANDMARK_NAMES}
    sigma = {
        name: float(np.sqrt(
            np.mean([v[1][name] ** 2 for v in views])
            + (float(np.sum(np.var([v[0][name] for v in views], axis=0))) / 2 if len(views) > 1 else 0.0)
        ))
        for name in LANDMARK_NAMES
    }
    return points, sigma  # type: ignore[return-value]


def orientation_ratio(given: Mapping[str, float], flipped: Mapping[str, float]) -> float:
    """Mean uncertainty under the reader's orientation over the reversed hypothesis.

    Values well above 1 mean the detector is far more certain with the apex
    the other way up, the signature of wrong orientation metadata.
    """
    return float(np.mean([given[n] for n in LANDMARK_NAMES]) / max(np.mean([flipped[n] for n in LANDMARK_NAMES]), 1e-6))


def review_prediction(
    points: Mapping[str, Point],
    sigma: Mapping[str, float],
    policy: ReviewPolicy,
    *,
    draws: int = 1000,
    seed: int = SEED,
    extra_reasons: Sequence[str] = (),
    interval_factor: float = 1.0,
) -> tuple[PBLInterval, bool, tuple[str, ...], dict[str, float]]:
    analysis = stage_analysis(points, sigma, draws=draws, seed=seed)
    result = calculate_tooth_pbl(to_tooth_landmarks(points))
    flagged, reasons = policy.review(result.stage, analysis, sigma)
    reasons = (*extra_reasons, *reasons)
    interval = widen_interval(analysis.interval, result.pbl_max_pct, interval_factor)
    return interval, bool(reasons) or flagged, reasons, analysis.probabilities


def _calibration_path() -> Path:
    return Path(os.environ.get("PBL_REFINED_CALIBRATION", DEFAULT_CALIBRATION))


def load_calibration(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path is not None else _calibration_path()
    if not path.is_file():
        raise ModelNotReadyError(f"Week 5 calibration is missing: {path}. Run python -m week5.evaluate first.")
    return json.loads(path.read_text())


def calibrated_checkpoints(calibration: Mapping[str, Any]) -> tuple[list[Path], list[Path]]:
    """Checkpoint paths named in the calibration, relative to the repository root."""
    model = calibration["model"]
    return (
        [ROOT / p for p in model["raw_checkpoints"]],
        [ROOT / p for p in model["clahe_checkpoints"]],
    )


def refined_ready(path: str | Path | None = None) -> bool:
    """True when the calibration file and all ten checkpoints it names exist."""
    try:
        raw, clahe = calibrated_checkpoints(load_calibration(path))
    except (ModelNotReadyError, KeyError, json.JSONDecodeError):
        return False
    return len(raw) == len(clahe) == 5 and all(p.is_file() for p in raw + clahe)


class RefinedLandmarkDetector:
    """Raw/CLAHE fold ensembles with development-only calibration and review policy."""

    condition = "raw+clahe"

    def __init__(
        self,
        raw_checkpoints: Sequence[str | Path] | None = None,
        clahe_checkpoints: Sequence[str | Path] | None = None,
        *,
        calibration: str | Path | None = None,
        apex_at_bottom: bool = True,
        mesial_on_left: bool = True,
        device: str | None = None,
    ) -> None:
        saved = load_calibration(calibration)
        self.weights = {name: float(saved["blend_raw_weight"][name]) for name in LANDMARK_NAMES}
        self.sigma_scale = {name: float(saved["sigma_scale"][name]) for name in LANDMARK_NAMES}
        self.margins = tuple(float(m) for m in saved["model"]["tta_margins"])
        ratio = saved.get("orientation_switch_ratio")
        self.orientation_switch_ratio = None if ratio is None else float(ratio)
        self.policy = ReviewPolicy.from_json(saved["review_policy"])
        self.interval_factor = float(saved.get("pbl_interval_factor", 1.0))
        default_raw, default_clahe = calibrated_checkpoints(saved)
        from week4.learned import LearnedHeatmapDetector

        self.raw = LearnedHeatmapDetector(list(raw_checkpoints or default_raw), device=device)
        self.clahe = LearnedHeatmapDetector(list(clahe_checkpoints or default_clahe), device=device)
        self.apex_at_bottom = apex_at_bottom
        self.mesial_on_left = mesial_on_left
        self.orientation_note: str | None = None

    def _views(self, detector: Any, image: Image.Image, bbox: BBox, apex_at_bottom: bool) -> Prediction:
        source = preprocess(image, detector.condition)
        crops = [
            canonical_crop(source, bbox, apex_at_bottom=apex_at_bottom, mesial_on_left=self.mesial_on_left, margin=m)
            for m in self.margins
        ]
        return combine_views(detector.predict_crops(crops))

    def _hypothesis(self, image: Image.Image, bbox: BBox, apex_at_bottom: bool) -> Prediction:
        raw_points, raw_sigma = self._views(self.raw, image, bbox, apex_at_bottom)
        clahe_points, clahe_sigma = self._views(self.clahe, image, bbox, apex_at_bottom)
        points, sigma, _ = blend_prediction(
            {"points": raw_points, "sigma": raw_sigma},
            {"points": clahe_points, "sigma": clahe_sigma},
            self.weights,
            self.sigma_scale,
        )
        return points, sigma

    def predict(self, image: Image.Image, bbox: BBox) -> Prediction:
        given = self._hypothesis(image, bbox, self.apex_at_bottom)
        self.orientation_note = None
        if self.orientation_switch_ratio is None:
            return given
        flipped = self._hypothesis(image, bbox, not self.apex_at_bottom)
        ratio = orientation_ratio(given[1], flipped[1])
        if ratio >= self.orientation_switch_ratio:
            self.orientation_note = (
                f"orientation self-check: the detector is {ratio:.1f}x more certain with the apex "
                f"{'at the top' if self.apex_at_bottom else 'at the bottom'}; landmarks use that "
                "orientation — confirm the crown/apex direction"
            )
            return flipped
        return given

    def review(
        self, points: Mapping[str, Point], sigma: Mapping[str, float], *, draws: int = 1000
    ) -> tuple[PBLInterval, bool, tuple[str, ...], dict[str, float]]:
        """Hook used by ``week4.predict.predict_landmarks``."""
        extra = (self.orientation_note,) if self.orientation_note else ()
        return review_prediction(
            points, sigma, self.policy, draws=draws, extra_reasons=extra, interval_factor=self.interval_factor
        )
