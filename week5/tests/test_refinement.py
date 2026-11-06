from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from week4.constants import LANDMARK_NAMES
from week4.errors import ModelNotReadyError
from week5.refinement import RefinedLandmarkDetector, blend_prediction, fit_blend_weights


def row(offset: float, sigma: float = 2.0):
    return {
        "points": {name: [index + offset, index * 2 + offset] for index, name in enumerate(LANDMARK_NAMES)},
        "sigma": [sigma] * 5,
    }


def tooth(identifier: int, offset: float):
    return {
        "id": identifier,
        "truth": {name: [index + offset, index * 2 + offset] for index, name in enumerate(LANDMARK_NAMES)},
    }


def test_blend_is_convex_and_preserves_all_landmarks():
    raw, clahe = row(2), row(0)
    points, sigma, disagreement = blend_prediction(raw, clahe, {name: 0.25 for name in LANDMARK_NAMES})
    assert set(points) == set(sigma) == set(disagreement) == set(LANDMARK_NAMES)
    assert points["apex"] == pytest.approx((4.5, 8.5))
    assert disagreement["apex"] == pytest.approx(np.sqrt(8))
    assert sigma["apex"] > 0


def test_fit_recovers_raw_when_raw_matches_truth():
    teeth = [tooth(1, 2), tooth(2, 3)]
    raw = {1: row(2), 2: row(3)}
    clahe = {1: row(0), 2: row(1)}
    weights = fit_blend_weights(teeth, raw, clahe)
    assert all(value == pytest.approx(1.0) for value in weights.values())


def test_missing_calibration_fails_before_model_loading(tmp_path):
    with pytest.raises(ModelNotReadyError, match="calibration is missing"):
        RefinedLandmarkDetector([], [], calibration=tmp_path / "missing.json")


def test_saved_calibration_never_used_external_labels():
    path = Path(__file__).parents[1] / "reports" / "calibration.json"
    saved = json.loads(path.read_text())
    assert saved["external_labels_used"] is False
    assert len(saved["fold_parameters"]) == 5
    assert set(saved["blend_raw_weight"]) == set(LANDMARK_NAMES)

