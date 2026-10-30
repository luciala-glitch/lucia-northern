"""Generate held-out landmark, downstream-agreement, and rejection reports."""

from __future__ import annotations

import argparse
import csv
from io import StringIO
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from week3.pbl_calculator import calculate_tooth_pbl, long_axis
from week3.statistics import agreement
from week4.constants import LANDMARK_NAMES
from week4.metrics import (
    STAGE_CODE,
    downstream_agreement,
    landmark_metrics,
    metric_dicts,
    risk_coverage,
    uncertainty_error_correlation,
)
from week4.uncertainty import to_tooth_landmarks


def _record_points(record: dict[str, Any]) -> dict[str, tuple[float, float]]:
    lm = record["landmarks"]
    return {
        "mesial_cej": tuple(map(float, lm["mesial"]["cej"])),
        "distal_cej": tuple(map(float, lm["distal"]["cej"])),
        "mesial_bc": tuple(map(float, lm["mesial"]["bc"])),
        "distal_bc": tuple(map(float, lm["distal"]["bc"])),
        "apex": tuple(map(float, lm["apex"])),
    }


def _annotation_points(annotation: dict[str, Any], field: str = "mean") -> dict[str, tuple[float, float]]:
    return {
        name: tuple(map(float, annotation[field][name])) for name in LANDMARK_NAMES
    }


def _annotation_round_points(
    annotation: dict[str, Any], round_number: int
) -> dict[str, tuple[float, float]]:
    values = annotation["rounds"][str(round_number)]
    return {name: tuple(map(float, values[name])) for name in LANDMARK_NAMES}


def _plot_bland_altman(manual: np.ndarray, predicted: np.ndarray, path: Path) -> None:
    difference = predicted - manual
    means = (manual + predicted) / 2
    bias = difference.mean()
    sd = difference.std(ddof=1)
    figure, axis = plt.subplots(figsize=(6.4, 4.2))
    axis.scatter(means, difference, s=25, alpha=0.75)
    axis.axhline(bias, color="#146c94", label=f"Bias {bias:.2f}")
    axis.axhline(bias - 1.96 * sd, color="#b33", linestyle="--")
    axis.axhline(bias + 1.96 * sd, color="#b33", linestyle="--", label="95% LoA")
    axis.set(xlabel="Mean manual/predicted PBL (%)", ylabel="Predicted − manual (percentage points)")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _plot_confusion(matrix: np.ndarray, path: Path) -> None:
    labels = ["I", "II", "III/IV"]
    figure, axis = plt.subplots(figsize=(4.8, 4.2))
    image = axis.imshow(matrix, cmap="Blues")
    for row in range(3):
        for column in range(3):
            axis.text(column, row, str(matrix[row, column]), ha="center", va="center")
    axis.set_xticks(range(3), labels=labels)
    axis.set_yticks(range(3), labels=labels)
    axis.set(xlabel="Predicted stage", ylabel="Manual stage")
    figure.colorbar(image, ax=axis, shrink=0.8)
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _plot_risk_coverage(curve: dict[str, Any], path: Path) -> None:
    coverage = np.asarray(curve["coverage"])
    figure, first = plt.subplots(figsize=(6.4, 4.2))
    first.plot(coverage, curve["accepted_mae_pct_points"], color="#b33", label="PBL MAE")
    first.set(xlabel="Accepted fraction (coverage)", ylabel="Accepted PBL MAE (percentage points)")
    second = first.twinx()
    second.plot(coverage, curve["accepted_stage_accuracy"], color="#146c94", label="Stage accuracy")
    second.axhline(0.90, color="#146c94", linestyle="--", alpha=0.5)
    second.set_ylabel("Accepted stage accuracy")
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _image_path(file_name: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    if file_name.startswith("denpar_development_"):
        return root / "week4" / "demo_denpar" / "development" / "images" / file_name.removeprefix("denpar_development_")
    if file_name.startswith("denpar_external_test_"):
        return root / "week4" / "demo_denpar" / "external_test" / "images" / file_name.removeprefix("denpar_external_test_")
    return root / "week2" / "sample_xrays" / file_name


def _plot_worst_predictions(
    keys: list[tuple[str, int, str]],
    manual: list[dict[str, tuple[float, float]]],
    predicted: list[dict[str, tuple[float, float]]],
    path: Path,
) -> None:
    radial = np.asarray(
        [
            np.mean([np.linalg.norm(np.asarray(estimate[name]) - truth[name]) for name in LANDMARK_NAMES])
            for truth, estimate in zip(manual, predicted)
        ]
    )
    worst = np.argsort(radial)[::-1][:5]
    figure, axes = plt.subplots(len(worst), 1, figsize=(7, 4 * len(worst)), squeeze=False)
    for row, index in enumerate(worst):
        axis = axes[row, 0]
        truth, estimate = manual[index], predicted[index]
        image_path = _image_path(keys[index][0])
        if image_path.is_file():
            axis.imshow(Image.open(image_path).convert("L"), cmap="gray")
        manual_axis = np.asarray(long_axis(to_tooth_landmarks(truth)))
        errors = np.asarray(
            [np.asarray(estimate[name]) - np.asarray(truth[name]) for name in LANDMARK_NAMES]
        )
        along = float(np.mean(np.abs(errors @ manual_axis)))
        for name in LANDMARK_NAMES:
            expected, observed = truth[name], estimate[name]
            axis.plot([expected[0], observed[0]], [expected[1], observed[1]], color="#ff4d4d", linewidth=1)
            axis.scatter(*expected, c="#55e06f", s=25, marker="o")
            axis.scatter(*observed, c="#ff4d4d", s=25, marker="x")
        mid_cej = np.mean([truth["mesial_cej"], truth["distal_cej"]], axis=0)
        apex = np.asarray(truth["apex"])
        axis.plot([mid_cej[0], apex[0]], [mid_cej[1], apex[1]], color="#55e06f", linestyle="--")
        coordinates = np.asarray([*truth.values(), *estimate.values()])
        low, high = coordinates.min(axis=0), coordinates.max(axis=0)
        margin = np.maximum((high - low) * 0.35, 30)
        axis.set_xlim(low[0] - margin[0], high[0] + margin[0])
        axis.set_ylim(high[1] + margin[1], low[1] - margin[1])
        axis.set_title(
            f"{keys[index][0]} · tooth {keys[index][1]} · MRE {radial[index]:.1f}px · along-axis MAE {along:.1f}px"
        )
        axis.axis("off")
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def evaluate(
    dataset: dict[str, Any], predictions: list[dict[str, Any]], output: Path
) -> dict[str, Any]:
    images = {int(item["id"]): item for item in dataset["images"]}
    annotations = {
        (
            images[int(item["image_id"])]["file_name"],
            int(item["tooth_id"]),
            images[int(item["image_id"])]["condition"],
        ): item
        for item in dataset["annotations"]
    }
    prediction_lookup = {
        (item["image_id"], int(item["tooth_id"]), item["condition"]): item
        for item in predictions
    }
    keys = sorted(set(annotations) & set(prediction_lookup))
    if len(keys) < 2:
        raise ValueError("At least two aligned held-out predictions are required")
    manual = [_annotation_points(annotations[key]) for key in keys]
    predicted = [_record_points(prediction_lookup[key]) for key in keys]
    manual_array = np.asarray([[points[name] for name in LANDMARK_NAMES] for points in manual])
    predicted_array = np.asarray([[points[name] for name in LANDMARK_NAMES] for points in predicted])
    axes = np.asarray([long_axis(to_tooth_landmarks(points)) for points in manual])
    landmark_rows = metric_dicts(landmark_metrics(manual_array, predicted_array, axes))
    downstream = downstream_agreement(manual, predicted)

    manual_results = [calculate_tooth_pbl(to_tooth_landmarks(points)) for points in manual]
    predicted_results = [calculate_tooth_pbl(to_tooth_landmarks(points)) for points in predicted]
    manual_pbl = np.asarray([result.pbl_max_pct for result in manual_results])
    predicted_pbl = np.asarray([result.pbl_max_pct for result in predicted_results])
    stage_correct = np.asarray(
        [a.stage == b.stage for a, b in zip(manual_results, predicted_results)]
    )
    uncertainty = np.asarray(
        [
            max(prediction_lookup[key]["uncertainty"]["landmark_px"].values())
            for key in keys
        ]
    )
    pbl_error = np.abs(predicted_pbl - manual_pbl)
    calibration = uncertainty_error_correlation(uncertainty, pbl_error)
    coverage = risk_coverage(uncertainty, pbl_error, stage_correct)

    round_one, round_two = [], []
    for key in keys:
        annotation = annotations[key]
        round_one.append(
            calculate_tooth_pbl(
                to_tooth_landmarks(_annotation_round_points(annotation, 1))
            )
        )
        round_two.append(
            calculate_tooth_pbl(
                to_tooth_landmarks(_annotation_round_points(annotation, 2))
            )
        )
    human = agreement(
        [item.pbl_max_pct for item in round_one],
        [item.pbl_max_pct for item in round_two],
        [STAGE_CODE[item.stage] for item in round_one],
        [STAGE_CODE[item.stage] for item in round_two],
    )
    human_width = human.loa_upper - human.loa_lower
    model_width = float(downstream["loa_upper"]) - float(downstream["loa_lower"])
    comparison = {
        "human_loa_width": human_width,
        "model_loa_width": model_width,
        "model_minus_human_loa_width": model_width - human_width,
        "model_no_wider_than_human": model_width <= human_width,
    }
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "n": len(keys),
        "landmark_metrics": landmark_rows,
        "downstream": downstream,
        "uncertainty_error_correlation": calibration,
        "risk_coverage": coverage,
        "human_repeatability_comparison": comparison,
    }
    (output / "metrics.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(landmark_rows[0]))
    writer.writeheader()
    writer.writerows(landmark_rows)
    (output / "landmark_metrics.csv").write_text(buffer.getvalue())
    _plot_bland_altman(manual_pbl, predicted_pbl, output / "bland_altman.png")
    _plot_confusion(
        np.asarray(downstream["confusion_rows_manual_cols_predicted"]),
        output / "stage_confusion.png",
    )
    _plot_risk_coverage(coverage, output / "risk_coverage.png")
    _plot_worst_predictions(keys, manual, predicted, output / "worst_predictions.png")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("week4/reports/evaluation"))
    args = parser.parse_args()
    report = evaluate(
        json.loads(args.dataset.read_text()),
        json.loads(args.predictions.read_text()),
        args.output,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
