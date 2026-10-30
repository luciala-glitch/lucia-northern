from __future__ import annotations

import numpy as np
import pytest

from week4.dataset import consolidate_rounds
from week4.evaluate import evaluate
from week4.metrics import (
    downstream_agreement,
    landmark_metrics,
    metric_dicts,
    risk_coverage,
    uncertainty_error_correlation,
)
from week4.reproduce import reproduce
from week4.predict import AutoPrediction
from week4.uncertainty import PBLInterval, to_tooth_landmarks
from week3.pbl_calculator import calculate_tooth_pbl
import json
from pathlib import Path


def cases():
    base = {
        "mesial_cej": (30.0, 20.0),
        "distal_cej": (70.0, 20.0),
        "mesial_bc": (30.0, 35.0),
        "distal_bc": (70.0, 40.0),
        "apex": (50.0, 90.0),
    }
    second = {name: (x + 1, y + 1) for name, (x, y) in base.items()}
    return base, second


def test_landmark_metrics_separate_axial_error():
    truth = np.zeros((2, 5, 2))
    predicted = truth.copy()
    predicted[:, :, 1] = 3
    rows = landmark_metrics(truth, predicted, np.asarray([[0, 1], [0, 1]]))
    assert rows[0].mre_px == 3
    assert rows[0].along_axis_mae_px == 3
    assert rows[0].perpendicular_mae_px == 0
    assert rows[0].sdr_2px == 0
    assert metric_dicts(rows)[0]["landmark"] == "mesial_cej"


def test_metric_input_validation():
    with pytest.raises(ValueError, match="shape"):
        landmark_metrics(np.zeros((1, 2)), np.zeros((1, 2)), np.ones((1, 2)))
    with pytest.raises(ValueError, match="non-zero"):
        landmark_metrics(np.zeros((1, 5, 2)), np.zeros((1, 5, 2)), np.zeros((1, 2)))


def test_downstream_agreement_and_confusion():
    first, second = cases()
    output = downstream_agreement([first, second], [first, second])
    assert output["n"] == 2
    assert output["invalid_prediction_rate"] == 0
    assert sum(sum(row) for row in output["confusion_rows_manual_cols_predicted"]) == 2
    with pytest.raises(ValueError, match="At least two"):
        downstream_agreement([first], [first])


def test_calibration_and_risk_coverage():
    correlation = uncertainty_error_correlation([1, 2, 3], [1, 2, 4])
    assert correlation["pearson_r"] > 0.9
    curve = risk_coverage([3, 1, 2], [5, 1, 2], [False, True, True])
    assert curve["coverage"][-1] == 1
    assert curve["maximum_coverage_at_90pct_stage_accuracy"] is not None
    with pytest.raises(ValueError):
        uncertainty_error_correlation([1], [1])
    with pytest.raises(ValueError):
        risk_coverage([], [], [])


def test_reproduce_reports_honest_gate():
    status = reproduce()
    assert status["denpar_development_images"] == 20
    assert status["denpar_development_tooth_boxes"] == 90
    assert status["denpar_external_test_images"] == 20
    assert status["denpar_external_test_tooth_boxes"] == 92
    assert str(status["five_fold_split"]).startswith("blocked safely")
    with pytest.raises(Exception, match="At least 60"):
        reproduce(strict=True)


def test_evaluate_writes_agreement_and_plots(tmp_path):
    source = Path("week3/reports/collected_study/exports/measurements.json")
    dataset = consolidate_rounds(json.loads(source.read_text()))
    selected = dataset["annotations"][:3]
    images = {item["id"]: item for item in dataset["images"]}
    predictions = []
    for annotation in selected:
        points_here = {
            name: tuple(annotation["mean"][name]) for name in annotation["keypoint_names"]
        }
        result = calculate_tooth_pbl(to_tooth_landmarks(points_here))
        prediction = AutoPrediction(
            points_here,
            {name: 0.0 for name in points_here},
            PBLInterval(result.pbl_max_pct, result.pbl_max_pct, 1000, 1000),
            False,
            (),
        )
        image = images[annotation["image_id"]]
        predictions.append(
            prediction.to_record(
                image_id=image["file_name"],
                tooth_id=annotation["tooth_id"],
                condition=image["condition"],
            )
        )
    report = evaluate(dataset, predictions, tmp_path)
    assert report["n"] == 3
    assert report["downstream"]["invalid_prediction_rate"] == 0
    assert (tmp_path / "metrics.json").is_file()
    assert (tmp_path / "bland_altman.png").is_file()
    assert (tmp_path / "worst_predictions.png").is_file()
