"""Prediction -> review -> correction -> recalculation -> export, without weights."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import copy
from io import BytesIO
import json
import math

import jsonschema
import numpy as np
from PIL import Image
import pytest

from week3.pbl_calculator import PBLValidationError
from week4 import app
from week4.constants import LANDMARK_NAMES
from week4.errors import CorruptedImageError, EmptyPredictionError, MissingImageError, UnsupportedImageError
from week4.predict import SCHEMA, predict_landmarks
from week5.refinement import RefinedLandmarkDetector, refined_ready
from week5.review import comparison_rows, validate_bundle
from week5.tests.fakes import FakeHeatmapDetector

BBOX = (100, 60, 260, 380)


def radiograph() -> Image.Image:
    rng = np.random.default_rng(3)
    return Image.fromarray(rng.integers(40, 200, (480, 400), dtype=np.uint8))


def test_refined_prediction_carries_stage_probabilities_and_valid_schema(fake_refined):
    detector = RefinedLandmarkDetector()
    prediction = predict_landmarks(radiograph(), BBOX, detector=detector)
    assert set(prediction.stage_probabilities) == {"I", "II", "III/IV"}
    assert prediction.result.stage == "I"
    assert not prediction.review_required, prediction.review_reasons
    record = prediction.to_record(image_id="x.png", tooth_id=1)
    jsonschema.validate(record, SCHEMA)
    # Three TTA margins x two preprocessing ensembles x two orientation hypotheses.
    assert len(FakeHeatmapDetector.calls) == 12


def test_orientation_self_check_switches_and_always_flags(fake_refined):
    FakeHeatmapDetector.correct_flip_y = True  # the reader's apex direction is wrong
    prediction = predict_landmarks(radiograph(), BBOX, detector=RefinedLandmarkDetector())
    assert prediction.review_required
    assert "orientation self-check" in prediction.review_reasons[0]
    # The switched hypothesis is the confident one.
    assert max(prediction.landmark_uncertainty_px.values()) < 5


def test_refined_detector_reports_missing_weights(fake_refined, tmp_path):
    saved = json.loads(fake_refined.read_text())
    saved["model"]["raw_checkpoints"][0] = str(tmp_path / "absent.pt")
    fake_refined.write_text(json.dumps(saved))
    assert not refined_ready()
    from week4.errors import ModelNotReadyError

    with pytest.raises(ModelNotReadyError, match="does not exist"):
        RefinedLandmarkDetector()


def test_corrupted_or_missing_calibration_is_not_ready(fake_refined):
    fake_refined.write_text("{not json")
    assert not refined_ready()
    fake_refined.unlink()
    assert not refined_ready()


@pytest.mark.parametrize(
    "source, error",
    [
        ("/definitely/missing.png", MissingImageError),
        (b"not an image at all", CorruptedImageError),
        (Image.new("L", (10, 10)), UnsupportedImageError),
    ],
)
def test_bad_images_fail_before_inference(fake_refined, source, error):
    with pytest.raises(error):
        predict_landmarks(source, BBOX, detector=RefinedLandmarkDetector())
    assert FakeHeatmapDetector.calls == []


def test_truncated_png_is_reported_as_corrupted(fake_refined):
    buffer = BytesIO()
    radiograph().save(buffer, format="PNG")
    with pytest.raises(CorruptedImageError):
        predict_landmarks(buffer.getvalue()[:200], BBOX, detector=RefinedLandmarkDetector())


class Broken:
    def __init__(self, points, sigma=None):
        self.points, self.sigma = points, sigma or {n: 2.0 for n in LANDMARK_NAMES}

    def predict(self, image, bbox):
        return self.points, self.sigma


GOOD = {"mesial_cej": (140, 100), "distal_cej": (220, 100), "mesial_bc": (140, 125), "distal_bc": (220, 126), "apex": (180, 360)}


@pytest.mark.parametrize(
    "points",
    [
        {k: v for k, v in GOOD.items() if k != "apex"},
        {**GOOD, "apex": (math.nan, 300.0)},
        {**GOOD, "apex": (180.0, 5000.0)},
    ],
)
def test_failed_or_invalid_detector_output_is_rejected(points):
    with pytest.raises(EmptyPredictionError):
        predict_landmarks(radiograph(), BBOX, detector=Broken(points))


def test_anatomically_impossible_prediction_is_rejected():
    with pytest.raises(PBLValidationError):
        predict_landmarks(radiograph(), BBOX, detector=Broken({**GOOD, "apex": (180, 90)}))


def bundle_for(prediction, points):
    corrected = app._corrected_prediction(points, prediction)
    original = prediction.to_record(image_id="x.png", tooth_id=1)
    manual = corrected.to_record(image_id="x.png", tooth_id=1, source="manual")
    auto_canvas = {app.TO_CANVAS[k]: v for k, v in prediction.landmarks.items()}
    moved = {
        app.FROM_CANVAS[n]: float(np.hypot(points[n][0] - auto_canvas[n][0], points[n][1] - auto_canvas[n][1]))
        for n in app.CANVAS_NAMES
    }
    return corrected, {
        "saved_at_utc": "2026-11-05T00:00:00+00:00", "annotator_role": "qualified_reviewer",
        "reviewer_id": "R1", "detector": {"name": "test", "checkpoints": []},
        "review_flagged": prediction.review_required, "review_reasons": list(prediction.review_reasons),
        "auto_stage_probabilities": prediction.stage_probabilities, "moved_px": moved,
        "seconds_since_suggestion": 3.0, "blind_first_read": None, "review_context": {},
        "original_prediction": original, "corrected_result": manual,
    }


def test_correction_recalculates_immediately_and_never_touches_the_original(fake_refined, tmp_path, monkeypatch):
    prediction = predict_landmarks(radiograph(), BBOX, detector=RefinedLandmarkDetector())
    before = copy.deepcopy(dict(prediction.landmarks))
    points = {app.TO_CANVAS[k]: tuple(round(c) for c in v) for k, v in prediction.landmarks.items()}
    # Move both crests 100 px apically: Stage I -> Stage III/IV.
    for name in ("mesial.bc", "distal.bc"):
        points[name] = (points[name][0], points[name][1] + 100)
    corrected, bundle = bundle_for(prediction, points)
    assert corrected.result.stage == "III/IV"
    assert corrected.result.pbl_max_pct > prediction.result.pbl_max_pct + 20
    assert dict(prediction.landmarks) == before
    with pytest.raises(FrozenInstanceError):
        prediction.landmarks = {}  # type: ignore[misc]
    validate_bundle(bundle)
    rows = comparison_rows(bundle)
    assert rows[-1]["Outside AI 95% radius"] == "stage changed"
    assert {r["Outside AI 95% radius"] for r in rows if r["Landmark"].endswith("_bc")} == {"yes"}
    # Untouched markers keep their exact automatic coordinates.
    assert corrected.landmarks["apex"] == prediction.landmarks["apex"]

    monkeypatch.setattr(app, "CORRECTIONS", tmp_path / "corrections.json")
    app._save_bundle(bundle)
    app._save_bundle({**bundle, "reviewer_id": "R2"})
    app._save_bundle(bundle)  # re-save replaces R1's slot instead of duplicating it
    saved = json.loads((tmp_path / "corrections.json").read_text())
    assert [s["reviewer_id"] for s in saved] == ["R2", "R1"]
    for entry in saved:
        validate_bundle(entry)
        assert entry["original_prediction"]["source"] == "auto"
        assert entry["original_prediction"]["landmarks"]["apex"] == list(before["apex"])


def test_invalid_correction_is_refused_by_the_calculator(fake_refined):
    prediction = predict_landmarks(radiograph(), BBOX, detector=RefinedLandmarkDetector())
    points = {app.TO_CANVAS[k]: tuple(round(c) for c in v) for k, v in prediction.landmarks.items()}
    points["apex"] = (points["apex"][0], 20)  # apex above the CEJ
    with pytest.raises(PBLValidationError):
        app._corrected_prediction(points, prediction)


def test_bundle_schema_rejects_overwritten_or_mismatched_records(fake_refined):
    prediction = predict_landmarks(radiograph(), BBOX, detector=RefinedLandmarkDetector())
    points = {app.TO_CANVAS[k]: tuple(round(c) for c in v) for k, v in prediction.landmarks.items()}
    _, bundle = bundle_for(prediction, points)
    validate_bundle(bundle)
    overwritten = copy.deepcopy(bundle)
    overwritten["original_prediction"] = copy.deepcopy(bundle["corrected_result"])
    with pytest.raises(jsonschema.ValidationError):
        validate_bundle(overwritten)
    other_tooth = copy.deepcopy(bundle)
    other_tooth["corrected_result"]["tooth_id"] = 2
    with pytest.raises(jsonschema.ValidationError, match="tooth_id"):
        validate_bundle(other_tooth)
    broken = copy.deepcopy(bundle)
    broken["corrected_result"]["metrics"]["stage"] = "V"
    with pytest.raises(jsonschema.ValidationError):
        validate_bundle(broken)
    missing = {k: v for k, v in bundle.items() if k != "moved_px"}
    with pytest.raises(jsonschema.ValidationError):
        validate_bundle(missing)
