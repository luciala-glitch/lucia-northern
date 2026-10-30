from __future__ import annotations

from io import BytesIO
import json
import numpy as np
from PIL import Image, ImageOps
import pytest

from week4.constants import LANDMARK_NAMES
from week4.errors import (
    CorruptedImageError,
    EmptyPredictionError,
    ImageValidationError,
    MissingImageError,
    UnsupportedImageError,
)
from week4.predict import (
    ClassicalLandmarkDetector,
    load_radiograph,
    predict_landmarks,
)
from week4.uncertainty import (
    PBLInterval,
    needs_review_by_margin,
    needs_manual_review,
    pbl_confidence_interval,
    to_tooth_landmarks,
)


def points():
    return {
        "mesial_cej": (30.0, 25.0),
        "distal_cej": (70.0, 25.0),
        "mesial_bc": (30.0, 40.0),
        "distal_bc": (70.0, 45.0),
        "apex": (50.0, 90.0),
    }


def image():
    array = np.tile(np.arange(120, dtype=np.uint8)[:, None], (1, 100))
    array[45:48] = 255
    return Image.fromarray(array)


def deep_crest_image():
    """Crest well apical to the mean-shape CEJ, so baseline uncertainty stays valid."""
    array = np.tile(np.arange(120, dtype=np.uint8)[:, None], (1, 100))
    array[72:120] = 230
    return Image.fromarray(array)


def png_bytes(im):
    buffer = BytesIO()
    im.save(buffer, format="PNG")
    return buffer.getvalue()


def test_load_validates_sources(tmp_path):
    path = tmp_path / "x.png"
    image().save(path)
    assert load_radiograph(path).size == (100, 120)
    assert load_radiograph(png_bytes(image())).mode == "L"
    assert load_radiograph(image()).size == (100, 120)
    with pytest.raises(MissingImageError):
        load_radiograph(tmp_path / "missing.png")
    with pytest.raises(CorruptedImageError):
        load_radiograph(b"not an image")
    with pytest.raises(UnsupportedImageError, match="dimensions"):
        load_radiograph(Image.new("L", (12, 12)))
    with pytest.raises(UnsupportedImageError, match="mode"):
        load_radiograph(Image.new("P", (40, 40)))


def test_classical_prediction_is_complete_schema_valid_and_reviewable():
    prediction = predict_landmarks(
        deep_crest_image(),
        (10, 5, 90, 110),
        detector=ClassicalLandmarkDetector(apex_at_bottom=True),
        draws=100,
    )
    assert set(prediction.landmarks) == set(LANDMARK_NAMES)
    record = prediction.to_record(
        image_id="synthetic.png", tooth_id=1, condition="clahe", round_number=2
    )
    assert record["source"] == "auto"
    assert record["condition"] == "clahe" and record["round"] == 2
    assert record["uncertainty"]["pbl_ci95"][0] <= record["uncertainty"]["pbl_ci95"][1]
    assert json.dumps(record, allow_nan=False)


def test_top_apex_and_right_mesial_path():
    prediction = predict_landmarks(
        ImageOps.flip(deep_crest_image()),
        (10, 5, 90, 110),
        detector=ClassicalLandmarkDetector(apex_at_bottom=False, mesial_on_left=False),
        draws=100,
    )
    assert prediction.landmarks["apex"][1] < prediction.landmarks["mesial_cej"][1]


class BadDetector:
    def __init__(self, output):
        self.output = output

    def predict(self, image, bbox):
        return self.output


def test_prediction_rejects_bbox_and_empty_nonfinite_outside_outputs():
    with pytest.raises(ImageValidationError, match="outside"):
        predict_landmarks(image(), (0, 0, 200, 100), draws=100)
    with pytest.raises(ImageValidationError, match="too small"):
        predict_landmarks(image(), (0, 0, 10, 20), draws=100)
    with pytest.raises(EmptyPredictionError, match="exactly"):
        predict_landmarks(image(), (0, 0, 80, 100), detector=BadDetector(({}, {})), draws=100)
    bad = points()
    bad["apex"] = (float("nan"), 90)
    with pytest.raises(EmptyPredictionError, match="non-finite"):
        predict_landmarks(
            image(), (0, 0, 80, 100), detector=BadDetector((bad, {k: 1 for k in bad})), draws=100
        )
    bad = points()
    bad["apex"] = (500, 90)
    with pytest.raises(EmptyPredictionError, match="outside"):
        predict_landmarks(
            image(), (0, 0, 80, 100), detector=BadDetector((bad, {k: 1 for k in bad})), draws=100
        )


def test_uncertainty_exact_interval_and_review_rules():
    uncertainty = {name: 0.0 for name in LANDMARK_NAMES}
    interval = pbl_confidence_interval(points(), uncertainty, draws=100)
    assert interval.lower == pytest.approx(interval.upper)
    rejected, reasons = needs_manual_review(PBLInterval(14, 16, 100, 100), uncertainty)
    assert rejected and "15%" in reasons[0]
    uncertainty["apex"] = 5.1
    rejected, reasons = needs_manual_review(PBLInterval(20, 21, 100, 100), uncertainty)
    assert rejected and "exceeds" in reasons[0]


def test_uncertainty_failure_cases():
    with pytest.raises(ValueError, match="At least 100"):
        pbl_confidence_interval(points(), {name: 1 for name in LANDMARK_NAMES}, draws=99)
    with pytest.raises(EmptyPredictionError, match="all five"):
        pbl_confidence_interval(points(), {"apex": 1}, draws=100)
    bad = {name: 1.0 for name in LANDMARK_NAMES}
    bad["apex"] = -1
    with pytest.raises(ValueError, match="cannot be negative"):
        pbl_confidence_interval(points(), bad, draws=100)
    incomplete = points()
    incomplete.pop("apex")
    with pytest.raises(EmptyPredictionError, match="Missing"):
        to_tooth_landmarks(incomplete)


def test_baseline_refuses_interval_when_uncertainty_swamps_tooth_geometry():
    # Mean-shape SD is ~9 px while CEJ-to-crest is ~3 px: most draws are invalid.
    with pytest.raises(EmptyPredictionError, match="guardrails"):
        predict_landmarks(image(), (10, 5, 90, 110), draws=100)


@pytest.mark.parametrize(
    "pbl, interval, flagged",
    [
        (14.0, (10.0, 18.0), True),   # 1 pp from 15%, half-width 4 -> 1 < 1.8
        (25.0, (20.0, 30.0), False),  # 8 pp from 33%, half-width 5
        (34.0, (33.5, 34.5), False),  # tight interval: 1 pp >= 0.45 x 0.5
        (32.0, (25.0, 40.0), True),
    ],
)
def test_margin_rule_flags_teeth_near_a_stage_boundary(pbl, interval, flagged):
    result, reasons = needs_review_by_margin(pbl, PBLInterval(*interval, 1000, 1000))
    assert result is flagged and bool(reasons) is flagged
