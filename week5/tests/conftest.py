from __future__ import annotations

import json

import pytest

from week4.constants import LANDMARK_NAMES

from week5.tests.fakes import FakeHeatmapDetector


@pytest.fixture
def fake_refined(tmp_path, monkeypatch):
    """A calibration file plus ten (empty) checkpoint files the fake detector accepts."""
    import week4.learned

    FakeHeatmapDetector.correct_flip_y = False
    FakeHeatmapDetector.calls = []
    monkeypatch.setattr(week4.learned, "LearnedHeatmapDetector", FakeHeatmapDetector)
    weights = tmp_path / "weights"
    weights.mkdir()
    raw, clahe = [], []
    for fold in range(1, 6):
        for condition, bucket in (("raw", raw), ("clahe", clahe)):
            path = weights / f"{condition}_fold_{fold}.pt"
            path.write_bytes(b"")
            # ROOT / an absolute path is that absolute path, as the App resolves it.
            bucket.append(str(path))
    calibration = {
        "model": {"config": "test", "tta_margins": [0.06, 0.08, 0.10], "raw_checkpoints": raw, "clahe_checkpoints": clahe},
        "blend_raw_weight": {n: 0.5 for n in LANDMARK_NAMES},
        "sigma_scale": {n: 1.2 for n in LANDMARK_NAMES},
        "orientation_switch_ratio": 2.0,
        "review_policy": {"min_stage_probability": 0.9, "severe_guard": 0.1, "max_sigma_px": None},
        "external_labels_used": False,
        "fold_parameters": [],
    }
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration))
    monkeypatch.setenv("PBL_REFINED_CALIBRATION", str(path))
    return path
